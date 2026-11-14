// 流光咖啡馆 · 记账页（第 2 批）
// 参考钱迹主界面：顶部月收支汇总带 + 按日期分组流水；月度报表 = 分类汇总条 + 近6月趋势
// 收入红、支出绿（中文惯例）；金额展示用元，存库用分
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;
  const { api, openModal, esc } = LC;

  const S = {
    month: new Date().toISOString().slice(0, 7),
    view: "personal",
    data: null,          // 当月账目 + 汇总 + 趋势
    categories: [],
    convId: null,
    messages: [],
    busy: false,
  };

  let el = null;

  const yuan = (fen) => (fen / 100).toFixed(2);
  const fmtDate = (s) => (s ?? "").slice(5, 10);

  /* ---------- 数据 ---------- */
  async function loadAll() {
    const [entries, cats, conv] = await Promise.all([
      api(`/api/money/entries?month=${S.month}&view=${S.view}`),
      api("/api/money/categories"),
      api("/api/money/conversation"),
    ]);
    S.data = entries;
    S.categories = cats.categories;
    S.convId = conv.conversation.id;
    const msgs = await api(`/api/chat/conversations/${S.convId}/messages`);
    S.messages = msgs.messages;
  }

  /* ---------- 渲染 ---------- */
  function render() {
    // 重渲染前保住输入框正在输入的内容（渲染是 innerHTML 整体重写，不保住会丢掉）
    const keepInput = el.querySelector(".money-input")?.value ?? null;
    const d = S.data;
    const income = d.summary.income?.total ?? 0;
    const expense = d.summary.expense?.total ?? 0;
    const byDate = {};
    for (const t of d.entries) (byDate[t.occurred_on] ??= []).push(t);

    el.querySelector(".money-body").innerHTML = `
      <div class="money-head-row">
        <div class="month-nav">
          <button class="icon-btn" data-month="-1">‹</button>
          <span class="month-label">${S.month.replace("-", " 年 ")} 月</span>
          <button class="icon-btn" data-month="1">›</button>
        </div>
        <div class="view-toggle">
          <button class="vt-btn ${S.view === "personal" ? "on" : ""}" data-view="personal">个人</button>
          <button class="vt-btn ${S.view === "family" ? "on" : ""}" data-view="family">家庭</button>
        </div>
        <div class="money-actions">
          <button class="btn btn-ghost" data-cats>分类管理</button>
          <button class="btn btn-primary" data-add>记一笔</button>
        </div>
      </div>

      <div class="money-cards">
        <div class="mcard"><div class="mcard-k">收入</div><div class="mcard-v income">+¥${yuan(income)}</div></div>
        <div class="mcard"><div class="mcard-k">支出</div><div class="mcard-v expense">-¥${yuan(expense)}</div></div>
        <div class="mcard"><div class="mcard-k">结余</div><div class="mcard-v">${income - expense < 0 ? "-" : ""}¥${yuan(Math.abs(income - expense))}</div></div>
      </div>

      <div class="money-charts">
        <div class="chart-box">
          <div class="chart-title">分类汇总（支出）</div>
          ${d.by_category.filter((c) => c.kind === "expense").slice(0, 8).map((c) => {
            const max = Math.max(...d.by_category.map((x) => x.total), 1);
            return `<div class="bar-row"><span class="bar-name">${esc(c.name)}</span>
              <span class="bar-track"><span class="bar-fill expense" data-w="${Math.round((c.total / max) * 100)}"></span></span>
              <span class="bar-val">¥${yuan(c.total)}</span></div>`;
          }).join("") || `<div class="chart-none">本月还没有支出</div>`}
        </div>
        <div class="chart-box">
          <div class="chart-title">近 6 月趋势</div>
          ${(() => {
            const max = Math.max(...d.trend.map((t) => Math.max(t.expense, t.income)), 1);
            return `<div class="trend">${d.trend.map((t) => `
              <div class="trend-col" title="${t.month}：支 ¥${yuan(t.expense)} / 收 ¥${yuan(t.income)}">
                <span class="trend-bar income" data-hi="${Math.round((t.income / max) * 100)}"></span>
                <span class="trend-bar expense" data-he="${Math.round((t.expense / max) * 100)}"></span>
                <span class="trend-m">${t.month.slice(5)}月</span>
              </div>`).join("")}</div>`;
          })()}
        </div>
      </div>

      <div class="entry-list">
        ${Object.keys(byDate).sort().reverse().map((date) => {
          const rows = byDate[date];
          const dayTotal = rows.filter((t) => t.type === "expense").reduce((a, t) => a + t.amount_fen, 0);
          return `<div class="entry-date-row">
            <span>${fmtDate(date)}</span><span class="entry-day-total">-¥${yuan(dayTotal)}</span>
          </div>
          ${rows.map((t) => `
          <div class="entry-row" data-entry="${t.id}">
            <span class="entry-cat">${esc(t.category_name)}${t.shared ? `<span class="tag soon tag-family">家庭</span>` : ""}</span>
            <span class="entry-note">${esc(t.note || "")}</span>
            <span class="entry-amt ${t.type}">${t.type === "income" ? "+" : "-"}¥${yuan(t.amount_fen)}</span>
            <span class="entry-ops">
              <button class="conv-op" data-edit="${t.id}">${LC.IC.sliders}</button>
              <button class="conv-op" data-del-entry="${t.id}">${LC.IC.close}</button>
            </span>
          </div>`).join("")}`;
        }).join("") || `<div class="empty-hint">这个月还没有账目，点「记一笔」或用下方对话记。</div>`}
      </div>

      <div class="money-chat">
        <div class="money-chat-head">AI 记账对话</div>
        <div class="money-chat-msgs">${renderMessages()}</div>
        <div class="money-chat-composer">
          <input class="text-input money-input" placeholder="说「午饭 32 元」记一笔，或问「这个月吃饭花了多少」">
          <button class="composer-send money-send" title="发送">${LC.IC.arrow}</button>
        </div>
      </div>`;
    // CSP 禁内联样式：条形宽度/高度用 data 属性 + JS 逐属性设置（逐属性赋值不受 style-src 拦）
    el.querySelectorAll("[data-w]").forEach((n) => (n.style.width = n.dataset.w + "%"));
    el.querySelectorAll("[data-hi]").forEach((n) => (n.style.height = n.dataset.hi + "%"));
    el.querySelectorAll("[data-he]").forEach((n) => (n.style.height = n.dataset.he + "%"));
    const box = el.querySelector(".money-chat-msgs");
    if (box) box.scrollTop = box.scrollHeight;
    if (keepInput != null) {
      const input = el.querySelector(".money-input");
      if (input) input.value = keepInput;
    }
  }

  function renderMessages() {
    return S.messages.map((m) => {
      if (m.role === "user") {
        return `<div class="msg msg-user"><div class="msg-user-bubble">${esc(m.content)}</div></div>`;
      }
      if (m.kind === "draft") {
        let d = null;
        try { d = JSON.parse(m.content); } catch { /* 旧数据 */ }
        if (!d) return `<div class="msg msg-ai"><div class="msg-ai-body">${esc(m.content)}</div></div>`;
        const confirmed = S.data?.entries.some((t) => t.request_id === d.request_id);
        return `<div class="msg msg-ai">
          <div class="draft-card" data-draft="${esc(m.id)}" data-req="${esc(d.request_id)}">
            <div class="draft-title">记账草稿（确认后才入账）</div>
            <div class="draft-grid">
              <label>金额（元）</label><input class="text-input d-amount" type="number" min="0.01" step="0.01" value="${(d.amount_fen / 100).toFixed(2)}" ${confirmed ? "disabled" : ""}>
              <label>分类</label><select class="text-input d-cat" ${confirmed ? "disabled" : ""}>
                ${S.categories.filter((c) => c.kind === d.type).map((c) => `<option value="${c.id}" ${c.id === d.category_id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
              </select>
              <label>日期</label><input class="text-input d-date" type="date" value="${d.occurred_on}" ${confirmed ? "disabled" : ""}>
              <label>备注</label><input class="text-input d-note" value="${esc(d.note ?? "")}" maxlength="100" ${confirmed ? "disabled" : ""}>
            </div>
            <label class="d-shared-row"><input type="checkbox" class="d-shared" ${d.shared ? "checked" : ""} ${confirmed ? "disabled" : ""}> 记入家庭账本（双方可见）</label>
            <div class="draft-actions">
              ${confirmed
                ? `<span class="tag soon">已入账</span>`
                : `<button class="btn btn-ghost" data-draft-cancel>取消</button>
                   <button class="btn btn-primary" data-draft-ok>确认入账</button>`}
            </div>
          </div>
        </div>`;
      }
      return `<div class="msg msg-ai"><div class="msg-ai-body">${esc(m.content)}</div></div>`;
    }).join("") || `<div class="chat-empty"><div class="chat-empty-sub">在这里用白话记账、问账。</div></div>`;
  }

  /* ---------- 表单（记一笔 / 编辑） ---------- */
  function entryForm(entry = null) {
    const isEdit = Boolean(entry);
    const cats = S.categories;
    const val = entry ?? { type: "expense", amount_fen: null, category_id: null, occurred_on: new Date().toISOString().slice(0, 10), note: "", shared: false };
    openModal(isEdit ? "编辑账目" : "记一笔", `
      <div class="draft-grid">
        <label>收支</label>
        <div class="type-toggle">
          <button class="vt-btn ${val.type === "expense" ? "on" : ""}" data-type="expense">支出</button>
          <button class="vt-btn ${val.type === "income" ? "on" : ""}" data-type="income">收入</button>
        </div>
        <label>金额（元）</label><input class="text-input f-amount" type="number" min="0.01" step="0.01" value="${val.amount_fen ? (val.amount_fen / 100).toFixed(2) : ""}" autofocus>
        <label>分类</label><select class="text-input f-cat">
          ${cats.filter((c) => c.kind === val.type && !c.hidden).map((c) => `<option value="${c.id}" ${c.id === val.category_id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}
        </select>
        <label>日期</label><input class="text-input f-date" type="date" value="${val.occurred_on}">
        <label>备注</label><input class="text-input f-note" value="${esc(val.note ?? "")}" maxlength="100" placeholder="可留空">
      </div>
      <label class="d-shared-row"><input type="checkbox" class="f-shared" ${val.shared ? "checked" : ""}> 记入家庭账本（双方可见）</label>
    `, `<button class="btn btn-ghost" data-close>取消</button>
        <button class="btn btn-primary" id="entry-save">${isEdit ? "保存修改" : "入账"}</button>`);

    const modal = document.getElementById("modal");
    modal.querySelectorAll("[data-type]").forEach((b) => b.addEventListener("click", () => {
      modal.querySelectorAll("[data-type]").forEach((x) => x.classList.toggle("on", x === b));
      const type = b.dataset.type;
      modal.querySelector(".f-cat").innerHTML = cats.filter((c) => c.kind === type && !c.hidden)
        .map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    }));
    document.getElementById("entry-save")?.addEventListener("click", async () => {
      const amount = Math.round(parseFloat(modal.querySelector(".f-amount").value) * 100);
      const body = {
        amount_fen: amount,
        type: modal.querySelector('[data-type].on').dataset.type,
        category_id: Number(modal.querySelector(".f-cat").value),
        occurred_on: modal.querySelector(".f-date").value,
        note: modal.querySelector(".f-note").value.trim(),
        shared: modal.querySelector(".f-shared").checked,
      };
      if (!Number.isInteger(amount) || amount <= 0) { LC.closeModal(); return; }
      if (isEdit) {
        await api(`/api/money/entries/${entry.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      } else {
        body.request_id = crypto.randomUUID();
        await api("/api/money/entries", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      }
      LC.closeModal();
      await loadAll();
      render();
    });
  }

  /* ---------- 分类管理 ---------- */
  function catsModal() {
    openModal("分类管理", `
      <div class="cat-list">
        ${["expense", "income"].map((kind) => `
          <div class="cat-kind">${kind === "expense" ? "支出" : "收入"}</div>
          ${S.categories.filter((c) => c.kind === kind).map((c) => `
          <div class="cat-row" data-cat="${c.id}">
            <input class="text-input cat-name" value="${esc(c.name)}" ${c.built_in ? "" : ""}>
            <button class="msg-act" data-cat-hide="${c.id}">${c.hidden ? "显示" : "隐藏"}</button>
            ${c.built_in ? `<span class="tag">预置</span>` : `<button class="msg-act" data-cat-del="${c.id}">删除</button>`}
          </div>`).join("")}`).join("")}
        <div class="cat-add-row">
          <select class="text-input cat-add-kind"><option value="expense">支出</option><option value="income">收入</option></select>
          <input class="text-input cat-add-name" placeholder="新分类名" maxlength="12">
          <button class="btn btn-ghost" data-cat-add>添加</button>
        </div>
      </div>
    `, `<button class="btn btn-primary" data-close>完成</button>`);

    const modal = document.getElementById("modal");
    modal.addEventListener("change", async (e) => {
      const nameInput = e.target.closest(".cat-name");
      if (nameInput) {
        const id = nameInput.closest("[data-cat]").dataset.cat;
        await api(`/api/money/categories/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: nameInput.value.trim() }) });
        await loadAll();
      }
    });
  }

  /* ---------- AI 对话 ---------- */
  async function sendAi() {
    const input = el.querySelector(".money-input");
    const text = input.value.trim();
    if (!text || S.busy) return;
    S.busy = true;
    input.value = "";
    try {
      await api("/api/money/ai", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, req_id: crypto.randomUUID() }),
      });
      await loadAll();
      render();
    } finally {
      S.busy = false;
    }
  }

  /* ---------- 事件 ---------- */
  function bind() {
    el.addEventListener("click", async (e) => {
      const monthBtn = e.target.closest("[data-month]");
      const viewBtn = e.target.closest("[data-view]");
      if (monthBtn) {
        const [y, m] = S.month.split("-").map(Number);
        const d = new Date(y, m - 1 + Number(monthBtn.dataset.month), 1);
        S.month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
        await loadAll(); render(); return;
      }
      if (viewBtn) { S.view = viewBtn.dataset.view; await loadAll(); render(); return; }
      if (e.target.closest("[data-add]")) { entryForm(); return; }
      if (e.target.closest("[data-cats]")) { catsModal(); return; }

      const edit = e.target.closest("[data-edit]");
      const delEntry = e.target.closest("[data-del-entry]");
      if (edit) {
        entryForm(S.data.entries.find((t) => String(t.id) === edit.dataset.edit));
        return;
      }
      if (delEntry) {
        const t = S.data.entries.find((x) => String(x.id) === delEntry.dataset.delEntry);
        openModal("删除账目", `<p>删除这条 ${esc(t.category_name)} ¥${yuan(t.amount_fen)} 的账？</p>`,
          `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" id="del-ok">删除</button>`);
        document.getElementById("del-ok")?.addEventListener("click", async () => {
          await api(`/api/money/entries/${t.id}`, { method: "DELETE" });
          LC.closeModal(); await loadAll(); render();
        });
        return;
      }

      // 草稿卡片按钮（事件委托，卡片在消息里）
      const card = e.target.closest(".draft-card");
      if (card && e.target.closest("[data-draft-ok]")) {
        const amount = Math.round(parseFloat(card.querySelector(".d-amount").value) * 100);
        await api("/api/money/entries", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            amount_fen: amount,
            type: S.categories.find((c) => String(c.id) === card.querySelector(".d-cat").value)?.kind ?? "expense",
            category_id: Number(card.querySelector(".d-cat").value),
            occurred_on: card.querySelector(".d-date").value,
            note: card.querySelector(".d-note").value.trim(),
            shared: card.querySelector(".d-shared").checked,
            request_id: card.dataset.req, // 沿用原请求标识 → 幂等
          }),
        });
        await loadAll(); render(); return;
      }
      if (card && e.target.closest("[data-draft-cancel]")) {
        openModal("取消这笔草稿", "<p>只是不入账，对话记录保留。</p>",
          `<button class="btn btn-ghost" data-close>再想想</button><button class="btn btn-danger" id="dc-ok">取消草稿</button>`);
        document.getElementById("dc-ok")?.addEventListener("click", () => { LC.closeModal(); });
        return;
      }

      if (e.target.closest(".money-send")) { await sendAi(); return; }

      // 分类管理弹窗内的委托（弹窗在 body 下，但事件冒泡不到 el——用 document 级一次）
    });

    el.addEventListener("keydown", async (e) => {
      if (e.key === "Enter" && e.target.closest(".money-input")) { e.preventDefault(); await sendAi(); }
    });

    // 弹窗内按钮（modal 在 #app 外）
    document.addEventListener("click", modalDelegate);
  }

  function modalDelegate(e) {
    const hide = e.target.closest("[data-cat-hide]");
    const del = e.target.closest("[data-cat-del]");
    const add = e.target.closest("[data-cat-add]");
    if (!hide && !del && !add) return;
    (async () => {
      if (hide) await api(`/api/money/categories/${hide.dataset.catHide}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hidden: true }) });
      if (del) await api(`/api/money/categories/${del.dataset.catDel}`, { method: "DELETE" }).catch((err) => alert(err.message));
      if (add) {
        const modal = document.getElementById("modal");
        await api("/api/money/categories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: modal.querySelector(".cat-add-name").value.trim(), kind: modal.querySelector(".cat-add-kind").value }) }).catch(() => {});
      }
      await loadAll();
      render();
      if (add || hide || del) catsModal(); // 重开刷新列表
    })();
  }

  async function mount(container) {
    el = container;
    el.innerHTML = `<div class="money-page"><div class="money-body"></div></div>`;
    bind();
    await loadAll();
    render();
  }

  function cleanup() {
    document.removeEventListener("click", modalDelegate);
    el = null;
  }

  window.LC.views = Object.assign(window.LC.views || {}, { money: { mount, cleanup } });
})();
