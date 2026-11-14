// 流光咖啡馆 · 页面外壳 JS（0C）
// 单页应用 hash 路由；事件一律委托（视图会重渲染）；弹窗走原生 dialog 基建
// 视图注册表：chat.js 等子页面模块挂到 window.LC.views，路由命中时由这里挂载
"use strict";

window.LC = window.LC || {};

const $app = document.getElementById("app");
const $modal = document.getElementById("modal");

const state = {
  principal: null,        // 登录身份（chord principal，如 { kind: "owner" }）
  user: null,             // 自有账号（/api/session 返回，{ username, displayName, role }；无则 null）
  bootstrapNeeded: false, // owner 引导：users 表为空，需要创建首个管理员
  pong: "wait",           // 探针状态：wait / on / off
  route: "home",
};

/* ---------- 图标（内联 SVG，data-ic 注入风格，与原型一致） ---------- */
const svg = (body, size = 20) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

const IC = {
  logo: svg('<path d="M12 3c-1.8 0-3 1.4-3 3 0 .5.1 1 .3 1.4C7.9 8.4 7 10.1 7 12v6a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-6c0-1.9-.9-3.6-2.3-4.6.2-.4.3-.9.3-1.4 0-1.6-1.2-3-3-3Z"/><path d="M9 18h6"/>', 16),
  home: svg('<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>', 18),
  menu: svg('<path d="M4 7h16M4 12h16M4 17h16"/>', 18),
  chat: svg('<path d="M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z"/>'),
  wallet: svg('<rect x="3" y="6" width="18" height="13" rx="3"/><path d="M16 12.5h.01M3 9h18"/>'),
  book: svg('<path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2Zm0 0a2 2 0 0 0 2 2h13"/>'),
  user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>'),
  sliders: svg('<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.4"/><circle cx="10" cy="17" r="2.4"/>'),
  shield: svg('<path d="M12 3 5 6v5c0 5 3 8.4 7 10 4-1.6 7-5 7-10V6l-7-3Z"/><path d="m9.5 12 1.8 1.8 3.4-3.6"/>'),
  grid: svg('<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>'),
  activity: svg('<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
  arrow: svg('<path d="m9 6 6 6-6 6"/>', 18),
  close: svg('<path d="M6 6l12 12M18 6 6 18"/>', 16),
  check: svg('<path d="m5 12 5 5L20 7"/>', 16),
};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- API ---------- */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { Accept: "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
  return res.json();
}

/* ---------- 弹窗基建（原生 dialog；Esc/焦点陷阱/背景禁交互走原生） ---------- */
function openModal(title, bodyHtml, footHtml = "") {
  $modal.innerHTML = `
    <div class="modal-head">
      <h2 class="modal-title">${esc(title)}</h2>
      <button class="modal-close" data-close aria-label="关闭">${IC.close}</button>
    </div>
    <div class="modal-body">${bodyHtml}</div>
    ${footHtml ? `<div class="modal-foot">${footHtml}</div>` : ""}`;
  if (typeof $modal.showModal === "function") $modal.showModal();
  else $modal.setAttribute("open", "");
}
function closeModal() {
  if (typeof $modal.close === "function" && $modal.open) $modal.close();
  else $modal.removeAttribute("open");
}
$modal.addEventListener("click", (e) => { if (e.target === $modal) closeModal(); }); // 遮罩点击

/* ---------- 视图 ---------- */
const APPS = [
  { key: "chat", icon: IC.chat, name: "对话", desc: "通用聊天：会话、流式回答、停止与重新生成。", href: "#/chat", live: true },
  { key: "money", icon: IC.wallet, name: "记账", desc: "对话记一笔、月度统计，表单与 AI 一条写路径。", href: "#/money", live: true },
  { key: "papers", icon: IC.book, name: "论文", desc: "下载解析、批注笔记、单篇问答带出处。", href: "#/papers", live: true },
];

const ROUTE_TITLES = { home: "工作台", chat: "对话", money: "记账", papers: "论文", reader: "阅读", me: "我的", admin: "管理设置" };
// 身份显示优先用自有账号显示名（有 user 时）；其次 chord principal
const whoAmI = () =>
  state.user?.displayName
  ?? (state.principal?.kind === "owner" ? "主人" : (state.principal?.name ?? "成员"));
// 身份角标：自有账号角色优先，兜底按 principal 判断
const roleLabel = () => {
  if (state.user) return state.user.role === "admin" ? "管理员" : "成员";
  return state.principal?.kind === "owner" ? "管理员" : "成员";
};

/* 石墨灰侧栏（桌面常驻；窄屏变抽屉，项目规矩允许的导航抽屉） */
function sideNav() {
  const isOwner = state.principal?.kind === "owner";
  const item = (r, name, href, icon) =>
    `<a class="side-item ${state.route === r ? "active" : ""}" href="${href}">${icon}<span>${name}</span></a>`;
  return `
  <aside class="side-nav" id="sideNav">
    <div class="side-brand">
      <span class="brand-dot">${IC.logo}</span>
      <span><div class="t">流光咖啡馆</div><div class="s">Lumen Cafe</div></span>
    </div>
    <div class="side-group">
      <div class="side-gt">首页</div>
      ${item("home", "工作台", "#/", IC.home)}
    </div>
    <div class="side-group">
      <div class="side-gt">应用</div>
      ${item("chat", "对话", "#/chat", IC.chat)}
      ${item("money", "记账", "#/money", IC.wallet)}
      ${item("papers", "论文", "#/papers", IC.book)}
    </div>
    <div class="side-group">
      <div class="side-gt">管理</div>
      ${item("me", "我的", "#/me", IC.user)}
      ${isOwner ? item("admin", "管理设置", "#/admin", IC.shield) : ""}
    </div>
    <div class="side-foot">
      <span class="avatar">${esc(whoAmI().slice(0, 1))}</span>
      <span class="who"><b>${esc(whoAmI())}</b><span>${esc(roleLabel())}</span></span>
    </div>
  </aside>
  <div class="side-backdrop" id="sideBackdrop"></div>`;
}

function topbar(routeName) {
  return `
  <header class="topbar">
    <button class="icon-btn menu-btn" data-side-toggle aria-label="菜单">${IC.menu}</button>
    <span class="page-title">${routeName}</span>
    <div class="topbar-side">
      ${statusDot()}
      <a class="user-chip" href="#/me" title="账号与设置"><span class="avatar">${IC.user}</span><span>${esc(whoAmI())}</span></a>
    </div>
  </header>`;
}

/* 外壳 = 侧栏 + 主列（顶栏 + 内容） */
function shell(contentHtml) {
  return `<div class="app-shell">${sideNav()}<div class="shell-col">${topbar(ROUTE_TITLES[state.route] ?? "")}${contentHtml}</div></div>`;
}

function closeSide() {
  document.getElementById("sideNav")?.classList.remove("open");
  document.getElementById("sideBackdrop")?.classList.remove("show");
}

function statusDot() {
  const cls = state.pong === "on" ? "on" : state.pong === "off" ? "off" : "wait";
  const text = state.pong === "on" ? "服务正常" : state.pong === "off" ? "连接异常" : "连接中";
  return `<span class="status-pill" title="探针 /api/ping"><span class="status-dot ${cls}"></span><span class="status-text">${text}</span></span>`;
}

function homeView() {
  const now = new Date();
  const h = now.getHours();
  const greet = h < 6 ? "夜深了" : h < 12 ? "早上好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
  const dateStr = now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  return `
  <main class="stage">
    <div class="welcome-bar">
      <div>
        <div class="welcome-hello">${greet}，${esc(whoAmI())}</div>
        <div class="welcome-sub">${dateStr} · 对话、记账、论文三个应用都在线</div>
      </div>
      <div class="welcome-acts">
        <a class="btn btn-ghost btn-ghost-w" href="#/money">记一笔</a>
        <a class="btn btn-primary" href="#/chat">开始对话</a>
      </div>
    </div>
    <div class="stage-head">
      <h1 class="stage-title">工作台</h1>
      <p class="stage-sub">三个应用会陆续在这里亮起来。</p>
    </div>
    <div class="card-grid">
      ${APPS.map((a) => a.live ? `
      <a class="card" href="${a.href}">
        <div class="card-icon">${a.icon}</div>
        <div class="card-title">${a.name}</div>
        <div class="card-desc">${a.desc}</div>
        <div class="card-foot"><span class="tag soon">已上线</span><span class="card-link">进入</span></div>
      </a>` : `
      <article class="card card-disabled">
        <div class="card-icon">${a.icon}</div>
        <div class="card-title">${a.name}<span class="tag soon">即将上线</span></div>
        <div class="card-desc">${a.desc}</div>
        <div class="card-foot"><span class="tag">第 2 批</span><span class="card-link card-link-hidden">进入</span></div>
      </article>`).join("")}
      <article class="card">
        <div class="card-icon">${IC.activity}</div>
        <div class="card-title">系统状态</div>
        <div class="kv-row"><span class="kv-k">探针 /api/ping</span><span class="kv-v">${state.pong === "on" ? "pong ✓" : state.pong === "off" ? "无响应" : "检测中…"}</span></div>
        <div class="kv-row"><span class="kv-k">登录身份</span><span class="kv-v">${esc(JSON.stringify(state.principal))}</span></div>
        <div class="card-foot"><span class="tag">0A/0B 验收探针</span><span></span></div>
      </article>
    </div>
  </main>`;
}

const DOMAINS = [
  { key: "general", icon: IC.user, name: "通用设置", desc: "账号与登录（批 1 起为账号密码）" },
  { key: "apps", icon: IC.sliders, name: "应用设置", desc: "各应用偏好，随应用批次开放" },
  { key: "admin", icon: IC.shield, name: "管理设置", desc: "模型、用户、费用统计（管理页）", admin: true },
];

/* 「我的」通用设置面板：owner 引导建首个管理员 + 自助改密（批 1 账号登录） */
const bootstrapBlock = () => `
  <div class="boot-banner">
    <div class="boot-banner-t">创建首个管理员</div>
    <div class="boot-banner-d">系统还没有任何账号。请创建一个管理员账号；创建成功后请退出当前主人会话，用新账号登录。</div>
    <label class="login-field" for="bsUser"><span class="login-label">用户名</span><input class="text-input" id="bsUser" autocomplete="off"></label>
    <label class="login-field" for="bsName"><span class="login-label">显示名（可选）</span><input class="text-input" id="bsName" autocomplete="off"></label>
    <label class="login-field" for="bsPass"><span class="login-label">密码（至少 8 位）</span><input class="text-input" type="password" id="bsPass" autocomplete="new-password"></label>
    <div class="me-sec-acts">
      <button class="btn btn-primary" data-bootstrap-submit>创建</button>
      <span class="form-msg" id="bsMsg"></span>
    </div>
  </div>`;

const passBlock = () => `
  <div class="me-sec">
    <div class="me-sec-t">修改密码</div>
    <label class="login-field" for="pwOld"><span class="login-label">旧密码</span><input class="text-input" type="password" id="pwOld" autocomplete="current-password"></label>
    <label class="login-field" for="pwNew"><span class="login-label">新密码</span><input class="text-input" type="password" id="pwNew" autocomplete="new-password"></label>
    <label class="login-field" for="pwNew2"><span class="login-label">确认新密码</span><input class="text-input" type="password" id="pwNew2" autocomplete="new-password"></label>
    <div class="me-sec-acts">
      <button class="btn btn-primary" data-pass-submit>提交</button>
      <span class="form-msg" id="pwMsg"></span>
    </div>
  </div>`;

/* POST JSON 便捷封装（api() 只认 2xx，错误信息按状态码映射） */
async function postJson(path, payload, messages = {}) {
  try {
    return await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    const msg = messages[err.status] ?? messages.default ?? `请求失败（HTTP ${err.status}）`;
    throw Object.assign(new Error(msg), { status: err.status });
  }
}

function meView() {
  const isOwner = state.principal?.kind === "owner";
  return `
  <main class="stage">
    <div class="stage-head">
      <h1 class="stage-title">我的</h1>
      <p class="stage-sub">设置分三个域，和 macOS 系统设置一个思路。</p>
    </div>
    <div class="domain-list">
      ${DOMAINS.filter((d) => !d.admin || isOwner).map((d) => `
      <button class="domain-item" data-domain="${d.key}">
        <span class="card-icon">${d.icon}</span>
        <span class="domain-text">
          <span class="domain-name">${d.name}</span>
          <span class="domain-desc">${d.desc}</span>
        </span>
        <span class="domain-arrow">${IC.arrow}</span>
      </button>`).join("")}
    </div>
    ${!isOwner ? `<p class="me-note">管理设置仅主人可见；成员访问受保护接口一律 401（chord 默认拒绝）。</p>` : ""}
  </main>`;
}

function adminView() {
  if (state.principal?.kind !== "owner") return meView(); // 成员看不到入口，防御性兜底
  return `
  <main class="stage">
    <div class="stage-head">
      <h1 class="stage-title">管理设置</h1>
      <p class="stage-sub">模型管理、用户与角色、调用统计——第 1 批随对话应用开放。</p>
    </div>
    <div class="empty-hint">这里会是管理后台。现在还是空壳，等第 1 批来填。</div>
  </main>`;
}

let mountedView = null; // 当前挂载的子页面模块（chat 等），切走时清理

function render() {
  const hash = location.hash || "#/";
  const route = hash.startsWith("#/me") ? "me" : hash.startsWith("#/admin") ? "admin"
    : hash.startsWith("#/papers/") ? "reader" : hash.startsWith("#/papers") ? "papers"
    : hash.startsWith("#/chat") ? "chat" : hash.startsWith("#/money") ? "money" : "home";
  const sub = window.LC.views?.[route];

  if (route === state.route && mountedView === sub && sub) return; // 子页面自管内部渲染
  if (mountedView?.cleanup) mountedView.cleanup();
  mountedView = null;
  state.route = route;

  if (sub) {
    $app.innerHTML = shell('<div id="view" class="view-host"></div>');
    sub.mount(document.getElementById("view"), { hash, state });
    mountedView = sub;
    document.title = `流光咖啡馆 · ${{ chat: "对话", money: "记账", papers: "论文", reader: "阅读" }[route] ?? ""}`;
    return;
  }

  const view = state.route === "me" ? meView() : state.route === "admin" ? adminView() : homeView();
  $app.innerHTML = shell(view);
  document.title = `流光咖啡馆 · ${state.route === "me" ? "我的" : state.route === "admin" ? "管理" : "工作台"}`;
}

/* ---------- 事件委托 ---------- */
document.addEventListener("click", (e) => {
  const closeBtn = e.target.closest("[data-close]");
  if (closeBtn) { closeModal(); return; }

  // 窄屏导航抽屉：开关、遮罩、点链接后收起
  if (e.target.closest("[data-side-toggle]")) {
    document.getElementById("sideNav")?.classList.toggle("open");
    document.getElementById("sideBackdrop")?.classList.toggle("show");
    return;
  }
  if (e.target.closest("#sideBackdrop")) { closeSide(); return; }
  if (e.target.closest(".side-nav a.side-item")) closeSide();

  // 通用设置 · 修改密码（批 1）
  if (e.target.closest("[data-pass-submit]")) {
    e.preventDefault();
    const msg = document.getElementById("pwMsg");
    const setMsg = (text, ok) => {
      msg.textContent = text;
      msg.className = `form-msg ${ok ? "ok" : "err"}`;
    };
    const oldPassword = document.getElementById("pwOld")?.value ?? "";
    const pw1 = document.getElementById("pwNew")?.value ?? "";
    const pw2 = document.getElementById("pwNew2")?.value ?? "";
    if (pw1.length < 8) { setMsg("新密码至少 8 位", false); return; }
    if (pw1 !== pw2) { setMsg("两次输入的新密码不一致", false); return; }
    postJson("/api/auth/password", { oldPassword, newPassword: pw1 }, {
      401: "旧密码错误",
      403: "该登录方式无密码",
      400: "新密码至少 8 位",
      default: "修改失败，请稍后重试",
    }).then(() => {
      setMsg("已更新，下次登录请用新密码", true);
      document.getElementById("pwOld").value = "";
      document.getElementById("pwNew").value = "";
      document.getElementById("pwNew2").value = "";
    }).catch((err) => setMsg(err.message, false));
    return;
  }

  // 通用设置 · owner 引导创建首个管理员（批 1）
  if (e.target.closest("[data-bootstrap-submit]")) {
    e.preventDefault();
    const msg = document.getElementById("bsMsg");
    const setMsg = (text, ok) => {
      msg.textContent = text;
      msg.className = `form-msg ${ok ? "ok" : "err"}`;
    };
    const username = document.getElementById("bsUser")?.value.trim() ?? "";
    const displayName = document.getElementById("bsName")?.value.trim() ?? "";
    const password = document.getElementById("bsPass")?.value ?? "";
    postJson("/api/auth/bootstrap", { username, displayName, password }, {
      400: "用户名需为 2-32 位小写字母、数字或下划线，密码至少 8 位",
      403: "仅主人可用",
      409: "首个管理员已创建",
      default: "创建失败，请稍后重试",
    }).then(() => {
      state.bootstrapNeeded = false;
      setMsg("已创建，请退出后用新账号登录", true);
    }).catch((err) => setMsg(err.message, false));
    return;
  }

  const domain = e.target.closest("[data-domain]");
  if (domain) {
    const key = domain.dataset.domain;
    if (key === "admin") { location.hash = "#/admin"; return; }
    const isOwner = state.principal?.kind === "owner";
    const bodies = {
      general: `
        ${state.bootstrapNeeded ? bootstrapBlock() : ""}
        <div class="kv-row"><span class="kv-k">当前身份</span><span class="kv-v">${esc(whoAmI())}（${esc(roleLabel())}）</span></div>
        <div class="kv-row"><span class="kv-k">登录方式</span><span class="kv-v">账号密码（chord 会话 cookie）</span></div>
        ${state.user ? passBlock() : `<p class="me-note">当前身份无密码（chord 主人/邀请会话）。</p>`}`,
      apps: `<p>应用偏好设置会按批次加入：对话、记账、论文各管各的。</p>`,
      admin: isOwner ? `<p>管理后台骨架在 <a href="#/admin">#/admin</a>。</p>` : `<p>仅主人可用。</p>`,
    };
    openModal(domain.querySelector(".domain-name").textContent, bodies[key] ?? "<p>占位</p>",
      `<button class="btn btn-ghost" data-close>关闭</button>`);
  }
});

window.addEventListener("hashchange", render);

// 供子页面模块（chat.js 等）使用的共享件
Object.assign(window.LC, { api, openModal, closeModal, esc, IC, getState: () => state });

/* ---------- 启动：登录态检测 → 未登录跳 /login 登录页 ---------- */
(async function boot() {
  try {
    const data = await api("/api/session");
    state.principal = data.principal;
    state.user = data.user ?? null;
  } catch (err) {
    if (err.status === 401) {
      location.replace("/login"); // 批 1 自有登录页（取代 chord /_chord/owner 链接登录）
      return;
    }
    $app.querySelector(".boot-hint").innerHTML =
      `<span class="boot-error">连不上服务，请确认主程序已启动。</span>`;
    return;
  }
  // owner 引导：users 表为空 → 通用设置面板顶部提示创建首个管理员
  if (state.principal?.kind === "owner") {
    try {
      const bs = await api("/api/auth/bootstrap");
      state.bootstrapNeeded = bs.needed === true;
    } catch {
      state.bootstrapNeeded = false;
    }
  }
  render();
  // 后台探活
  (async () => {
    try { await api("/api/ping"); state.pong = "on"; }
    catch { state.pong = "off"; }
    if (state.route) render();
  })();
})();
