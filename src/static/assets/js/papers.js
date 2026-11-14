// 流光咖啡馆 · 论文库与阅读器（第 3 批）
// 库页：添加（标题/DOI/arXiv）、四段阶段条、失败原因 + 手动重试、逐篇共享
// 阅读器：blocks 渲染、批注（anchor 点回原文）、右栏单篇问答（出处点回 flash）
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;
  const { api, openModal, esc } = LC;

  const PHASES = [
    ["fetch", "获取全文"],
    ["upload", "上传"],
    ["queue", "排队"],
    ["parse", "解析"],
  ];

  /* ================= 论文库页 ================= */
  const lib = { items: [], poll: null };

  function phaseBar(item) {
    const idx = PHASES.findIndex(([k]) => k === item.phase);
    const failed = item.phase === "failed";
    const done = item.phase === "done";
    return `<div class="phase-bar ${failed ? "failed" : ""}">
      ${PHASES.map(([k, name], i) => {
        const lit = done || i < (idx === -1 ? 0 : idx);
        const cur = !done && !failed && i === idx;
        return `<span class="phase-seg ${lit ? "lit" : ""} ${cur ? "cur" : ""}">${name}</span>`;
      }).join('<span class="phase-arrow">→</span>')}
      ${done ? '<span class="phase-seg lit">完成</span>' : ""}
      ${failed ? '<span class="phase-seg fail">失败</span>' : ""}
    </div>`;
  }

  function libHtml() {
    return `<div class="money-page papers-page">
      <div class="money-head-row">
        <h1 class="stage-title" style="margin:0">论文库</h1>
        <div class="paper-add">
          <input class="text-input paper-add-input" placeholder="标题 / DOI / arXiv 编号">
          <button class="btn btn-primary" data-add-paper>添加并解析</button>
        </div>
      </div>
      <div class="paper-list">
        ${lib.items.map((it) => `
        <article class="paper-card" data-item="${it.id}">
          <div class="paper-main">
            <div class="paper-title">${esc(it.title)}</div>
            <div class="paper-meta">${esc(it.authors || "未知作者")} · ${esc(it.journal || "")} ${it.year ?? ""}${it.shared ? ' <span class="tag soon">共享</span>' : ""}${it.mine ? "" : ' <span class="tag">对方的</span>'}</div>
            ${phaseBar(it)}
            ${it.phase === "failed" ? `<div class="paper-error">失败：${esc(it.fail_class || "")} ${esc(it.phase_error || "")}</div>` : ""}
            ${it.phase === "done" ? `<div class="paper-ok">${esc(it.phase_error || "")}</div>` : ""}
          </div>
          <div class="paper-ops">
            ${it.phase === "done" ? `<a class="btn btn-ghost" href="#/papers/${it.id}">阅读</a>` : ""}
            ${it.phase === "failed" && it.mine ? `<button class="btn btn-primary" data-retry="${it.id}">手动重试</button>` : ""}
            ${it.mine ? `<button class="btn btn-ghost" data-share="${it.id}">${it.shared ? "取消共享" : "共享"}</button>
            <button class="conv-op" data-del-paper="${it.id}">${LC.IC.close}</button>` : ""}
          </div>
        </article>`).join("") || `<div class="empty-hint">库里还没有论文。添加一篇试试，后台会自动找全文并解析。</div>`}
      </div>
    </div>`;
  }

  async function loadLibrary() {
    const data = await api("/api/papers/library");
    lib.items = data.items;
  }

  function startPoll(render) {
    clearInterval(lib.poll);
    lib.poll = setInterval(async () => {
      try {
        await loadLibrary();
        render();
        if (!lib.items.some((i) => !["done", "failed"].includes(i.phase))) clearInterval(lib.poll);
      } catch { /* 轮询静默失败，下次再试 */ }
    }, 3000);
  }

  async function mountLibrary(container) {
    container.innerHTML = libHtml();
    const render = () => { container.innerHTML = libHtml(); };
    try { await loadLibrary(); } catch (e) { container.innerHTML = `<div class="empty-hint">加载失败：${esc(e.message)}</div>`; return; }
    render();
    if (lib.items.some((i) => !["done", "failed"].includes(i.phase))) startPoll(render);

    container.addEventListener("click", async (e) => {
      if (e.target.closest("[data-add-paper]")) {
        const input = container.querySelector(".paper-add-input");
        const value = input.value.trim();
        if (!value) return;
        const btn = e.target.closest("[data-add-paper]");
        btn.disabled = true;
        try {
          await api("/api/papers/library", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input: value, request_id: crypto.randomUUID() }),
          });
          input.value = "";
          await loadLibrary(); render(); startPoll(render);
        } catch (err) {
          alert(err.message);
          btn.disabled = false;
        }
        return;
      }
      const retry = e.target.closest("[data-retry]");
      if (retry) {
        await api(`/api/papers/library/${retry.dataset.retry}/retry`, { method: "POST" });
        await loadLibrary(); render(); startPoll(render);
        return;
      }
      const share = e.target.closest("[data-share]");
      if (share) {
        const it = lib.items.find((x) => String(x.id) === share.dataset.share);
        await api(`/api/papers/library/${it.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shared: !it.shared }) });
        await loadLibrary(); render();
        return;
      }
      const del = e.target.closest("[data-del-paper]");
      if (del) {
        openModal("移出论文库", "<p>条目、解析内容和你的批注都会删除（对方的共享视图也会消失）。PDF 原件保留在存储里。</p>",
          `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" id="pd-ok">删除</button>`);
        document.getElementById("pd-ok")?.addEventListener("click", async () => {
          await api(`/api/papers/library/${del.dataset.delPaper}`, { method: "DELETE" });
          LC.closeModal(); await loadLibrary(); render();
        });
      }
    });
  }

  function cleanupLibrary() { clearInterval(lib.poll); }

  /* ================= 阅读器 ================= */
  const rd = { itemId: null, item: null, blocks: [], annotations: [], qa: [], anchor: null, busy: false, poll: null };

  function blockHtml(b) {
    const notes = rd.annotations.filter((a) => a.anchor_block === b.block_idx);
    const tag = b.block_type === "heading" ? `h${Math.min((b.text_level || 1) + 1, 5)}` : "p";
    const cls = b.block_type === "heading" ? `paper-block heading lvl${b.text_level || 1}` : "paper-block";
    return `<${tag} class="${cls}" data-block="${b.block_idx}" data-anchor="${b.block_idx}">
      ${esc(b.content)}
      <button class="anno-dot" data-anchor-block="${b.block_idx}" title="批注这条">${LC.IC.chat}${notes.length ? `<span class="anno-count">${notes.length}</span>` : ""}</button>
    </${tag}>`;
  }

  function readerHtml() {
    const conv = rd.qa;
    return `<div class="reader-wrap">
      <div class="reader-main">
        <div class="reader-head">
          <a class="icon-btn" href="#/papers" title="返回论文库">${LC.IC.arrow}</a>
          <div class="reader-title">${esc(rd.item?.title ?? "")}</div>
        </div>
        <div class="reader-body">
          ${rd.blocks.map(blockHtml).join("") || `<div class="empty-hint">还没有解析内容。</div>`}
        </div>
      </div>
      <aside class="reader-side">
        <div class="side-tabs">
          <button class="vt-btn on" data-tab="qa">问答</button>
          <button class="vt-btn" data-tab="notes">批注 ${rd.annotations.length ? `(${rd.annotations.length})` : ""}</button>
        </div>
        <div class="side-panel" data-panel="qa">
          <div class="qa-msgs">
            ${conv.map((m) => {
              if (m.role === "user") return `<div class="msg msg-user"><div class="msg-user-bubble">${esc(m.content.replace(/^【.*?】/, ""))}</div></div>`;
              return `<div class="msg msg-ai"><div class="msg-ai-body qa-answer">${esc(m.content)}</div>${renderCitations(m)}</div>`;
            }).join("") || `<div class="chat-empty"><div class="chat-empty-sub">针对本篇提问，回答带段落出处，点出处跳回原文。</div></div>`}
          </div>
          <div class="qa-composer">
            <input class="text-input qa-input" placeholder="问这篇论文…">
            <button class="composer-send qa-send" title="提问">${LC.IC.arrow}</button>
          </div>
        </div>
        <div class="side-panel" data-panel="notes" hidden>
          <div class="notes-list">
            ${rd.annotations.map((a) => `
            <div class="note-card" data-note="${a.id}">
              <div class="note-quote">段落 ${a.anchor_block + 1}：${esc(a.anchor_quote)}</div>
              <div class="note-body">${esc(a.body)}</div>
              <div class="msg-actions">
                <button class="msg-act" data-goto="${a.anchor_block}">定位原文</button>
                <button class="msg-act" data-note-del="${a.id}">删除</button>
              </div>
            </div>`).join("") || `<div class="chat-empty"><div class="chat-empty-sub">点正文段落旁的批注图标，把想法钉在原文上。</div></div>`}
          </div>
        </div>
      </aside>
      ${rd.anchor != null ? `
      <div class="anno-pop">
        <div class="anno-pop-head">批注 · 段落 ${rd.anchor + 1}</div>
        <textarea class="text-input anno-input" rows="3" placeholder="写批注，支持 [[双链]]"></textarea>
        <div class="draft-actions">
          <button class="btn btn-ghost" data-anno-cancel>取消</button>
          <button class="btn btn-primary" data-anno-save>保存批注</button>
        </div>
      </div>` : ""}
    </div>`;
  }

  function renderCitations(m) {
    // 出处块：kind=paper_qa 的回答，details 不持久化；用回答里的〔N〕渲染可点引用
    const ids = [...new Set([...m.content.matchAll(/〔(\d+)〕/g)].map((x) => Number(x[1])))];
    if (!ids.length) return "";
    return `<div class="citations">${ids.map((n) => `<button class="cite-chip" data-goto="${n}">段落 ${n + 1}</button>`).join("")}</div>`;
  }

  function flash(blockIdx) {
    const el2 = document.querySelector(`[data-anchor="${blockIdx}"]`);
    if (!el2) return;
    el2.scrollIntoView({ behavior: "smooth", block: "center" });
    el2.classList.remove("flash");
    requestAnimationFrame(() => el2.classList.add("flash"));
  }

  async function loadReader() {
    const data = await api(`/api/papers/items/${rd.itemId}/reader`);
    rd.item = data.item; rd.item.title = data.paper.title;
    rd.blocks = data.blocks; rd.annotations = data.annotations;
    const conv = await api("/api/papers/conversation").catch(() => null);
    if (conv) {
      const msgs = await api(`/api/chat/conversations/${conv.conversation.id}/messages`);
      // 只显示本篇相关的问答（用户消息带【标题】前缀）
      const related = msgs.messages.filter((m) => m.content.includes(rd.item?.title?.slice(0, 12) ?? "【") || m.kind === "paper_qa");
      rd.qa = related;
    }
  }

  async function mountReader(container) {
    rd.itemId = (location.hash.match(/#\/papers\/(\d+)/) || [])[1];
    container.innerHTML = `<div class="empty-hint">加载中…</div>`;
    try { await loadReader(); } catch (e) { container.innerHTML = `<div class="empty-hint">加载失败：${esc(e.message)}</div>`; return; }
    container.innerHTML = readerHtml();

    container.addEventListener("click", async (e) => {
      const dot = e.target.closest("[data-anchor-block]");
      if (dot) { rd.anchor = Number(dot.dataset.anchorBlock); container.innerHTML = readerHtml(); container.querySelector(".anno-input")?.focus(); return; }
      if (e.target.closest("[data-anno-cancel]")) { rd.anchor = null; container.innerHTML = readerHtml(); return; }
      if (e.target.closest("[data-anno-save]")) {
        const body = container.querySelector(".anno-input").value.trim();
        if (!body) return;
        await api(`/api/papers/items/${rd.itemId}/annotations`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ anchor_block: rd.anchor, body }),
        });
        rd.anchor = null;
        await loadReader(); container.innerHTML = readerHtml();
        return;
      }
      const goto = e.target.closest("[data-goto]");
      if (goto) { flash(Number(goto.dataset.goto)); return; }
      const noteDel = e.target.closest("[data-note-del]");
      if (noteDel) {
        await api(`/api/papers/annotations/${noteDel.dataset.noteDel}`, { method: "DELETE" });
        await loadReader(); container.innerHTML = readerHtml(); return;
      }
      const tab = e.target.closest("[data-tab]");
      if (tab) {
        container.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b === tab));
        container.querySelectorAll("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== tab.dataset.tab));
        return;
      }
      if (e.target.closest(".qa-send")) return ask(container);
    });
    container.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.closest(".qa-input")) ask(container); });

    // 解析中自动轮询
    if (!["done", "failed"].includes(rd.item.phase)) {
      rd.poll = setInterval(async () => {
        try {
          await loadReader();
          container.innerHTML = readerHtml();
          if (["done", "failed"].includes(rd.item.phase)) clearInterval(rd.poll);
        } catch { /* ignore */ }
      }, 4000);
    }
  }

  async function ask(container) {
    const input = container.querySelector(".qa-input");
    const q = input.value.trim();
    if (!q || rd.busy) return;
    rd.busy = true;
    input.value = "";
    try {
      await api(`/api/papers/items/${rd.itemId}/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, req_id: crypto.randomUUID() }),
      });
      await loadReader();
      container.innerHTML = readerHtml();
      const box = container.querySelector(".qa-msgs");
      if (box) box.scrollTop = box.scrollHeight;
    } finally { rd.busy = false; }
  }

  function cleanupReader() { clearInterval(rd.poll); rd.anchor = null; }

  window.LC.views = Object.assign(window.LC.views || {}, {
    papers: { mount: mountLibrary, cleanup: cleanupLibrary },
    reader: { mount: mountReader, cleanup: cleanupReader },
  });
})();
