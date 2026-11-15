// 流光咖啡馆 · 对话页（2026-11-15 改版：学 WorkBuddy 任务对话，红白灰落地）
// ① AI 消息「模型 · 已完成 Xs」耗时标注（latency_ms 来自后端调用计时）
// ② 右侧提问导航刻度条：每条=一次用户提问，hover 看问题/点击定位，≥7 条显示、窄区隐藏
// ③ 对话内搜索：头部 ⌕ 弹出，命中高亮点击跳转
// ④ 模型选择收进输入区常驻控件行（单档拍板：单次/Agent 合并——全部走 pi 只读工具循环，
//    简单问题模型不调工具≈单次成本；界面不再有模式开关）
// ⑤ 用户消息 hover「编辑重发」；⑥ Markdown 表格/引用块样式（main.css）
// ⑦ 长对话视窗渲染（默认最近 80 条，顶部「加载更早」）
// 保留：懒创建(A1)/搜索统一(A2)/B3 操作条/B4 失败回填/草稿/B7 空态 chips/C8 会话抽屉
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;

  const { api, apiStream, openModal, esc } = LC;

  const md = new LCVendor.MarkdownIt({ html: false, linkify: true, breaks: true });
  const hljs = LCVendor.hljs;

  const ownerKey = () => JSON.stringify(LC.getState().principal ?? {});
  const draftKey = (convId) => `lc_draft_${ownerKey()}_${convId}`;
  /* 草稿键：新会话占位用固定键（创建后迁移到真实 id，A1 配套） */
  const draftId = () => (S.currentId === NEW_ID ? NEW_ID : S.currentId);
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
    current: null,     // 当前会话对象（含 model/app；hub 为合成对象）
    messages: [],
    generating: false,
    abort: null,
    sidebarOpen: false,  // 移动端抽屉（入口在对话头部 chat-menu，白皮书 §20 C8 拍板保留）
    query: "",           // 会话搜索词（过滤与主列表共用同一渲染函数）
    winSize: 80,         // 长对话视窗：默认渲染最近 80 条（性能项）
  };

  /* 新会话占位 id：点击「新会话」不再落库（懒创建，白皮书拍板），
     发送首条消息时才 POST 创建；与 hub 一样是合成对象 */
  const NEW_ID = "__new__";
  const newConvObj = () => ({ id: NEW_ID, title: "新会话", model: null, mode: "chat", app: "chat" });

  /* B7 空态建议问题（内置常量，与 chat 系统提示词同思路；点击填入输入框） */
  const SUGGESTIONS = [
    "帮我总结今天的待办",
    "解释一下什么是向量数据库",
    "写一封简短的会议邀请邮件",
    "这个月记账有什么趋势？",
  ];

  let el = null; // 视图容器

  /* ---------- 渲染 ---------- */
  function modelNameOf(ref) {
    const m = S.models.find((x) => x.id === (ref || currentModel()));
    return m ? m.name : (ref || "默认模型");
  }

  /* 「已完成 · Xs」耗时标注（latency_ms 后端计时入库；无值/未成功则不显示） */
  function metaDone(m) {
    if (m.latency_ms == null || m.status !== "ok") return "";
    return `<span class="m-done">已完成 · ${(m.latency_ms / 1000).toFixed(1)}s</span>`;
  }

  /* B3：操作条 hover 显形图标（学 RAGFlow）；失败重试是恢复动作，常显不藏 */
  function msgActions(m, isLastAssistant) {
    return `<div class="msg-actions">
      <button class="msg-act" data-copy="${m.id}" title="复制" aria-label="复制">${LC.IC.copy}</button>
      ${m.status === "failed" ? `<button class="msg-act msg-act-keep" data-retry="${m.id}" title="重试" aria-label="重试">${LC.IC.refresh}</button>` : ""}
      ${isLastAssistant && m.status === "ok" && !S.generating ? `<button class="msg-act" data-regen="${m.id}" title="重新生成" aria-label="重新生成">${LC.IC.refresh}</button>` : ""}
    </div>`;
  }

  function renderMessages() {
    const box = el.querySelector(".chat-msgs");
    if (!box) return;
    if (!S.current || S.current.id === NEW_ID) {
      // B7：空态即入口——建议问题 chips，点击填入输入框（学 RAGFlow prologue 思路）
      box.innerHTML = `<div class="chat-empty">
        <div class="chat-empty-logo">开始一段新对话</div>
        <div class="chat-empty-sub">输入框在下方，Enter 发送，Shift+Enter 换行</div>
        <div class="chat-suggest">
          ${SUGGESTIONS.map((s) => `<button class="suggest-chip" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}
        </div>
      </div>`;
      renderTicks();
      return;
    }
    const total = S.messages.length;
    const start = Math.max(0, total - S.winSize); // 视窗：只渲染最近 winSize 条
    const rows = [];
    if (start > 0) {
      rows.push(`<div class="msg-more"><button data-more-msgs>加载更早的 ${start} 条消息</button></div>`);
    }
    S.messages.slice(start).forEach((m, i) => {
      const idx = start + i;
      if (m.role === "user") {
        rows.push(`<div class="msg msg-user" data-idx="${idx}"><div class="msg-user-bubble">${esc(m.content)}</div>
          <button class="msg-user-edit" data-edit-user="${idx}" title="编辑重发">✎ 编辑</button></div>`);
        return;
      }
      const slice = S.messages.slice(start);
      const isLastAssistant = m.role === "assistant" && i === slice.map((x) => x.role).lastIndexOf("assistant");
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
          rows.push(`<div class="msg msg-ai" data-msg="${m.id}" data-idx="${idx}">
            <div class="msg-ai-meta"><span class="m-model">${esc(modelNameOf())}</span>${metaDone(m)}</div>
            <div class="tool-trace">${traceHtml}</div>
            <div class="msg-ai-body" data-render="${m.id}">${renderMd(parsed.answer ?? "")}</div>
            ${msgActions(m, isLastAssistant)}
          </div>`);
          return;
        }
      }
      const statusTag = m.status === "stopped" ? `<span class="msg-status">已停止</span>`
        : m.status === "failed" ? `<span class="msg-status msg-status-fail">生成失败</span>` : "";
      rows.push(`<div class="msg msg-ai" data-msg="${m.id}" data-idx="${idx}">
        <div class="msg-ai-meta"><span class="m-model">${esc(modelNameOf())}</span>${metaDone(m)}</div>
        <div class="msg-ai-body" data-render="${m.id}">${renderMd(m.content)}</div>
        ${statusTag}${msgActions(m, isLastAssistant)}
      </div>`);
    });
    box.innerHTML = rows.join("") || `<div class="chat-empty">
      <div class="chat-empty-sub">这个会话还没有消息，试试：</div>
      <div class="chat-suggest">
        ${SUGGESTIONS.map((s) => `<button class="suggest-chip" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}
      </div>
    </div>`;
    box.scrollTop = box.scrollHeight;
    renderTicks();
  }

  /* ② 提问导航刻度条：每条=一次用户提问；≥7 条显示，窄区由 CSS 隐藏 */
  function renderTicks() {
    const nav = el.querySelector(".chat-ticks");
    if (!nav) return;
    const box = el.querySelector(".chat-msgs");
    const users = [...box.querySelectorAll(".msg-user")];
    if (users.length < 7) { nav.classList.remove("show"); nav.innerHTML = ""; return; }
    nav.classList.add("show");
    nav.innerHTML = users.map((u) => {
      const idx = u.dataset.idx;
      const text = u.querySelector(".msg-user-bubble")?.textContent ?? "";
      return `<span class="tk" data-tick="${idx}"><span class="tk-tip">${esc(text.slice(0, 40))}</span></span>`;
    }).join("");
    syncCurTick();
  }

  function syncCurTick() {
    const nav = el.querySelector(".chat-ticks");
    const box = el.querySelector(".chat-msgs");
    if (!nav || !nav.classList.contains("show") || !box) return;
    const boxTop = box.getBoundingClientRect().top;
    let cur = null;
    for (const u of box.querySelectorAll(".msg-user")) {
      if (u.getBoundingClientRect().top <= boxTop + 90) cur = u.dataset.idx;
      else break;
    }
    nav.querySelectorAll(".tk").forEach((t) => t.classList.toggle("cur", t.dataset.tick === cur));
  }

  function scrollToMsgIdx(idx) {
    // 命中消息在视窗外时先扩窗再滚动
    if (idx < S.messages.length - S.winSize) {
      S.winSize = S.messages.length - idx + 10;
      renderMessages();
      highlightAll();
    }
    requestAnimationFrame(() => {
      el.querySelector(`.msg[data-idx="${idx}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  /* ③ 对话内搜索 */
  function renderSearchResults(q) {
    const res = el.querySelector(".csr");
    if (!res) return;
    const query = q.trim();
    if (!query) { res.innerHTML = `<div class="none">输入关键词搜索本对话</div>`; return; }
    const eQuery = esc(query);
    const hits = [];
    S.messages.forEach((m, idx) => {
      const pos = m.content.indexOf(query);
      if (pos >= 0 && hits.length < 20) {
        const from = Math.max(0, pos - 14);
        const to = pos + query.length + 20;
        const snippet = (from > 0 ? "…" : "") + m.content.slice(from, to) + (to < m.content.length ? "…" : "");
        hits.push({ idx, html: esc(snippet).replace(eQuery, `<mark>${eQuery}</mark>`) });
      }
    });
    res.innerHTML = hits.length
      ? hits.map((h) => `<div class="ri" data-goto-msg="${h.idx}">${h.html}</div>`).join("")
      : `<div class="none">没有匹配的消息</div>`;
  }

  function renderMd(text) {
    if (!text) return `<span class="msg-thinking">正在输入…</span>`;
    return md.render(text);
  }

  function highlightAll() {
    el.querySelectorAll("pre code").forEach((block) => {
      try { hljs.highlightElement(block); } catch { /* 未知语言跳过 */ }
    });
    // 代码块一键复制：每个 pre 右上角注入按钮（复制文案走委托，见 bind()）
    el.querySelectorAll(".msg-ai-body pre").forEach((pre) => {
      if (pre.querySelector(".copy-code")) return; // 防重复注入
      const btn = document.createElement("button");
      btn.className = "copy-code";
      btn.type = "button";
      btn.title = "复制代码";
      btn.innerHTML = `${LC.IC.copy}<span>复制</span>`;
      pre.appendChild(btn);
    });
  }

  /* 会话列表单一渲染入口：主列表与搜索过滤共用（A2 修复） */
  function convItemHtml(c, hubActive) {
    return `
      <div class="conv-item ${c.id === S.currentId && !hubActive ? "active" : ""}" data-conv="${c.id}">
        <span class="conv-title">${esc(c.title)}</span>
        ${c.mode === "agent" ? '<span class="tag soon">agent</span>' : ""}
        <span class="conv-ops">
          <button class="conv-op" data-rename="${c.id}" title="重命名">${LC.IC.sliders}</button>
          <button class="conv-op" data-del="${c.id}" title="删除">${LC.IC.close}</button>
        </span>
      </div>`;
  }

  function renderSidebar() {
    const list = el.querySelector(".chat-list");
    if (!list) return;
    const hubActive = S.current?.app === "hub";
    const q = S.query.trim();
    const shown = S.conversations.filter((c) => !q || c.title.includes(q));
    list.innerHTML = `
      <div class="conv-item hub-item ${hubActive ? "active" : ""}" data-hub="1">
        <span class="conv-title">总对话 · 跨应用查询</span>
        <span class="tag soon">agent</span>
      </div>
      <div class="conv-sep"></div>
      ${shown.map((c) => convItemHtml(c, hubActive)).join("")
        || `<div class="conv-none">${q ? "没有匹配的会话" : "还没有会话"}</div>`}`;
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
    // 空标题占位（第一批拍板）：新会话/未选中时头部显示「新会话」
    if (titleEl) titleEl.textContent = conv?.app === "hub" ? "总对话（只读工具，跨应用查询）" : (conv?.title || "新会话");
    const banner = el.querySelector(".chat-banner");
    if (banner) banner.hidden = S.realLlm;
  }

  const currentModel = () =>
    (S.currentId === NEW_ID ? S.current?.model : S.conversations.find((c) => c.id === S.currentId)?.model)
    || S.defaultModel || "";

  function renderComposer() {
    const ta = el.querySelector(".composer-input");
    if (!ta) return;
    ta.disabled = S.generating;
    const btn = el.querySelector(".composer-send");
    btn.classList.toggle("stop", S.generating);
    btn.innerHTML = S.generating ? `<span class="stop-square"></span>` : LC.IC.arrow;
    // 草稿恢复（白皮书：切换/刷新后回填）；占位会话用固定草稿键，创建后迁移到真实 id
    const draft = draftId() ? readDraft(draftId()) : null;
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
    if (selectId === NEW_ID || (!selectId && S.currentId === NEW_ID)) {
      S.currentId = NEW_ID; // 新会话占位不在服务端列表里，单独保持
      S.current = newConvObj();
    } else if (selectId) {
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
      .then((d) => { S.messages = d.messages; S.winSize = 80; renderAll(); })
      .catch(() => { S.messages = []; renderAll(); });
  }

  async function loadMessages(convId) {
    const data = await api(`/api/chat/conversations/${convId}/messages`);
    S.messages = data.messages;
    S.winSize = 80; // 换会话重置视窗
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

  /* ---------- 发送（单档拍板：全部走 pi 只读工具循环；简单问题模型不调工具≈单次成本） ---------- */
  async function send() {
    const ta = el.querySelector(".composer-input");
    const text = ta.value.trim();
    if (!text || S.generating) return;
    const wasNew = S.current?.id === NEW_ID; // 占位草稿键迁移用（A1 配套）
    if (!S.current || S.current.id === NEW_ID) {
      // 懒创建：占位阶段选的模型随创建落库（A1 配套）
      const payload = S.current?.id === NEW_ID ? { model: S.current.model ?? null } : {};
      const { conversation } = await api("/api/chat/conversations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      S.currentId = conversation.id;
      S.current = conversation;
      location.hash = `#/chat/${conversation.id}`;
      await loadConversations(S.currentId);
    }
    const convId = S.current.id;
    // 占位会话创建后，把占位草稿迁到真实 id（reqId 沿用，幂等不变）
    if (wasNew) {
      const old = readDraft(NEW_ID);
      if (old) { writeDraft(convId, old); clearDraft(NEW_ID); }
    }
    // 草稿记录发送中的文本与请求标识（重试沿用，原文不变不换标识）
    let draft = readDraft(convId) || {};
    if (draft.text !== text || !draft.reqId) draft = { text, reqId: crypto.randomUUID() };
    writeDraft(convId, draft);

    try {
      await api("/api/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: convId, content: text, req_id: draft.reqId }),
      });
    } catch {
      // 情况 1：用户消息未保存——原文回填输入框（B4，学 RAGFlow pendingInput），草稿保留供重试
      ta.value = draft.text;
      ta.focus();
      toast("发送失败，原文已回填，可重新发送");
      return;
    }
    clearDraft(convId);
    ta.value = "";
    draft = null;
    await loadConversations(); // 标题可能自动生成
    await agentSend(text);
  }

  /* ---------- agent 流程（pi 接管：文本增量 + 工具卡片，SSE）——单档后唯一发送路径 ---------- */
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
      // 流式光标：回答末尾追加闪烁 caret，结束后由 loadMessages 重渲染自然消失
      if (answerEl) answerEl.innerHTML = (renderMd(answerText) || '<span class="msg-thinking">正在输入…</span>') + '<span class="stream-caret" aria-hidden="true"></span>';
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
      const res = await apiStream("/api/chat/agent", {
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

  /* 重新生成 / 重试：走单次调用路径（/generate，带 regenerate/retry_message_id）——
     回答类消息的快速再来一次；失败 agent 消息的重试也走这里 */
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
      if (bodyEl) bodyEl.innerHTML = renderMd(full) + '<span class="stream-caret" aria-hidden="true"></span>';
      const box = el.querySelector(".chat-msgs");
      if (box) box.scrollTop = box.scrollHeight;
    }, 80);

    try {
      const res = await apiStream("/api/chat/generate", {
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
      // 代码块复制（按钮在 pre 里，随消息重渲染重新注入，无需解绑）
      const copyCode = e.target.closest(".copy-code");
      if (copyCode) {
        const code = copyCode.closest("pre")?.querySelector("code");
        const label = copyCode.querySelector("span");
        if (code) {
          await navigator.clipboard.writeText(code.textContent).catch(() => {});
          copyCode.classList.add("copied");
          if (label) label.textContent = "已复制";
          setTimeout(() => { copyCode.classList.remove("copied"); if (label) label.textContent = "复制"; }, 1600);
          toast("代码已复制");
        }
        return;
      }

      // ⑤ 用户消息「编辑重发」：填入输入框并聚焦（学 WorkBuddy 消息可编辑）
      const editUser = e.target.closest("[data-edit-user]");
      if (editUser) {
        const m = S.messages[Number(editUser.dataset.editUser)];
        const ta = el.querySelector(".composer-input");
        if (m && ta) { ta.value = m.content; ta.focus(); ta.dispatchEvent(new Event("input", { bubbles: true })); }
        return;
      }

      // ② 刻度条定位
      const tickEl = e.target.closest("[data-tick]");
      if (tickEl) { scrollToMsgIdx(Number(tickEl.dataset.tick)); return; }

      // 「加载更早」扩窗
      if (e.target.closest("[data-more-msgs]")) {
        const firstIdx = el.querySelector(".chat-msgs .msg")?.dataset.idx;
        S.winSize += 80;
        renderMessages();
        highlightAll();
        if (firstIdx != null) {
          requestAnimationFrame(() => {
            el.querySelector(`.msg[data-idx="${firstIdx}"]`)?.scrollIntoView({ block: "start" });
          });
        }
        return;
      }

      const convEl = e.target.closest("[data-conv]");
      const newBtn = e.target.closest("[data-new]");
      const sendBtn = e.target.closest(".composer-send");
      const stopGen = S.generating && sendBtn;
      const menuBtn = e.target.closest("[data-menu]");
      const searchBtn = e.target.closest("[data-chat-search]");
      const backdrop = e.target.classList.contains("chat-backdrop");

      if (stopGen) { S.abort?.abort(); return; }
      if (sendBtn) { await send(); return; }
      // B7：建议问题 chip → 填入输入框并聚焦（不直接发送，给用户改的机会）
      const suggest = e.target.closest("[data-suggest]");
      if (suggest) {
        const ta = el.querySelector(".composer-input");
        if (ta) { ta.value = suggest.dataset.suggest; ta.focus(); ta.dispatchEvent(new Event("input", { bubbles: true })); }
        return;
      }
      if (e.target.closest("[data-hub]")) { openHub(); return; }
      if (newBtn) {
        // A1 修复：不落库，本地占位；发送首条消息时才创建（懒创建拍板）
        S.currentId = NEW_ID;
        S.current = newConvObj();
        S.messages = [];
        location.hash = "#/chat";
        S.sidebarOpen = false;
        renderAll();
        el.querySelector(".composer-input")?.focus();
        return;
      }
      if (menuBtn || backdrop) {
        S.sidebarOpen = backdrop ? false : !S.sidebarOpen;
        renderAll();
        return;
      }
      // ③ 对话内搜索开关与跳转
      if (searchBtn) {
        const pop = el.querySelector(".chat-search-pop");
        const willOpen = pop.hidden;
        pop.hidden = !willOpen;
        if (willOpen) { renderSearchResults(""); pop.querySelector("input")?.focus(); }
        return;
      }
      const gotoMsg = e.target.closest("[data-goto-msg]");
      if (gotoMsg) {
        el.querySelector(".chat-search-pop").hidden = true;
        scrollToMsgIdx(Number(gotoMsg.dataset.gotoMsg));
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
      // 新会话占位未落库：模型只记本地，创建时随首条消息带上（A1 配套）
      if (S.currentId !== NEW_ID) {
        await api(`/api/chat/conversations/${S.currentId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: sel.value }),
        });
        const c = S.conversations.find((x) => x.id === S.currentId);
        if (c) c.model = sel.value;
      } else if (S.current) {
        S.current.model = sel.value;
      }
      toast("已切换模型，只影响之后的回答");
    });

    el.addEventListener("input", (e) => {
      const ta = e.target.closest(".composer-input");
      if (ta) {
        if (!ta.value.trim() || !draftId()) return;
        // 输入即存草稿（换会话/刷新后恢复）；占位会话存固定键
        const prev = readDraft(draftId()) || {};
        writeDraft(draftId(), { ...prev, text: ta.value });
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
        return;
      }
      const search = e.target.closest(".chat-search-input");
      if (search) renderSearchResults(search.value);
      const q = e.target.closest(".conv-search");
      if (q) {
        S.query = q.value;
        renderSidebar(); // 与主列表同一渲染函数，agent 标签不丢
      }
    });

    // ② 滚动同步刻度条当前位置（捕获阶段：chat-msgs 滚动不冒泡）
    el.addEventListener("scroll", (e) => {
      if (e.target.classList?.contains("chat-msgs")) syncCurTick();
    }, true);

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
          <div class="chat-list">
            <div class="skeleton sk-conv"></div><div class="skeleton sk-conv"></div>
            <div class="skeleton sk-conv"></div><div class="skeleton sk-conv"></div>
            <div class="skeleton sk-conv"></div><div class="skeleton sk-conv"></div>
          </div>
        </aside>
        <section class="chat-main">
          <div class="chat-head">
            <button class="icon-btn chat-menu" data-menu title="会话列表">${LC.IC.grid}</button>
            <span class="chat-title">新会话</span>
            <button class="icon-btn" data-chat-search title="对话内搜索" aria-label="对话内搜索">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
            </button>
          </div>
          <div class="chat-search-pop" hidden>
            <input class="chat-search-input" placeholder="搜索本对话消息…">
            <div class="csr"><div class="none">输入关键词搜索本对话</div></div>
          </div>
          <div class="chat-banner" hidden>未配置模型渠道，当前为本地假模型——全链路可跑，回答不真实。到「模型 & API 管理」接入。</div>
          <div class="chat-flow-wrap">
            <div class="chat-msgs"></div>
            <nav class="chat-ticks" aria-label="提问导航"></nav>
          </div>
          <div class="chat-composer">
            <div class="composer-ctl">
              <select class="model-select" title="模型选择（按会话生效）"></select>
              <span class="spacer"></span>
              <span class="kbd-hint">Enter 发送 · Shift+Enter 换行</span>
            </div>
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
        // 占位会话未落库，不请求消息列表（A1 配套，防 404）
        if (S.currentId && S.currentId !== NEW_ID) await loadMessages(S.currentId);
        renderAll();
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
