// 流光咖啡馆 · 管理页（批 4：用户与角色 + 角色权限矩阵）
// 用户表参考 Supabase Auth Users：数据表格 + 角色/状态徽章 + 行操作
//（改角色 / 停用启用（二次确认）/ 重置密码）+ 「添加用户」入口弹窗
// 角色权限矩阵参考 thefrontkit 团队设置：角色×权限复选网格，
// 管理员×管理员格结构性锁定（不是「预勾选仍可编辑」，而是不可点）
// 规矩：事件委托（视图会重渲染）、中央弹窗走 LC.openModal、错误文案直接用后端返回
"use strict";

(() => {
  const LC = window.LC;
  if (!LC) return;

  const { openModal, closeModal, esc, IC } = LC;

  /* 带服务端错误文案的请求封装：LC.api 的 err.message 只有 "HTTP 409"，
     管理页要直接把后端 409/400 文案展示在表单旁，故这里自己解析 */
  async function req(path, options = {}) {
    const res = await fetch(path, {
      headers: { Accept: "application/json", ...(options.headers ?? {}) },
      ...options,
    });
    let data = null;
    try { data = await res.json(); } catch { /* 非 JSON 响应 */ }
    if (!res.ok) {
      const message = (typeof data?.message === "string" && data.message) || `HTTP ${res.status}`;
      throw Object.assign(new Error(message), { status: res.status });
    }
    return data;
  }

  const APPS = [
    { key: "chat", name: "对话", desc: "对话与 agent 总对话" },
    { key: "money", name: "记账", desc: "账本、分类与 AI 记账" },
    { key: "papers", name: "论文", desc: "论文库、阅读器与推送订阅" },
    { key: "admin", name: "管理", desc: "管理页与权限矩阵" },
  ];
  const ROLES = [
    { key: "admin", name: "管理员", desc: "全部应用与管理权限" },
    { key: "member", name: "成员", desc: "日常应用，无管理权限" },
  ];

  const S = {
    users: [],
    grants: [],
    me: null, // 当前登录身份映射到的账号（userByPrincipal 语义，用于行内标「我」）
    loading: true,
    error: "",
  };

  let el = null;

  /* ---------- 数据 ---------- */
  async function loadAll() {
    S.loading = true;
    S.error = "";
    try {
      const [usersRes, grantsRes] = await Promise.all([
        req("/api/admin/users"),
        req("/api/admin/grants"),
      ]);
      S.users = usersRes.users ?? [];
      S.grants = grantsRes.grants ?? [];
      const st = LC.getState();
      S.me = st.user?.username ?? null;
    } catch (err) {
      S.error = err.message ?? "加载失败";
    }
    S.loading = false;
    paint();
  }

  const grantOf = (app, role) =>
    S.grants.find((g) => g.app === app && g.role === role)?.allowed === true;

  /* ---------- 渲染 ---------- */
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("zh-CN");
  }

  function usersTable() {
    if (!S.users.length) return `<div class="empty-hint">还没有账号，点右上角「添加用户」创建第一个。</div>`;
    const rows = S.users.map((u) => {
      const isMe = S.me === u.username;
      const roleBadge = u.role === "admin"
        ? `<span class="badge badge-role-admin">管理员</span>`
        : `<span class="badge badge-role-member">成员</span>`;
      const statusBadge = u.enabled
        ? `<span class="badge badge-on">启用</span>`
        : `<span class="badge badge-off">停用</span>`;
      const toggleBtn = u.enabled
        ? `<button class="row-act danger" data-disable="${u.id}" data-name="${esc(u.displayName)}">停用</button>`
        : `<button class="row-act" data-enable="${u.id}">启用</button>`;
      return `<tr>
        <td><b>${esc(u.username)}</b>${isMe ? `<span class="tag soon me-tag">我</span>` : ""}</td>
        <td>${esc(u.displayName)}</td>
        <td>${roleBadge}</td>
        <td>${statusBadge}</td>
        <td class="tbl-dim">${fmtDate(u.createdAt)}</td>
        <td><div class="row-acts">
          <button class="row-act" data-edit-role="${u.id}">改角色</button>
          ${toggleBtn}
          <button class="row-act" data-reset-pw="${u.id}" data-name="${esc(u.username)}">重置密码</button>
        </div></td>
      </tr>`;
    }).join("");
    return `<table class="tbl">
      <thead><tr>
        <th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>创建日期</th><th>操作</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function grantsMatrix() {
    const head = `<tr><th>应用</th>${ROLES.map((r) => `<th>${r.name}</th>`).join("")}</tr>`;
    const body = APPS.map((app) => {
      const cells = ROLES.map((role) => {
        const locked = app.key === "admin" && role.key === "admin";
        const on = grantOf(app.key, role.key);
        const title = locked
          ? "管理员入口不能对管理员关闭"
          : `${role.name}${on ? "可用" : "不可用"}「${app.name}」`;
        return `<td>
          <input type="checkbox" class="grant-chk${locked ? " grant-lock" : ""}"
            data-grant-app="${app.key}" data-grant-role="${role.key}"
            ${on ? "checked" : ""} ${locked ? "disabled" : ""} title="${title}">
        </td>`;
      }).join("");
      return `<tr>
        <td><b>${app.name}</b><span class="tbl-dim"> · ${app.desc}</span></td>
        ${cells}
      </tr>`;
    }).join("");
    return `<table class="tbl grant-tbl">
      <thead>${head}</thead>
      <tbody>${body}</tbody>
    </table>
    <p class="tbl-dim matrix-hint">勾选即生效；「管理 × 管理员」格锁定，防止把管理员入口对所有管理员关闭。</p>`;
  }

  function paint() {
    if (!el) return;
    const box = el.querySelector(".admin-body");
    if (!box) return;
    if (S.loading) {
      box.innerHTML = `<div class="empty-hint">加载中…</div>`;
      return;
    }
    if (S.error) {
      box.innerHTML = `<div class="empty-hint">加载失败：${esc(S.error)}</div>`;
      return;
    }
    box.innerHTML = `
      <div class="card">
        <div class="card-title card-title-gap">用户与角色
          <span class="tbl-dim card-sub">参考 Supabase Auth Users</span>
        </div>
        ${usersTable()}
      </div>
      <div class="card card-gap">
        <div class="card-title card-title-gap">角色权限矩阵
          <span class="tbl-dim card-sub">参考 thefrontkit 团队设置</span>
        </div>
        ${grantsMatrix()}
      </div>`;
  }

  /* ---------- 弹窗表单 ---------- */
  function field(id, label, type = "text", extra = "") {
    return `<label class="login-field" for="${id}">
      <span class="login-label">${label}</span>
      <input class="text-input" id="${id}" type="${type}" autocomplete="off" ${extra}>
    </label>`;
  }

  function roleOptions(current) {
    return ROLES.map((r) =>
      `<option value="${r.key}" ${r.key === current ? "selected" : ""}>${r.name} — ${r.desc}</option>`
    ).join("");
  }

  function addUserModal() {
    openModal("添加用户", `
      ${field("auName", "用户名（2-32 位小写字母/数字/下划线）")}
      ${field("auDisp", "显示名（可选）")}
      ${field("auPass", "密码（至少 8 位）", "password", 'autocomplete="new-password"')}
      <label class="login-field" for="auRole">
        <span class="login-label">角色</span>
        <select class="text-input" id="auRole">${roleOptions("member")}</select>
      </label>
      <div class="form-msg" id="auMsg"></div>`,
      `<button class="btn btn-ghost" data-close>取消</button>
       <button class="btn btn-primary" data-au-submit>创建</button>`);
  }

  function editRoleModal(user) {
    openModal(`改角色 · ${user.displayName}`, `
      <p class="p-note">把 <b>${esc(user.username)}</b> 的角色从
        「${user.role === "admin" ? "管理员" : "成员"}」改为：</p>
      <label class="login-field" for="erRole">
        <span class="login-label">新角色</span>
        <select class="text-input" id="erRole">${roleOptions(user.role)}</select>
      </label>
      <div class="form-msg" id="erMsg"></div>`,
      `<button class="btn btn-ghost" data-close>取消</button>
       <button class="btn btn-primary" data-er-submit data-uid="${user.id}">保存</button>`);
  }

  function resetPwModal(user) {
    openModal(`重置密码 · ${user.username}`, `
      <p class="p-note">设置新密码（至少 8 位）。已登录的会话不受影响，仅影响下次密码登录。</p>
      ${field("rpPass", "新密码", "password", 'autocomplete="new-password"')}
      <div class="form-msg" id="rpMsg"></div>`,
      `<button class="btn btn-ghost" data-close>取消</button>
       <button class="btn btn-primary" data-rp-submit data-uid="${user.id}">重置</button>`);
  }

  function toggleConfirmModal(user, enable) {
    openModal(`${enable ? "启用" : "停用"} · ${user.displayName}`, `
      <p class="p-note p-note-plain">${enable
        ? `启用后 <b>${esc(user.username)}</b> 可以正常登录。`
        : `停用后 <b>${esc(user.username)}</b> 将无法登录（已发的会话保留，但角色接口按 users 表判定）。`}</p>
      <div class="form-msg" id="tgMsg"></div>`,
      `<button class="btn btn-ghost" data-close>取消</button>
       <button class="btn ${enable ? "btn-primary" : "btn-danger"}" data-tg-submit data-uid="${user.id}"
         data-enabled="${enable ? "1" : "0"}">${enable ? "启用" : "确认停用"}</button>`);
  }

  /* ---------- 操作 ---------- */
  const setMsg = (id, text, ok) => {
    const m = document.getElementById(id);
    if (!m) return;
    m.textContent = text;
    m.className = `form-msg ${ok ? "ok" : "err"}`;
  };
  const userOf = (id) => S.users.find((u) => u.id === Number(id));

  async function patchUser(id, patch, msgId, okText) {
    try {
      const res = await req(`/api/admin/users/${id}/${patch.__op}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch.body),
      });
      const updated = res.user;
      if (updated) {
        const i = S.users.findIndex((u) => u.id === updated.id);
        if (i >= 0) S.users[i] = updated;
      }
      setMsg(msgId, okText, true);
      setTimeout(() => { closeModal(); loadAll(); }, 450);
    } catch (err) {
      setMsg(msgId, err.message, false);
    }
  }

  /* ---------- 事件委托 ---------- */
  function onClick(e) {
    if (!el || !el.contains(e.target)) return;

    if (e.target.closest("[data-add-user]")) { addUserModal(); return; }

    const er = e.target.closest("[data-edit-role]");
    if (er) { const u = userOf(er.dataset.editRole); if (u) editRoleModal(u); return; }

    const rp = e.target.closest("[data-reset-pw]");
    if (rp) { const u = userOf(rp.dataset.resetPw); if (u) resetPwModal(u); return; }

    const dis = e.target.closest("[data-disable]");
    if (dis) { const u = userOf(dis.dataset.disable); if (u) toggleConfirmModal(u, false); return; }

    const en = e.target.closest("[data-enable]");
    if (en) { const u = userOf(en.dataset.enable); if (u) toggleConfirmModal(u, true); return; }

    // 添加用户提交
    if (e.target.closest("[data-au-submit]")) {
      const payload = {
        username: document.getElementById("auName")?.value.trim() ?? "",
        displayName: document.getElementById("auDisp")?.value.trim() ?? "",
        password: document.getElementById("auPass")?.value ?? "",
        role: document.getElementById("auRole")?.value ?? "member",
      };
      req("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(() => {
        setMsg("auMsg", "已创建", true);
        setTimeout(() => { closeModal(); loadAll(); }, 450);
      }).catch((err) => setMsg("auMsg", err.message, false));
      return;
    }

    // 改角色提交
    if (e.target.closest("[data-er-submit]")) {
      const btn = e.target.closest("[data-er-submit]");
      const role = document.getElementById("erRole")?.value ?? "";
      patchUser(btn.dataset.uid, { __op: "role", body: { role } }, "erMsg", "已保存");
      return;
    }

    // 重置密码提交
    if (e.target.closest("[data-rp-submit]")) {
      const btn = e.target.closest("[data-rp-submit]");
      const password = document.getElementById("rpPass")?.value ?? "";
      req(`/api/admin/users/${btn.dataset.uid}/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      }).then(() => {
        setMsg("rpMsg", "已重置", true);
        setTimeout(closeModal, 450);
      }).catch((err) => setMsg("rpMsg", err.message, false));
      return;
    }

    // 停用/启用提交
    if (e.target.closest("[data-tg-submit]")) {
      const btn = e.target.closest("[data-tg-submit]");
      const enabled = btn.dataset.enabled === "1";
      patchUser(btn.dataset.uid, { __op: "enabled", body: { enabled } }, "tgMsg",
        enabled ? "已启用" : "已停用");
      return;
    }
  }

  async function onChange(e) {
    const chk = e.target.closest?.("[data-grant-app]");
    if (!chk || !el?.contains(chk) || chk.disabled) return;
    const payload = {
      app: chk.dataset.grantApp,
      role: chk.dataset.grantRole,
      allowed: chk.checked,
    };
    chk.disabled = true; // 提交期间防连点
    try {
      const res = await req("/api/admin/grants", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      S.grants = res.grants ?? S.grants;
      setMsg("grantMsg", "", true);
      paint();
    } catch (err) {
      chk.checked = !chk.checked; // 失败回滚勾选
      chk.disabled = false;
      setMsg("grantMsg", err.message, false);
    }
  }

  /* ---------- 视图结构 ---------- */
  function mount(container) {
    el = container;
    el.innerHTML = `
      <main class="stage">
        <div class="stage-head">
          <h1 class="stage-title">管理设置</h1>
          <p class="stage-sub">用户与角色、角色权限矩阵——批 4 权限体系落地页。</p>
        </div>
        <div class="admin-toolbar">
          <button class="btn btn-primary" data-add-user>${IC.check} 添加用户</button>
          <button class="btn btn-ghost" data-refresh>刷新</button>
          <span class="form-msg" id="grantMsg"></span>
        </div>
        <div class="admin-body"></div>
      </main>`;
    el.addEventListener("click", onClick);
    el.addEventListener("change", onChange);
    el.querySelector("[data-refresh]")?.addEventListener("click", loadAll);
    loadAll();
  }

  function cleanup() {
    if (el) {
      el.removeEventListener("click", onClick);
      el.removeEventListener("change", onChange);
    }
    el = null;
  }

  window.LC.views = Object.assign(window.LC.views || {}, { admin: { mount, cleanup } });
})();
