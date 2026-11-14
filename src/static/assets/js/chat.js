// 流光咖啡馆 · 对话页（第 1 批）
// 参考 DeepSeek 网页版：左侧会话栏（搜索/新建/重命名/删除）+ 顶部模型选择 +
// 中央消息流（Markdown + 代码高亮）+ 底部两段式输入框（Enter 发送 / Shift+Enter 换行）
// 白皮书 §08：保存确认后再生成；请求标识幂等；三态失败全手动重试；草稿按账号+会话存本机
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;

  const { api, openModal, esc } = LC;

  const md = new LCVendor.MarkdownIt({ html: false, linkify: true, breaks: true });
  const hljs = LCVendor.hljs;

  const ownerKey = () => JSON.stringify(LC.getState().principal ?? {});
  const draftKey = (convId) => `lc_draft_${ownerKey()}_${convId}`;
  const readDraft = (convId) => {
    try { return JSON.parse(localStorage.getItem(draftKey(convId)) || "null"); } catch { return null; }
  };
  const writeDraft = (convId, data) => localStorage.setItem(draftKey(convId), JSON.stringify(data));
  const clearDraft = (convId) => localStorage.removeItem(draftKey(convId));

  const S = {
    conversations: [],
    models: [],
    defaultModel: null,
    realLlm: true,
    hubId: null,       // 总对话 id（恒 agent）
    currentId: null,   // 当前会话 id；null = 未选中
    current: null,     // 当前会话对象（含 mode/app；hub 为合成对象）
    messages: [],
    generating: false,
    abort: null,
    sidebarOpen: false,  // 移动端抽屉
  };

  let el = null; // 视图容器

  /* ---------- 渲染 ---------- */
  function renderMessages() {
    const box = el.querySelector(".chat-msgs");
    if (!box) return;
    if (!S.current) {
      box.innerHTML = `<div class="chat-empty">
        <div class="chat-empty-logo">开始一段新对话</div>
        <div class="chat-empty-sub">输入框在下方，Enter 发送，Shift+Enter 换行</div>
      </div>`;
      return;
    }
    const rows = S.messages.map((m, i) => {
      if (m.role === "user") {
        return `<div class="msg msg-user"><div class="msg-user-bubble">${esc(m.content)}</div></div>`;
      }
      const isLastAssistant = m.role === "assistant" && i === S.messages.map((x) => x.role).lastIndexOf("assistant");
      // agent 消息：结构化内容（回答 + 工具轨迹）渲染为持久工具卡片
      if (m.kind === "agent" && m.id !== "pending") {
        let parsed = null;
        try { parsed = JSON.parse(m.content); } catch { /* 旧格式 */ }
        if (parsed) {
          const traceHtml = (parsed.trace ?? []).map((x) => `
            <div class="tool-card">
              <span class="tool-name">${esc(x.name ?? "?")}</span>
              <span class="tool-args">${esc(JSON.stringify(x.args ?? {})).slice(0, 140)}</span>
              <span class="tool-status">${x.result === undefined ? "执行中…" : x.result.startsWith("失败") ? "失败" : "完成"}</span>
            </div>`).join("");
          return `<div class="msg msg-ai" data-msg="${m.id}">
            <div class="tool-trace">${traceHtml}</div>
            <div class="msg-ai-body" data-render="${m.id}">${renderMd(parsed.answer ?? "")}</div>
          </div>`;
        }
      }
      const statusTag = m.status === "stopped" ? `<span class="msg-status">已停止</span>`
        : m.status === "failed" ? `<span class="msg-status msg-status-fail">生成失败</span>` : "";
      const actions = `<div class="msg-actions">
        <button class="msg-act" data-copy="${m.id}">复制</button>
        ${m.status === "failed" ? `<button class="msg-act" data-retry="${m.id}">重试</button>` : ""}
        ${isLastAssistant && m.status === "ok" && !S.generating ? `<button class="msg-act" data-regen="${m.id}">重新生成</button>` : ""}
      </div>`;
      return `<div class="msg msg-ai" data-msg="${m.id}">
        <div class="msg-ai-body" data-render="${m.id}">${renderMd(m.content)}</div>
        ${statusTag}${actions}
      </div>`;
    }).join("");
    box.innerHTML = rows || `<div class="chat-empty"><div class="chat-empty-sub">这个会话还没有消息。</div></div>`;
    box.scrollTop = box.scrollHeight;
  }

  function renderMd(text) {
    if (!text) return `<span class="msg-thinking">正在输入…</span>`;
    return md.render(text);
  }

  function highlightAll() {
    el.querySelectorAll("pre code").forEach((block) => {
      try { hljs.highlightElement(block); } catch { /* 未知语言跳过 */ }
    });
  }

  function renderSidebar() {
    const list = el.querySelector(".chat-list");
    if (!list) return;
    const hubActive = S.current?.app === "hub";
    list.innerHTML = `
      <div class="conv-item hub-item ${hubActive ? "active" : ""}" data-hub="1">
        <span class="conv-title">总对话 · 跨应用查询</span>
        <span class="tag soon">agent</span>
      </div>
      <div class="conv-sep"></div>
      ${S.conversations.map((c) => `
      <div class="conv-item ${c.id === S.currentId && !hubActive ? "active" : ""}" data-conv="${c.id}">
        <span class="conv-title">${esc(c.title)}</span>
        ${c.mode === "agent" ? '<span class="tag soon">agent</span>' : ""}
        <span class="conv-ops">
          <button class="conv-op" data-rename="${c.id}" title="重命名">${LC.IC.sliders}</button>
          <button class="conv-op" data-del="${c.id}" title="删除">${LC.IC.close}</button>
        </span>
      </div>`).join("") || `<div class="conv-none">还没有会话</div>`}`;
  }

  function renderHeader() {
    const sel = el.querySelector(".model-select");
    if (sel) {
      sel.innerHTML = S.models.map((m) =>
        `<option value="${esc(m.id)}" ${m.id === currentModel() ? "selected" : ""}>${esc(m.name)}</option>`).join("");
      sel.disabled = S.generating;
    }
    const conv = S.current;
    const titleEl = el.querySelector(".chat-title");
    if (titleEl) titleEl.textContent = conv?.app === "hub" ? "总对话（只读工具，跨应用查询）" : (conv?.title ?? "");
    const banner = el.querySelector(".chat-banner");
    if (banner) banner.hidden = S.realLlm;
    // agent 开关（总对话恒 agent，不显示开关）
    const toggle = el.querySelector(".agent-toggle");
    if (toggle) {
      const isHub = conv?.app === "hub";
      toggle.style.display = isHub ? "none" : "";
      toggle.querySelectorAll(".vt-btn").forEach((b) =>
        b.classList.toggle("on", (conv?.mode ?? "chat") === b.dataset.mode));
    }
  }

  const currentModel = () =>
    (S.conversations.find((c) => c.id === S.currentId)?.model) || S.defaultModel || "";

  function renderComposer() {
    const ta = el.querySelector(".composer-input");
    if (!ta) return;
    ta.disabled = S.generating;
    const btn = el.querySelector(".composer-send");
    btn.classList.toggle("stop", S.generating);
    btn.innerHTML = S.generating ? `<span class="stop-square"></span>` : LC.IC.arrow;
    // 草稿恢复（白皮书：切换/刷新后回填）
    const draft = S.currentId ? readDraft(S.currentId) : null;
    if (document.activeElement !== ta) ta.value = draft?.text ?? "";
  }

  function renderAll() {
    renderSidebar();
    renderHeader();
    renderMessages();
    renderComposer();
    highlightAll();
    el.querySelector(".chat-sidebar").classList.toggle("open", S.sidebarOpen);
  }

  /* ---------- 数据 ---------- */
  async function loadConversations(selectId = null) {
    const data = await api("/api/chat/conversations");
    S.conversations = data.conversations;
    const hub = await api("/api/chat/hub").catch(() => null);
    S.hubId = hub?.conversation?.id ?? null;
    if (selectId) {
      S.currentId = selectId;
      S.current = S.conversations.find((c) => c.id === selectId) ?? null;
    } else if (S.current?.app === "hub") {
      // 保持总对话选中
    } else if (S.currentId && !S.conversations.some((c) => c.id === S.currentId)) {
      S.currentId = null;
      S.current = null;
    }
    renderSidebar();
    renderHeader();
  }

  function openHub() {
    S.currentId = null;
    S.current = { id: S.hubId, app: "hub", mode: "agent", title: "总对话" };
    S.sidebarOpen = false;
    location.hash = "#/chat";
    api(`/api/chat/conversations/${S.hubId}/messages`)
      .then((d) => { S.messages = d.messages; renderAll(); })
      .catch(() => { S.messages = []; renderAll(); });
  }

  async function loadMessages(convId) {
    const data = await api(`/api/chat/conversations/${convId}/messages`);
    S.messages = data.messages;
    S.current = S.conversations.find((c) => c.id === convId) ?? S.current;
    renderMessages();
    highlightAll();
    renderComposer(); // 恢复本机会话草稿
  }

  async function ensureDefaults() {
    const data = await api("/api/chat/models");
    S.models = data.models;
    S.defaultModel = data.default_model;
    S.realLlm = data.real;
  }

  /* ---------- 发送与生成（白皮书时序图） ---------- */
  async function send() {
    const ta = el.querySelector(".composer-input");
    const text = ta.value.trim();
    if (!text || S.generating) return;
    if (!S.current) {
      const { conversation } = await (await fetch("/api/chat/conversations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      })).json();
      S.currentId = conversation.id;
      S.current = conversation;
      location.hash = `#/chat/${conversation.id}`;
      await loadConversations(S.currentId);
    }
    const convId = S.current.id;
    // 草稿记录发送中的文本与请求标识（重试沿用，原文不变不换标识）
    let draft = readDraft(convId) || {};
    if (draft.text !== text || !draft.reqId) draft = { text, reqId: crypto.randomUUID() };
    writeDraft(convId, draft);

    let saved;
    try {
      saved = await api("/api/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: convId, content: text, req_id: draft.reqId }),
      });
    } catch {
      // 情况 1：用户消息未保存——原文留在输入框，提示手动重试
      toast("发送失败，请检查网络后重点发送");
      return;
    }
    clearDraft(convId);
    ta.value = "";
    draft = null;
    await loadConversations(); // 标题可能自动生成
    S.messages.push(saved.message);
    renderMessages();
    if (S.current?.mode === "agent" || S.current?.app === "hub") await agentSend(text);
    else await generate();
  }

  /* ---------- agent 模式（pi 接管：文本增量 + 工具卡片，SSE） ---------- */
  async function agentSend(userText) {
    if (!S.current?.id || S.generating) return;
    S.generating = true;
    S.abort = new AbortController();
    renderHeader();
    renderComposer();

    const placeholder = { id: "pending", role: "assistant", content: "", status: "ok", kind: "agent" };
    S.messages.push(placeholder);
    renderMessages();
    const msgEl = el.querySelector('[data-msg="pending"]');
    let traceBox = null;
    const answerEl = msgEl?.querySelector('[data-render="pending"]');
    let answerText = "";
    const flush = throttle(() => {
      if (answerEl) answerEl.innerHTML = renderMd(answerText) || '<span class="msg-thinking">正在输入…</span>';
      const box = el.querySelector(".chat-msgs");
      if (box) box.scrollTop = box.scrollHeight;
    }, 80);
    const addToolCard = (name, args) => {
      if (!msgEl) return null;
      if (!traceBox) {
        traceBox = document.createElement("div");
        traceBox.className = "tool-trace";
        msgEl.insertBefore(traceBox, answerEl ?? null);
      }
      const card = document.createElement("div");
      card.className = "tool-card";
      card.innerHTML = `<span class="tool-name">${esc(name)}</span><span class="tool-args">${esc(JSON.stringify(args ?? {})).slice(0, 140)}</span><span class="tool-status">执行中…</span>`;
      traceBox.appendChild(card);
      return card;
    };

    let failed = false;
    try {
      const res = await fetch("/api/chat/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: S.current.id, content: userText, req_id: crypto.randomUUID() }),
        signal: S.abort.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let lastCard = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const evt = JSON.parse(line.slice(6));
            if (evt.delta) { answerText += evt.delta; flush(); }
            else if (evt.tool) lastCard = addToolCard(evt.tool, evt.args);
            else if (evt.tool_end && lastCard) lastCard.querySelector(".tool-status").textContent = evt.ok ? "完成" : "失败";
            else if (evt.error) { failed = true; }
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") failed = true;
    }
    finishGen();
    await loadMessages(S.current.id);
    await loadConversations();
  }

  async function generate(opts = {}) {
    if (!S.currentId || S.generating) return;
    S.generating = true;
    S.abort = new AbortController();
    renderHeader();
    renderComposer();

    // 占位气泡（流式逐字显示）
    const placeholder = { id: "pending", role: "assistant", content: "", status: "ok" };
    S.messages.push(placeholder);
    renderMessages();
    const bodyEl = el.querySelector('[data-render="pending"]');

    let full = "";
    let failed = false;
    const flush = throttle(() => {
      if (bodyEl) bodyEl.innerHTML = renderMd(full);
      const box = el.querySelector(".chat-msgs");
      if (box) box.scrollTop = box.scrollHeight;
    }, 80);

    try {
      const res = await fetch("/api/chat/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: S.currentId,
          ...(opts.regenerate ? { regenerate: 1 } : {}),
          ...(opts.retryMessageId ? { retry_message_id: opts.retryMessageId } : {}),
        }),
        signal: S.abort.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            const evt = JSON.parse(line.slice(6));
            if (evt.delta) { full += evt.delta; flush(); }
            else if (evt.error) { failed = true; }
          }
        }
      }
    } catch (err) {
      if (err.name === "AbortError") {
        // 主动停止：保留已显示内容，由服务端标记“已停止”
        S.messages = S.messages.filter((m) => m.id !== "pending");
        await loadMessages(S.currentId);
        finishGen();
        return;
      }
      failed = true;
    }

    finishGen();
    // 以服务端入库为准刷新（半成品/失败/停止都已落库标记）
    await loadMessages(S.currentId);
    await loadConversations();
    const last = S.messages[S.messages.length - 1];
    if (failed && last?.role === "assistant") {
      // 情况 2/3：回答区显示“生成失败 + 重试”（按钮在 renderMessages 里按 status 渲染）
    }
  }

  function finishGen() {
    S.generating = false;
    S.abort = null;
    renderHeader();
    renderComposer();
  }

  function throttle(fn, ms) {
    let timer = null;
    return () => {
      if (timer) return;
      timer = setTimeout(() => { timer = null; fn(); }, ms);
    };
  }

  let toastTimer = null;
  function toast(text) {
    let t = el.querySelector(".chat-toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "chat-toast";
      el.appendChild(t);
    }
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
  }

  /* ---------- 事件 ---------- */
  function bind() {
    el.addEventListener("click", async (e) => {
      const modeBtn = e.target.closest(".agent-toggle [data-mode]");
      if (modeBtn && S.current && S.current.app !== "hub") {
        const mode = modeBtn.dataset.mode;
        await api(`/api/chat/conversations/${S.current.id}/mode`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
        S.current.mode = mode;
        renderHeader();
        toast(mode === "agent" ? "已切 agent 模式：pi 接管，可调用只读工具" : "已切普通模式：单次调用");
        return;
      }
      const convEl = e.target.closest("[data-conv]");
      const newBtn = e.target.closest("[data-new]");
      const sendBtn = e.target.closest(".composer-send");
      const stopGen = S.generating && sendBtn;
      const menuBtn = e.target.closest("[data-menu]");
      const backdrop = e.target.classList.contains("chat-backdrop");

      if (stopGen) { S.abort?.abort(); return; }
      if (sendBtn) { await send(); return; }
      if (e.target.closest("[data-hub]")) { openHub(); return; }
      if (newBtn) {
        const res = await fetch("/api/chat/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const { conversation } = await res.json();
        S.currentId = conversation.id;
        S.current = conversation;
        S.messages = [];
        location.hash = `#/chat/${conversation.id}`;
        S.sidebarOpen = false;
        await loadConversations(S.currentId);
        renderAll();
        el.querySelector(".composer-input")?.focus();
        return;
      }
      if (menuBtn || backdrop) {
        S.sidebarOpen = backdrop ? false : !S.sidebarOpen;
        renderAll();
        return;
      }
      if (!convEl) {
        const rename = e.target.closest("[data-rename]");
        const del = e.target.closest("[data-del]");
        const copy = e.target.closest("[data-copy]");
        const retry = e.target.closest("[data-retry]");
        const regen = e.target.closest("[data-regen]");
        if (rename) return renameConv(rename.dataset.rename);
        if (del) return deleteConv(del.dataset.del);
        if (copy) {
          const m = S.messages.find((x) => x.id === copy.dataset.copy);
          if (m) { await navigator.clipboard.writeText(m.content).catch(() => {}); toast("已复制"); }
          return;
        }
        if (retry) return generate({ retryMessageId: retry.dataset.retry });
        if (regen) return generate({ regenerate: true });
        return;
      }
      const id = convEl.dataset.conv;
      if (id !== S.currentId) {
        S.currentId = id;
        S.current = S.conversations.find((c) => c.id === id) ?? null;
        S.sidebarOpen = false;
        location.hash = `#/chat/${id}`;
        await loadMessages(id);
        renderAll();
      }
    });

    el.addEventListener("change", async (e) => {
      const sel = e.target.closest(".model-select");
      if (!sel || !S.currentId) return;
      await api(`/api/chat/conversations/${S.currentId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: sel.value }),
      });
      const c = S.conversations.find((x) => x.id === S.currentId);
      if (c) c.model = sel.value;
      toast("已切换模型，只影响之后的回答");
    });

    el.addEventListener("input", (e) => {
      const ta = e.target.closest(".composer-input");
      if (ta) {
        if (!ta.value.trim() || !S.currentId) return;
        // 输入即存草稿（换会话/刷新后恢复）
        const prev = readDraft(S.currentId) || {};
        writeDraft(S.currentId, { ...prev, text: ta.value });
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
        return;
      }
      const search = e.target.closest(".conv-search");
      if (search) {
        const q = search.value.trim();
        const list = el.querySelector(".chat-list");
        list.innerHTML = S.conversations
          .filter((c) => !q || c.title.includes(q))
          .map((c) => `
            <div class="conv-item ${c.id === S.currentId ? "active" : ""}" data-conv="${c.id}">
              <span class="conv-title">${esc(c.title)}</span>
              <span class="conv-ops">
                <button class="conv-op" data-rename="${c.id}" title="重命名">${LC.IC.sliders}</button>
                <button class="conv-op" data-del="${c.id}" title="删除">${LC.IC.close}</button>
              </span>
            </div>`).join("") || `<div class="conv-none">没有匹配的会话</div>`;
      }
    });

    el.addEventListener("keydown", (e) => {
      const ta = e.target.closest(".composer-input");
      if (!ta) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    });
  }

  async function renameConv(id) {
    const c = S.conversations.find((x) => x.id === id);
    openModal("重命名会话", `
      <input class="text-input" id="rename-input" value="${esc(c?.title ?? "")}" maxlength="60">
    `, `<button class="btn btn-ghost" data-close>取消</button>
        <button class="btn btn-primary" id="rename-ok">保存</button>`);
    document.getElementById("rename-ok")?.addEventListener("click", async () => {
      const title = document.getElementById("rename-input")?.value?.trim();
      if (title) {
        await api(`/api/chat/conversations/${id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        LC.closeModal();
        await loadConversations(S.currentId);
        renderAll();
      }
    });
  }

  function deleteConv(id) {
    openModal("删除会话", `
      <p>会话和它的全部消息会被永久删除，<b>不可恢复</b>。本机草稿会一并清除。</p>
    `, `<button class="btn btn-ghost" data-close>取消</button>
        <button class="btn btn-danger" id="del-ok">永久删除</button>`);
    document.getElementById("del-ok")?.addEventListener("click", async () => {
      await api(`/api/chat/conversations/${id}`, { method: "DELETE" });
      clearDraft(id);
      LC.closeModal();
      if (S.currentId === id) {
        S.currentId = null;
        S.messages = [];
        location.hash = "#/chat";
      }
      await loadConversations(S.currentId);
      renderAll();
    });
  }

  /* ---------- 视图结构 ---------- */
  function mount(container) {
    el = container;
    el.innerHTML = `
      <div class="chat-wrap">
        <div class="chat-backdrop ${S.sidebarOpen ? "show" : ""}"></div>
        <aside class="chat-sidebar ${S.sidebarOpen ? "open" : ""}">
          <div class="chat-side-head">
            <button class="btn btn-primary btn-new" data-new>${LC.IC.chat} 新会话</button>
            <input class="text-input conv-search" placeholder="搜索会话标题">
          </div>
          <div class="chat-list"></div>
        </aside>
        <section class="chat-main">
          <div class="chat-head">
            <button class="icon-btn chat-menu" data-menu title="会话列表">${LC.IC.grid}</button>
            <span class="chat-title"></span>
            <div class="agent-toggle view-toggle" title="普通 = 单次调用；agent = pi 接管、自主多步、只读工具">
              <button class="vt-btn on" data-mode="chat">单次</button>
              <button class="vt-btn" data-mode="agent">Agent</button>
            </div>
            <select class="model-select" title="模型选择（按会话生效）"></select>
          </div>
          <div class="chat-banner" hidden>未配置 DEEPSEEK_API_KEY，当前为本地假模型——全链路可跑，回答不真实。</div>
          <div class="chat-msgs"></div>
          <div class="chat-composer">
            <textarea class="composer-input" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行"></textarea>
            <div class="composer-bar">
              <span class="composer-hint"></span>
              <button class="composer-send" title="发送 / 停止">${LC.IC.arrow}</button>
            </div>
          </div>
        </section>
      </div>`;
    bind();

    (async () => {
      try {
        await ensureDefaults();
        const wanted = (location.hash.match(/#\/chat\/([\w-]+)/) || [])[1] ?? null;
        await loadConversations(wanted);
        if (S.currentId) await loadMessages(S.currentId);
        renderAll();
        // 草稿恢复（含无会话时的新建会话草稿不需要）
        renderComposer();
      } catch (err) {
        el.innerHTML = `<div class="empty-hint">对话加载失败：${esc(err.message)}</div>`;
      }
    })();
  }

  function cleanup() {
    S.abort?.abort();
    el = null;
  }

  window.LC.views = Object.assign(window.LC.views || {}, { chat: { mount, cleanup } });
})();
