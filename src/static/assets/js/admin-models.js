// 管理页 · 模型 & API 管理区块（需求-模型API管理-v1.md §7；信息密度参考 one-api）
// 三级树：供应商卡（含测试/拉模型/编辑/删除）→ 套餐行 → 模型表（勾选/批量/通用/启停/授权/日志）
// 规矩：事件委托、LC.openModal 中央弹窗、错误文案用后端原文；密钥只提交不回首
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;
  const { openModal, closeModal, esc, IC } = LC;

  const S = { providers: [], users: [], loading: true, error: "", picked: new Set(), msg: "" };

  let el = null; // 容器（admin 页签内容区）

  async function req(path, options = {}) {
    const res = await fetch(path, { headers: { Accept: "application/json", ...(options.headers ?? {}) }, ...options });
    if (res.status === 401 && LC.handleAuth401) LC.handleAuth401();
    let data = null;
    try { data = await res.json(); } catch { /* 非 JSON */ }
    if (!res.ok) {
      const message = (typeof data?.message === "string" && data.message) || `HTTP ${res.status}`;
      throw Object.assign(new Error(message), { status: res.status, payload: data });
    }
    return data;
  }

  const fmtPrice = (v) => (v == null ? "—" : `¥${Number(v).toFixed(2)}`);
  const protocolBadge = (p) => `<span class="badge badge-role-${p === "anthropic" ? "admin" : "member"}">${esc(p)}</span>`;
  const planTypeBadge = (t) => `<span class="badge ${t === "official" ? "badge-on" : "badge-role-member"}">${esc(t)}</span>`;

  /* ---------- 数据 ---------- */
  async function loadAll() {
    S.loading = true; S.error = "";
    try {
      const [tree, users] = await Promise.all([req("/api/models/tree"), req("/api/admin/users")]);
      S.providers = tree.providers ?? [];
      S.users = users.users ?? [];
    } catch (err) {
      S.error = err.message ?? "加载失败";
    }
    S.loading = false;
    paint();
  }

  const setMsg = (text, ok) => {
    S.msg = text;
    const n = el?.querySelector("#mmMsg");
    if (n) { n.textContent = text; n.className = `form-msg ${ok ? "ok" : "err"}`; }
  };

  /* ---------- 渲染 ---------- */
  function providerCard(p) {
    const plans = p.plans ?? [];
    const models = p.models ?? [];
    return `
    <div class="card mm-provider" data-provider="${p.id}">
      <div class="mm-provider-head">
        <span class="card-title">${esc(p.name)} <span class="tbl-dim">· ${esc(p.code)}</span></span>
        ${protocolBadge(p.protocol)}
        ${p.hasKey ? `<span class="badge badge-role-member" title="密钥脱敏提示">${esc(p.keyHint)}</span>` : `<span class="badge badge-off">无密钥</span>`}
        ${p.enabled ? '<span class="badge badge-on">启用</span>' : '<span class="badge badge-off">停用</span>'}
        <span class="mm-head-acts">
          <button class="btn btn-ghost mm-test" data-test-provider="${p.id}">测试</button>
          ${p.protocol !== "mineru" ? `<button class="btn btn-ghost mm-fetch" data-fetch-provider="${p.id}">一键获取模型</button>` : ""}
          <button class="btn btn-ghost mm-edit-provider" data-edit-provider="${p.id}">编辑</button>
          <button class="btn btn-ghost mm-add-plan" data-add-plan="${p.id}">+ 套餐</button>
          <button class="conv-op mm-del-provider" data-del-provider="${p.id}" title="删除供应商">${IC.close}</button>
        </span>
      </div>
      <div class="tbl-dim mm-sub">${esc(p.baseUrl)}${p.remark ? ` · ${esc(p.remark)}` : ""}</div>
      ${plans.length ? `<div class="mm-plans">${plans.map((pl) => `
        <div class="mm-plan-row">
          ${planTypeBadge(pl.planType)} <b>${esc(pl.name)}</b>
          <span class="tbl-dim">${pl.rpmLimit ? `RPM ${pl.rpmLimit}` : "不限 RPM"}${pl.dailyLimit ? ` · 日 ${pl.dailyLimit}` : ""}${pl.hasKey ? ` · ${esc(pl.keyHint)}` : ""}</span>
          <span class="mm-plan-acts">
            <button class="row-act mm-edit-plan" data-edit-plan="${pl.id}">编辑</button>
            <button class="row-act danger mm-del-plan" data-del-plan="${pl.id}">删除</button>
          </span>
        </div>`).join("")}</div>` : ""}
      ${models.length ? modelsTable(p, models) : `<div class="chart-none">还没有模型——点「一键获取模型」从供应商拉取</div>`}
    </div>`;
  }

  function modelsTable(p, models) {
    return `
    <div class="tbl-wrap mm-tbl-wrap"><table class="tbl mm-tbl">
      <thead><tr>
        <th><input type="checkbox" class="grant-chk mm-check-all" data-provider-check="${p.id}" title="全选"></th>
        <th>模型</th><th>能力</th><th>ref</th><th>价格(入/出 每百万token)</th><th>来源</th><th>通用</th><th>启用</th><th>授权</th><th></th>
      </tr></thead>
      <tbody>
        ${models.map((m) => `
        <tr data-model-row="${m.id}">
          <td><input type="checkbox" class="grant-chk mm-check" data-check="${m.id}" ${S.picked.has(m.id) ? "checked" : ""}></td>
          <td><b>${esc(m.displayName)}</b>${m.displayOrder === 0 && models[0]?.id === m.id ? ' <span class="tag" title="排序第一位 = 全员默认模型（学 WorkBuddy）">默认</span>' : ""}</td>
          <td>${[m.supportsImages ? '<span class="tag">图片</span>' : "", (m.thinkingLevels?.length || m.thinking) ? '<span class="tag soon">思考</span>' : ""].join("") || '<span class="tbl-dim">—</span>'}</td>
          <td class="tbl-dim mm-mono">${esc(m.ref)}</td>
          <td class="mm-mono">${fmtPrice(m.inputPrice)} / ${fmtPrice(m.outputPrice)}</td>
          <td>${m.source === "fetched" ? `<span class="tag">拉取</span>` : `<span class="tag soon">手录</span>`}</td>
          <td><input type="checkbox" class="grant-chk mm-common" data-common="${m.id}" ${m.isCommon ? "checked" : ""} title="通用模型：全员可用"></td>
          <td><input type="checkbox" class="grant-chk mm-enable" data-enable="${m.id}" ${m.enabled ? "checked" : ""}></td>
          <td><button class="row-act mm-grants" data-grants="${m.id}" data-name="${esc(m.displayName)}">${m.grants?.length ?? 0} 项</button></td>
          <td><div class="row-acts">
            <button class="row-act mm-sort" data-sort-up="${m.id}" title="上移（排序第一位=默认模型）" ${models.indexOf(m) === 0 ? "disabled" : ""}>↑</button>
            <button class="row-act mm-sort" data-sort-down="${m.id}" title="下移" ${models.indexOf(m) === models.length - 1 ? "disabled" : ""}>↓</button>
            <button class="row-act mm-edit-model" data-edit-model="${m.id}">编辑</button>
            <button class="row-act danger mm-del-model" data-del-model="${m.id}">删除</button>
          </div></td>
        </tr>`).join("")}
      </tbody>
    </table></div>`;
  }

  function paint() {
    if (!el) return;
    if (S.loading) { el.innerHTML = `<div class="empty-hint">加载中…</div>`; return; }
    if (S.error) { el.innerHTML = `<div class="empty-hint">加载失败：${esc(S.error)}</div>`; return; }
    el.innerHTML = `
      <div class="admin-toolbar">
        <button class="btn btn-primary" data-mm-add-provider>${IC.check} 添加供应商</button>
        <button class="btn btn-ghost" data-mm-refresh>刷新</button>
        <button class="btn btn-ghost" data-mm-batch-enable ${S.picked.size ? "" : "disabled"}>批量启用${S.picked.size ? `(${S.picked.size})` : ""}</button>
        <button class="btn btn-ghost" data-mm-batch-disable ${S.picked.size ? "" : "disabled"}>批量停用${S.picked.size ? `(${S.picked.size})` : ""}</button>
        <span class="form-msg" id="mmMsg">${esc(S.msg)}</span>
      </div>
      ${S.providers.length
        ? S.providers.map(providerCard).join("")
        : `<div class="empty-hint">还没有供应商。点「添加供应商」接入官方 API 或渠道套餐（MinerU 选 mineru 协议）。</div>`}
      <div class="card card-gap">
        <div class="card-title card-title-gap">权限查询 <span class="tbl-dim card-sub">输入成员账号，看他最终可用哪些模型（并集规则）</span></div>
        <div class="mm-visbar">
          <input class="text-input mm-vis-input" placeholder="成员账号，如 zhangsan" data-mm-vis-input>
          <button class="btn btn-ghost" data-mm-vis-go>查询</button>
          <span class="form-msg" data-mm-vis-result></span>
        </div>
      </div>
      <div class="card card-gap">
        <div class="card-title card-title-gap">调用日志 <span class="tbl-dim card-sub">最近 50 条</span></div>
        <div data-mm-logs><div class="chart-none">加载中…</div></div>
      </div>`;
    loadLogs();
  }

  /* 权限查询：某成员最终可见模型（学 WorkBuddy 企业版「权限查询」） */
  async function queryVisibility() {
    const input = el.querySelector("[data-mm-vis-input]");
    const out = el.querySelector("[data-mm-vis-result]");
    const username = input?.value.trim();
    if (!username || !out) return;
    out.textContent = "查询中…";
    out.className = "form-msg";
    try {
      const data = await req(`/api/models/visibility?username=${encodeURIComponent(username)}`);
      const enabled = data.models.filter((m) => m.enabled);
      out.className = "form-msg ok";
      out.textContent = data.isAdmin
        ? `${username}（管理员）可见全部 ${data.models.length} 个模型`
        : `${username}（${data.user.role === "member" ? "成员" : data.user.role}）可用 ${enabled.length} 个：${enabled.slice(0, 6).map((m) => m.name).join("、")}${enabled.length > 6 ? ` 等 ${enabled.length} 个` : ""}`;
    } catch (err) {
      out.className = "form-msg err";
      out.textContent = err.message;
    }
  }

  /* 排序：与相邻模型交换位次（排序第一位=全员默认模型，学 WorkBuddy） */
  async function sortModel(id, dir) {
    for (const p of S.providers) {
      const models = p.models ?? [];
      const idx = models.findIndex((m) => m.id === id);
      if (idx < 0) continue;
      const swap = dir === "up" ? idx - 1 : idx + 1;
      if (swap < 0 || swap >= models.length) return;
      const reordered = [...models];
      [reordered[idx], reordered[swap]] = [reordered[swap], reordered[idx]];
      await Promise.all(reordered.map((m, i) =>
        req(`/api/models/${m.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ displayOrder: i * 10 }) })));
      setMsg("已调整排序：第一位即默认模型", true);
      loadAll();
      return;
    }
  }

  async function loadLogs() {
    const box = el?.querySelector("[data-mm-logs]");
    if (!box) return;
    try {
      const { logs } = await req("/api/models/logs?limit=50");
      if (!logs.length) { box.innerHTML = `<div class="chart-none">还没有调用记录</div>`; return; }
      box.innerHTML = `<div class="tbl-wrap"><table class="tbl mm-tbl">
        <thead><tr><th>时间</th><th>模型</th><th>用户</th><th>应用</th><th>状态</th><th>Token(入/出)</th><th>费用</th><th>延迟</th><th>错误</th></tr></thead>
        <tbody>${logs.map((l) => `
          <tr>
            <td class="tbl-dim mm-mono">${new Date(l.createdAt).toLocaleString("zh-CN", { hour12: false })}</td>
            <td>${esc(l.modelName)}</td>
            <td>${esc(l.username ?? "?")}</td>
            <td class="tbl-dim">${esc(l.app)}</td>
            <td>${l.status === "ok" ? '<span class="badge badge-on">成功</span>' : l.status === "stopped" ? '<span class="badge badge-off">停止</span>' : '<span class="badge badge-role-admin">失败</span>'}</td>
            <td class="mm-mono">${l.promptTokens ?? "—"} / ${l.completionTokens ?? "—"}</td>
            <td class="mm-mono">¥${(l.costFen / 100).toFixed(2)}</td>
            <td class="mm-mono">${l.latencyMs}ms</td>
            <td class="tbl-dim" title="${esc(l.errorMsg)}">${esc(l.errorCode || l.errorMsg.slice(0, 24))}</td>
          </tr>`).join("")}</tbody>
      </table></div>`;
    } catch {
      box.innerHTML = `<div class="chart-none">日志加载失败</div>`;
    }
  }

  /* ---------- 弹窗表单 ---------- */
  const field = (id, label, type = "text", extra = "") =>
    `<label class="login-field" for="${id}"><span class="login-label">${label}</span><input class="text-input" id="${id}" type="${type}" autocomplete="off" ${extra}></label>`;

  const providerForm = (p = null) => `
    ${field("mpName", "名称", "text", `value="${esc(p?.name ?? "")}" maxlength="40"`)}
    ${p ? "" : field("mpCode", "英文码（模型 ref 前缀，建后不可改）", "text", 'placeholder="deepseek" maxlength="32"')}
    <label class="login-field"><span class="login-label">协议</span>
      <select class="text-input" id="mpProtocol">
        ${["openai", "anthropic", "mineru"].map((x) => `<option value="${x}" ${p?.protocol === x ? "selected" : ""}>${x === "openai" ? "OpenAI 兼容" : x === "anthropic" ? "Anthropic" : "MinerU（服务型）"}</option>`).join("")}
      </select></label>
    ${field("mpBaseUrl", "接口地址", "text", `value="${esc(p?.baseUrl ?? "")}" placeholder="https://api.deepseek.com"`)}
    <label class="login-field"><span class="login-label">鉴权方式</span>
      <select class="text-input" id="mpAuthType">
        ${[["bearer", "Authorization: Bearer"], ["header", "自定义 Header"], ["query", "Query 参数"], ["none", "无鉴权"]].map(([v, t]) => `<option value="${v}" ${p?.authType === v ? "selected" : ""}>${t}</option>`).join("")}
      </select></label>
    <label class="login-field mp-header-name" ${p?.authType === "header" ? "" : "hidden"}><span class="login-label">Header 名（如 x-api-key）</span><input class="text-input" id="mpHeaderName" value="${esc(p?.authConfig?.headerName ?? "")}" placeholder="X-API-Key"></label>
    ${field("mpKey", p?.hasKey ? `密钥（留空不改；当前 ${esc(p.keyHint)}）` : "API 密钥", "password", 'autocomplete="new-password"')}
    ${field("mpRemark", "备注", "text", `value="${esc(p?.remark ?? "")}" maxlength="100"`)}
    <div class="form-msg" id="mpMsg"></div>`;

  function openProviderModal(p = null) {
    openModal(p ? `编辑供应商 · ${p.name}` : "添加供应商", providerForm(p), `
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-primary" data-mm-save-provider ${p ? `data-id="${p.id}"` : ""}>保存</button>`);
  }

  const planForm = (pl = null) => `
    ${field("mplName", "套餐名", "text", `value="${esc(pl?.name ?? "")}" maxlength="40"`)}
    <label class="login-field"><span class="login-label">渠道类型</span>
      <select class="text-input" id="mplType">
        ${["official", "tokenplan", "agentplan", "third_party"].map((x) => `<option value="${x}" ${pl?.planType === x ? "selected" : ""}>${x}</option>`).join("")}
      </select></label>
    ${field("mplBaseUrl", "接口地址覆盖（留空用供应商地址）", "text", `value="${esc(pl?.baseUrl ?? "")}"`)}
    ${field("mplKey", pl?.hasKey ? `套餐密钥（留空不改；当前 ${esc(pl.keyHint)}）` : "套餐密钥（优先于供应商密钥）", "password", 'autocomplete="new-password"')}
    ${field("mplRpm", "每分钟调用上限（0=不限）", "number", `value="${pl?.rpmLimit ?? 0}" min="0"`)}
    ${field("mplDaily", "每日调用上限（0=不限）", "number", `value="${pl?.dailyLimit ?? 0}" min="0"`)}
    <div class="form-msg" id="mplMsg"></div>`;

  function openPlanModal(providerId, pl = null) {
    openModal(pl ? `编辑套餐 · ${pl.name}` : "添加套餐", planForm(pl), `
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-primary" data-mm-save-plan data-provider="${providerId}" ${pl ? `data-id="${pl.id}"` : ""}>保存</button>`);
  }

  const modelForm = (m) => `
    ${field("mmName", "显示名", "text", `value="${esc(m.displayName)}" maxlength="60"`)}
    ${field("mmCtx", "上下文窗口", "number", `value="${m.contextWindow ?? ""}" min="0"`)}
    ${field("mmMax", "最大输出 token", "number", `value="${m.maxOutputTokens ?? ""}" min="0"`)}
    ${field("mmIn", "输入价格（元/百万 token，可空）", "number", `value="${m.inputPrice ?? ""}" step="0.000001" min="0"`)}
    ${field("mmOut", "输出价格（元/百万 token，可空）", "number", `value="${m.outputPrice ?? ""}" step="0.000001" min="0"`)}
    <label class="login-field"><span class="login-label">思考强度（推理模式，学 WorkBuddy）</span>
      <select class="text-input" id="mmThinking">
        <option value="" ${!m.thinking ? "selected" : ""}>关闭（默认不走推理）</option>
        ${[["minimal", "最轻"], ["low", "低"], ["medium", "中"], ["high", "高"], ["xhigh", "超高"], ["max", "极致"]]
          .map(([v, t]) => `<option value="${v}" ${m.thinking === v ? "selected" : ""}>默认 · ${t}</option>`).join("")}
      </select></label>
    <label class="login-field mm-img-row"><span class="login-label">图片输入（多模态：对话可发照片，模型按图理解——需供应商支持视觉）</span>
      <input type="checkbox" class="grant-chk" id="mmImages" ${m.supportsImages ? "checked" : ""}></label>
    <div class="me-sec"><div class="me-sec-t">支持的思考强度档位（对话内可调范围）</div>
      ${[["low", "低"], ["medium", "中"], ["high", "高"], ["xhigh", "超高"], ["max", "极致"]]
        .map(([v, t]) => `<label class="chk-line"><input type="checkbox" data-think-lv="${v}" ${(m.thinkingLevels ?? ["low", "medium", "high", "xhigh", "max"]).includes(v) ? "checked" : ""}> ${t}</label>`).join("")}
    </div>
    <div class="form-msg" id="mmfMsg"></div>`;

  const grantsForm = (m) => {
    const grants = m.grants ?? [];
    const roleOn = (r) => grants.some((g) => g.type === "role" && g.grantee === r);
    const userOn = (id) => grants.some((g) => g.type === "user" && String(g.grantee) === String(id));
    return `
      <p class="p-note p-note-plain">通用开关打开时全员可用，授权仅用于<strong>非通用</strong>模型。<b>${esc(m.displayName)}</b> 当前${m.isCommon ? "是通用模型" : "非通用"}。</p>
      <div class="me-sec"><div class="me-sec-t">按角色</div>
        ${["admin", "member"].map((r) => `<label class="chk-line"><input type="checkbox" data-grant-role="${r}" ${roleOn(r) ? "checked" : ""}> ${r === "admin" ? "管理员" : "成员"}</label>`).join("")}
      </div>
      <div class="me-sec"><div class="me-sec-t">按账号</div>
        ${S.users.map((u) => `<label class="chk-line"><input type="checkbox" data-grant-user="${u.id}" ${userOn(u.id) ? "checked" : ""}> ${esc(u.displayName)}（${esc(u.username)}）</label>`).join("")}
      </div>
      <div class="form-msg" id="mmgMsg"></div>`;
  };

  /* ---------- 事件 ---------- */
  function onClick(e) {
    if (e.target.closest("[data-mm-add-provider]")) { openProviderModal(); return; }
    if (e.target.closest("[data-mm-refresh]")) { S.msg = ""; loadAll(); return; }

    const testBtn = e.target.closest("[data-test-provider]");
    if (testBtn) {
      const id = testBtn.dataset.testProvider;
      testBtn.disabled = true; testBtn.textContent = "测试中…";
      req(`/api/models/providers/${id}/test`, { method: "POST" })
        .then((r) => setMsg(r.ok ? `连通正常（${r.latencyMs}ms${r.modelsCount != null ? `，可拉 ${r.modelsCount} 个模型` : ""}）` : `测试失败：${r.error}`, r.ok))
        .catch((err) => setMsg(err.message, false))
        .finally(() => { testBtn.disabled = false; testBtn.textContent = "测试"; });
      return;
    }

    const fetchBtn = e.target.closest("[data-fetch-provider]");
    if (fetchBtn) {
      const id = fetchBtn.dataset.fetchProvider;
      fetchBtn.disabled = true; fetchBtn.textContent = "拉取中…";
      req("/api/models/fetch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ providerId: Number(id) }) })
        .then((r) => {
          if (r.ok === false) setMsg(`拉取失败：${r.error}`, false);
          else { setMsg(`拉取完成：新增 ${r.created}，更新 ${r.updated}，共 ${r.total}（${r.latencyMs}ms）`, true); loadAll(); }
        })
        .catch((err) => setMsg(err.message, false))
        .finally(() => { fetchBtn.disabled = false; fetchBtn.textContent = "一键获取模型"; });
      return;
    }

    const editP = e.target.closest("[data-edit-provider]");
    if (editP) { openProviderModal(S.providers.find((x) => x.id === Number(editP.dataset.editProvider))); return; }
    const delP = e.target.closest("[data-del-provider]");
    if (delP) {
      const p = S.providers.find((x) => x.id === Number(delP.dataset.delProvider));
      openModal("删除供应商", `<p>删除 <b>${esc(p.name)}</b> 将级联删除其套餐、模型与授权，调用日志保留快照。不可恢复。</p>`,
        `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" data-mm-confirm-del-provider="${p.id}">删除</button>`);
      return;
    }
    const addPlan = e.target.closest("[data-add-plan]");
    if (addPlan) { openPlanModal(Number(addPlan.dataset.addPlan)); return; }
    const editPlan = e.target.closest("[data-edit-plan]");
    if (editPlan) {
      for (const p of S.providers) {
        const pl = (p.plans ?? []).find((x) => x.id === Number(editPlan.dataset.editPlan));
        if (pl) { openPlanModal(p.id, pl); return; }
      }
      return;
    }
    const delPlan = e.target.closest("[data-del-plan]");
    if (delPlan) {
      openModal("删除套餐", "<p>套餐下的模型会一并删除（日志保留快照）。</p>",
        `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" data-mm-confirm-del-plan="${delPlan.dataset.delPlan}">删除</button>`);
      return;
    }

    const editModel = e.target.closest("[data-edit-model]");
    if (editModel) {
      const m = findModel(Number(editModel.dataset.editModel));
      if (m) {
        openModal(`编辑模型 · ${m.displayName}`, modelForm(m), `
          <button class="btn btn-ghost" data-close>取消</button>
          <button class="btn btn-primary" data-mm-save-model="${m.id}">保存</button>`);
      }
      return;
    }
    const delModel = e.target.closest("[data-del-model]");
    if (delModel) {
      openModal("删除模型", "<p>删除后前台不可见；历史调用日志保留快照。</p>",
        `<button class="btn btn-ghost" data-close>取消</button><button class="btn btn-danger" data-mm-confirm-del-model="${delModel.dataset.delModel}">删除</button>`);
      return;
    }

    const grantsBtn = e.target.closest("[data-grants]");
    if (grantsBtn) {
      const m = findModel(Number(grantsBtn.dataset.grants));
      if (m) {
        openModal(`授权 · ${m.displayName}`, grantsForm(m), `
          <button class="btn btn-ghost" data-close>取消</button>
          <button class="btn btn-primary" data-mm-save-grants="${m.id}">保存授权</button>`);
      }
      return;
    }

    if (e.target.closest("[data-mm-batch-enable]")) return batchSet(true);
    if (e.target.closest("[data-mm-batch-disable]")) return batchSet(false);

    // 权限查询 + 排序
    if (e.target.closest("[data-mm-vis-go]")) return queryVisibility();
    const sortUp = e.target.closest("[data-sort-up]");
    if (sortUp) return sortModel(Number(sortUp.dataset.sortUp), "up");
    const sortDown = e.target.closest("[data-sort-down]");
    if (sortDown) return sortModel(Number(sortDown.dataset.sortDown), "down");
    // 保存类
    if (e.target.closest("[data-mm-save-provider]")) return saveProvider(e.target.closest("[data-mm-save-provider]"));
    if (e.target.closest("[data-mm-save-plan]")) return savePlan(e.target.closest("[data-mm-save-plan]"));
    if (e.target.closest("[data-mm-save-model]")) return saveModel(e.target.closest("[data-mm-save-model]"));
    if (e.target.closest("[data-mm-save-grants]")) return saveGrants(e.target.closest("[data-mm-save-grants]"));
    if (e.target.closest("[data-mm-confirm-del-provider]")) {
      req(`/api/models/providers/${e.target.closest("[data-mm-confirm-del-provider]").dataset.mmConfirmDelProvider}`, { method: "DELETE" })
        .then(() => { closeModal(); setMsg("已删除", true); loadAll(); }).catch((err) => setMsg(err.message, false));
      return;
    }
    if (e.target.closest("[data-mm-confirm-del-plan]")) {
      req(`/api/models/plans/${e.target.closest("[data-mm-confirm-del-plan]").dataset.mmConfirmDelPlan}`, { method: "DELETE" })
        .then(() => { closeModal(); setMsg("已删除", true); loadAll(); }).catch((err) => setMsg(err.message, false));
      return;
    }
    if (e.target.closest("[data-mm-confirm-del-model]")) {
      req(`/api/models/${e.target.closest("[data-mm-confirm-del-model]").dataset.mmConfirmDelModel}`, { method: "DELETE" })
        .then(() => { closeModal(); setMsg("已删除", true); S.picked.clear(); loadAll(); }).catch((err) => setMsg(err.message, false));
      return;
    }
  }

  function findModel(id) {
    for (const p of S.providers) {
      const m = (p.models ?? []).find((x) => x.id === id);
      if (m) return m;
    }
    return null;
  }

  function onChange(e) {
    // 鉴权方式切换显隐 header 名
    if (e.target.id === "mpAuthType") {
      const show = e.target.value === "header";
      document.querySelector(".mp-header-name")?.toggleAttribute("hidden", !show);
      return;
    }
    const chk = e.target.closest(".mm-check");
    if (chk) {
      const id = Number(chk.dataset.check);
      chk.checked ? S.picked.add(id) : S.picked.delete(id);
      paint();
      return;
    }
    const checkAll = e.target.closest("[data-provider-check]");
    if (checkAll) {
      const pid = Number(checkAll.dataset.providerCheck);
      const p = S.providers.find((x) => x.id === pid);
      for (const m of p?.models ?? []) checkAll.checked ? S.picked.add(m.id) : S.picked.delete(m.id);
      paint();
      return;
    }
    const common = e.target.closest("[data-common]");
    if (common) {
      const id = Number(common.dataset.common);
      req(`/api/models/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ isCommon: common.checked }) })
        .then(() => setMsg(common.checked ? "已设为通用模型（全员可用）" : "已取消通用", true))
        .catch((err) => { setMsg(err.message, false); common.checked = !common.checked; });
      return;
    }
    const enable = e.target.closest("[data-enable]");
    if (enable) {
      const id = Number(enable.dataset.enable);
      req(`/api/models/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: enable.checked }) })
        .then(() => setMsg(enable.checked ? "已启用" : "已停用", true))
        .catch((err) => { setMsg(err.message, false); enable.checked = !enable.checked; });
      return;
    }
  }

  function numOrNull(v) { const n = Number(v); return v === "" || Number.isNaN(n) ? null : n; }

  function saveProvider(btn) {
    const id = btn.dataset.id;
    const body = {
      name: document.getElementById("mpName")?.value.trim(),
      protocol: document.getElementById("mpProtocol")?.value,
      baseUrl: document.getElementById("mpBaseUrl")?.value.trim(),
      authType: document.getElementById("mpAuthType")?.value,
      remark: document.getElementById("mpRemark")?.value.trim(),
    };
    const headerName = document.getElementById("mpHeaderName")?.value.trim();
    if (body.authType === "header") body.authConfig = { headerName: headerName || "X-API-Key" };
    const key = document.getElementById("mpKey")?.value;
    if (key) body.key = key;
    if (!id) body.code = document.getElementById("mpCode")?.value.trim();
    const msg = document.getElementById("mpMsg");
    const setErr = (t) => { if (msg) { msg.textContent = t; msg.className = "form-msg err"; } };
    req(id ? `/api/models/providers/${id}` : "/api/models/providers", {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(() => { closeModal(); setMsg("已保存", true); loadAll(); })
      .catch((err) => setErr(err.message));
  }

  function savePlan(btn) {
    const providerId = Number(btn.dataset.provider);
    const id = btn.dataset.id;
    const body = {
      providerId,
      name: document.getElementById("mplName")?.value.trim(),
      planType: document.getElementById("mplType")?.value,
      baseUrl: document.getElementById("mplBaseUrl")?.value.trim(),
      rpmLimit: Number(document.getElementById("mplRpm")?.value || 0),
      dailyLimit: Number(document.getElementById("mplDaily")?.value || 0),
    };
    const key = document.getElementById("mplKey")?.value;
    if (key) body.key = key;
    const msg = document.getElementById("mplMsg");
    req(id ? `/api/models/plans/${id}` : "/api/models/plans", {
      method: id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then(() => { closeModal(); setMsg("已保存", true); loadAll(); })
      .catch((err) => { if (msg) { msg.textContent = err.message; msg.className = "form-msg err"; } });
  }

  function saveModel(btn) {
    const id = Number(btn.dataset.mmSaveModel);
    const modal = document.getElementById("modal");
    const body = {
      displayName: document.getElementById("mmName")?.value.trim(),
      contextWindow: numOrNull(document.getElementById("mmCtx")?.value),
      maxOutputTokens: numOrNull(document.getElementById("mmMax")?.value),
      inputPrice: numOrNull(document.getElementById("mmIn")?.value),
      outputPrice: numOrNull(document.getElementById("mmOut")?.value),
      thinking: document.getElementById("mmThinking")?.value || null,
      thinkingLevels: [...modal.querySelectorAll("[data-think-lv]:checked")].map((c) => c.dataset.thinkLv),
      supportsImages: document.getElementById("mmImages")?.checked === true,
    };
    const msg = document.getElementById("mmfMsg");
    req(`/api/models/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(() => { closeModal(); setMsg("已保存", true); loadAll(); })
      .catch((err) => { if (msg) { msg.textContent = err.message; msg.className = "form-msg err"; } });
  }

  function saveGrants(btn) {
    const id = Number(btn.dataset.mmSaveGrants);
    const modal = document.getElementById("modal");
    const grants = [
      ...[...modal.querySelectorAll("[data-grant-role]:checked")].map((c) => ({ type: "role", grantee: c.dataset.grantRole })),
      ...[...modal.querySelectorAll("[data-grant-user]:checked")].map((c) => ({ type: "user", grantee: c.dataset.grantUser })),
    ];
    const msg = document.getElementById("mmgMsg");
    req(`/api/models/${id}/grants`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ grants }) })
      .then(() => { closeModal(); setMsg("授权已保存", true); loadAll(); })
      .catch((err) => { if (msg) { msg.textContent = err.message; msg.className = "form-msg err"; } });
  }

  function batchSet(enabled) {
    if (!S.picked.size) return;
    req("/api/models/batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids: [...S.picked], op: enabled ? "enable" : "disable" }) })
      .then((r) => { setMsg(`已${enabled ? "启用" : "停用"} ${r.count} 个模型`, true); S.picked.clear(); loadAll(); })
      .catch((err) => setMsg(err.message, false));
  }

  /* ---------- 挂载 ---------- */
  function mount(container) {
    el = container;
    document.addEventListener("click", onClick);
    document.addEventListener("change", onChange);
    S.picked.clear();
    loadAll();
  }

  function cleanup() {
    document.removeEventListener("click", onClick);
    document.removeEventListener("change", onChange);
    el = null;
  }

  window.LC.adminModels = { mount, cleanup };
})();
