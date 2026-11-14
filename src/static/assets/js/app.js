// 流光咖啡馆 · 页面外壳 JS（0C）
// 单页应用 hash 路由；事件一律委托（视图会重渲染）；弹窗走原生 dialog 基建
// 视图注册表：chat.js 等子页面模块挂到 window.LC.views，路由命中时由这里挂载
"use strict";

window.LC = window.LC || {};

const $app = document.getElementById("app");
const $modal = document.getElementById("modal");

const state = {
  principal: null, // 登录身份（chord principal，如 { kind: "owner" }）
  pong: "wait",    // 探针状态：wait / on / off
  route: "home",
};

/* ---------- 图标（内联 SVG，data-ic 注入风格，与原型一致） ---------- */
const svg = (body, size = 20) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

const IC = {
  logo: svg('<path d="M12 3c-1.8 0-3 1.4-3 3 0 .5.1 1 .3 1.4C7.9 8.4 7 10.1 7 12v6a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-6c0-1.9-.9-3.6-2.3-4.6.2-.4.3-.9.3-1.4 0-1.6-1.2-3-3-3Z"/><path d="M9 18h6"/>', 16),
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
  { key: "money", icon: IC.wallet, name: "记账", desc: "对话记一笔、月度统计，第二批开放。" },
  { key: "papers", icon: IC.book, name: "论文", desc: "订阅推送、下载解析、笔记问答，第二批开放。" },
];

function statusDot() {
  const cls = state.pong === "on" ? "on" : state.pong === "off" ? "off" : "wait";
  const text = state.pong === "on" ? "服务正常" : state.pong === "off" ? "连接异常" : "连接中";
  return `<span class="status-pill" title="探针 /api/ping"><span class="status-dot ${cls}"></span><span class="status-text">${text}</span></span>`;
}

function topbar() {
  const nav = [
    ["home", "工作台", "#/"],
    ["chat", "对话", "#/chat"],
    ["me", "我的", "#/me"],
  ];
  const who = state.principal?.kind === "owner" ? "主人" : (state.principal?.name ?? "成员");
  return `
  <header class="topbar">
    <div class="brand"><span class="brand-dot">${IC.logo}</span><span>流光咖啡馆</span></div>
    <nav class="nav">
      ${nav.map(([r, name, href]) => `<a class="nav-btn ${state.route === r ? "active" : ""}" href="${href}">${name}</a>`).join("")}
    </nav>
    <div class="topbar-side">
      ${statusDot()}
      <a class="user-chip" href="#/me" title="账号与设置"><span class="avatar">${IC.user}</span><span>${esc(who)}</span></a>
    </div>
  </header>`;
}

function homeView() {
  return `
  <main class="stage">
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
  { key: "general", icon: IC.user, name: "通用设置", desc: "账号与登录（chord 身份地基）" },
  { key: "apps", icon: IC.sliders, name: "应用设置", desc: "各应用偏好，随应用批次开放" },
  { key: "admin", icon: IC.shield, name: "管理设置", desc: "模型、用户、费用统计（管理页）", admin: true },
];

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
  const route = hash.startsWith("#/me") ? "me" : hash.startsWith("#/admin") ? "admin" : hash.startsWith("#/chat") ? "chat" : "home";
  const sub = window.LC.views?.[route];

  if (route === state.route && mountedView === sub && sub) return; // 子页面自管内部渲染
  if (mountedView?.cleanup) mountedView.cleanup();
  mountedView = null;
  state.route = route;

  if (sub) {
    $app.innerHTML = topbar() + '<div id="view" class="view-host"></div>';
    sub.mount(document.getElementById("view"), { hash, state });
    mountedView = sub;
    document.title = "流光咖啡馆 · 对话";
    return;
  }

  const view = state.route === "me" ? meView() : state.route === "admin" ? adminView() : homeView();
  $app.innerHTML = topbar() + view;
  document.title = `流光咖啡馆 · ${state.route === "me" ? "我的" : state.route === "admin" ? "管理" : "工作台"}`;
}

/* ---------- 事件委托 ---------- */
document.addEventListener("click", (e) => {
  const closeBtn = e.target.closest("[data-close]");
  if (closeBtn) { closeModal(); return; }

  const domain = e.target.closest("[data-domain]");
  if (domain) {
    const key = domain.dataset.domain;
    if (key === "admin") { location.hash = "#/admin"; return; }
    const isOwner = state.principal?.kind === "owner";
    const bodies = {
      general: `
        <div class="kv-row"><span class="kv-k">当前身份</span><span class="kv-v">${esc(JSON.stringify(state.principal))}</span></div>
        <div class="kv-row"><span class="kv-k">登录方式</span><span class="kv-v">chord 会话（cookie）</span></div>
        <p style="margin:12px 0 0;font-size:13px">成员账号、邀请链接随第 1 批「用户插件」开放。</p>`,
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

/* ---------- 启动：登录态检测 → 未登录跳 chord 登录页 ---------- */
(async function boot() {
  try {
    const data = await api("/api/session");
    state.principal = data.principal;
  } catch (err) {
    if (err.status === 401) {
      location.replace("/_chord/owner"); // chord 自带登录页（token 贴入框）
      return;
    }
    $app.querySelector(".boot-hint").innerHTML =
      `<span class="boot-error">连不上服务，请确认主程序已启动。</span>`;
    return;
  }
  render();
  // 后台探活
  (async () => {
    try { await api("/api/ping"); state.pong = "on"; }
    catch { state.pong = "off"; }
    if (state.route) render();
  })();
})();
