/* 流光咖啡馆 v2 · SPA 运行时
 * 参考：midday（外壳+⌘K）、gethomepage（玻璃 Bento）、Homarr（卡片即入口）、
 *       Open WebUI（多板块单外壳）、macOS 系统设置（子应用统一骨架）
 * 联调状态：全部页面已接真实 API（assets/js/api.js → localhost:8000）；
 *          data.js 仅保留为字体/演示常量来源，页面数据一律来自后端。
 */
(function () {
  "use strict";

  var D = window.LC_DATA || {};
  var API = window.LC_API;

  /* ================= 登录态 ================= */
  var LC_USER = null; /* GET /auth/me 缓存 {id, username, nickname, roles, permissions} */

  function isLoggedIn() { return !!API.getToken(); }

  /* 未登录访问业务路由 → 跳登录；已登录访问登录页 → 回工作台 */
  function authGuard(route) {
    if (route !== "login" && !isLoggedIn()) {
      location.replace("#/login");
      return false;
    }
    if (route === "login" && isLoggedIn()) {
      location.replace("#/workspace");
      return false;
    }
    return true;
  }

  /* ================= 工具 ================= */
  function fen(f) {
    var sign = f < 0 ? "-" : "";
    var abs = Math.abs(f);
    var yuan = Math.floor(abs / 100);
    var cent = String(abs % 100).padStart(2, "0");
    return sign + "¥" + yuan.toLocaleString("zh-CN") + "." + cent;
  }
  function fenShort(f) { return fen(f).replace(".00", ""); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  /* 本地时区「今天」（YYYY-MM-DD）。勿用 toISOString——那是 UTC，北京时间 0~8 点会落到前一天 */
  function localToday() {
    var d = new Date();
    var mo = d.getMonth() + 1, da = d.getDate();
    return d.getFullYear() + "-" + (mo < 10 ? "0" + mo : mo) + "-" + (da < 10 ? "0" + da : da);
  }
  /* 滑动开关统一态：class + aria-checked 同步（role="switch" 可访问性） */
  function setSwitch(el, on) { el.classList.toggle("on", !!on); el.setAttribute("aria-checked", on ? "true" : "false"); }
  /* IME 组合输入中（拼音选词等）。keydown 的 isComposing 在部分 Safari 不可靠，用 composition 事件兜底 */
  var imeComposing = false;
  document.addEventListener("compositionstart", function () { imeComposing = true; });
  document.addEventListener("compositionend", function () { imeComposing = false; });

  /* ================= 图标（内联 SVG 注入） ================= */
  var P = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
    chat: '<path d="M21 12a8 8 0 0 1-8 8H4l2.2-3.1A8 8 0 1 1 21 12z"/><path d="M8.5 11h.01M12 11h.01M15.5 11h.01"/>',
    money: '<circle cx="12" cy="12" r="9"/><path d="M8.5 8.5 12 12.5l3.5-4"/><path d="M12 12.5V17"/><path d="M9 14h6"/>',
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M19 12a7 7 0 0 0-.14-1.4l2-1.55-2-3.46-2.35.94A7 7 0 0 0 14.1 5.1L13.75 2.6h-3.5L9.9 5.1a7 7 0 0 0-2.41 1.43l-2.35-.94-2 3.46 2 1.55a7 7 0 0 0 0 2.8l-2 1.55 2 3.46 2.35-.94a7 7 0 0 0 2.41 1.43l.35 2.5h3.5l.35-2.5a7 7 0 0 0 2.41-1.43l2.35.94 2-3.46-2-1.55c.1-.45.14-.92.14-1.4z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    send: '<path d="M21 3 10 14"/><path d="M21 3 14 21l-4-7-7-4z"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/><path d="M9 7.5h7"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 14h10l1-14"/><path d="M10 11v6M14 11v6"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    shield: '<path d="M12 2 4.5 5v6c0 5 3.2 8.6 7.5 10 4.3-1.4 7.5-5 7.5-10V5z"/><path d="m9 11.5 2.2 2.2 4.3-4.4"/>',
    plug: '<path d="M9 7V3M15 7V3"/><path d="M7 7h10v4a5 5 0 0 1-10 0z"/><path d="M12 16v5"/>',
    spark: '<path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l2.5 2.5M16.5 16.5 19 19M19 5l-2.5 2.5M7.5 16.5 5 19"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 10h18"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    doc: '<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/><path d="M9 13h7M9 17h7"/>',
    chart: '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M9 16v-5M13 16V8M17 16v-3"/>',
    check: '<path d="m4.5 12.5 5 5 10-11"/>',
    key: '<circle cx="8" cy="15" r="4.5"/><path d="m11.5 11.5 8-8"/><path d="M16 5l3 3M13.5 7.5l3 3"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M17.5 14.4a6.5 6.5 0 0 1 4 5.6"/>',
    grip: '<g fill="currentColor" stroke="none"><circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/></g>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
    clip: '<path d="m21 12.5-8.2 8.2a5 5 0 0 1-7-7L14 5.5a3.5 3.5 0 0 1 5 5l-8 8a2 2 0 0 1-2.9-2.8l7.6-7.6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    token: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M7 8V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/><circle cx="12" cy="14" r="1.6"/>',
    star: '<path d="m12 3.6 2.6 5.4 5.8.7-4.3 4 1.1 5.7L12 16.6l-5.2 2.8 1.1-5.7-4.3-4 5.8-.7z"/>',
    back: '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
    wand: '<path d="m15 4 5 5L7 22l-5-5z"/><path d="M14 3.5 16.5 6M19 8.5 21.5 11M5 3v3M3.5 4.5h3M20 15v3M18.5 16.5h3"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
    dl: '<path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M5 21h14"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
  };
  function injectIcons(root) {
    qsa("[data-ic]", root).forEach(function (el) {
      var name = el.getAttribute("data-ic");
      el.classList.add("ic");
      /* 优先使用 Lucide 图标（LC_ICONS），缺失回退到手写 P 表 */
      var body = (window.LC_ICONS && window.LC_ICONS[name]) || P[name] || P.grid;
      el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
    });
  }

  /* ================= Toast ================= */
  var toastTimer = null;
  function toast(text) {
    /* 防御：FastAPI 422 detail 是数组等非字符串时也要给出可读信息，不显示 [object Object] */
    if (typeof text !== "string") {
      var d = text && text.detail;
      text = typeof d === "string" ? d
        : d ? JSON.stringify(d) : JSON.stringify(text);
    }
    var t = qs("#toast");
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }

  /* ================= 暗色模式（P12 拍板；2026-10-27）
   * 三档：跟随系统 / 浅色 / 深色，存 user_settings.theme.mode（默认跟随系统）。
   * localStorage 仅存最近一次的模式作启动闪现兜底；权威值在用户设置接口。 */
  var THEME_KEY = "lc_theme_mode";
  var themeState = { mode: "system", applied: "light" };
  var darkMedia = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function themeResolved() {
    if (themeState.mode === "dark") return "dark";
    if (themeState.mode === "light") return "light";
    return darkMedia && darkMedia.matches ? "dark" : "light";
  }
  function applyTheme() {
    themeState.applied = themeResolved();
    document.documentElement.setAttribute("data-theme", themeState.applied);
    try { localStorage.setItem(THEME_KEY, themeState.mode); } catch (err) {}
    /* 通用设置弹窗内的主题段同步高亮 */
    qsa("[data-theme-mode]").forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-theme-mode") === themeState.mode);
    });
  }
  /* 系统深浅切换时，仅「跟随系统」档响应 */
  if (darkMedia && darkMedia.addEventListener) {
    darkMedia.addEventListener("change", function () { if (themeState.mode === "system") applyTheme(); });
  }
  /* 启动兜底：localStorage 里上次模式先上，/auth/me 回来后再以 user_settings 为准 */
  (function () {
    try {
      var m = localStorage.getItem(THEME_KEY);
      if (m === "system" || m === "light" || m === "dark") themeState.mode = m;
    } catch (err) {}
    document.documentElement.setAttribute("data-theme", themeResolved());
  })();
  /* 用户设置里的主题档（无记录 = 跟随系统）。
   * /auth/me 的 MeOut 不含 settings 字段：此时不得覆盖启动兜底（localStorage 上次
   * 模式），否则整页刷新后用户选择会被重置回「跟随系统」（步 C 暗色模式的存量 bug，
   * 论文域增强批顺带修复——仅当 user_settings 里确有 theme.mode 时才以其为准。 */
  function loadThemeFromSettings(settings) {
    var m = (((settings || {}).theme) || {}).mode;
    if (m !== "light" && m !== "dark" && m !== "system") return;
    themeState.mode = m;
    applyTheme();
  }

  /* ================= 用户头像（localStorage: lc_avatar） =================
   * 形状约定：{"type":"img","data":"<dataURL>"} 或 {"type":"initial","color":"<hex>"}；
   * 未设置 / 解析失败 → 回退用户名首字 + 灰底（AGENTS.md：用户头像锚定身份、允许自定义） */
  var AVATAR_FALLBACK_BG = "#eef0f3"; /* 历史常量：自定义色合法性校验用；回退展示已改走 var(--bg-soft) */
  function avatarSetting() {
    try {
      var raw = localStorage.getItem("lc_avatar");
      if (!raw) return null;
      var o = JSON.parse(raw);
      if (o && o.type === "img" && typeof o.data === "string" && o.data.indexOf("data:image/") === 0) return o;
      if (o && o.type === "initial" && typeof o.color === "string" && /^#[0-9a-fA-F]{6}$/.test(o.color)) return o;
    } catch (err) {}
    return null;
  }
  function userInitial() {
    var name = LC_USER ? (LC_USER.nickname || LC_USER.username || "") : "";
    name = String(name).trim();
    return name ? name.slice(0, 1) : "?";
  }
  /* 头像内层：img 填充，或色底白字首字（未设置时用主题变量回退，暗色下不突兀） */
  function avatarInnerHtml() {
    var s = avatarSetting();
    if (s && s.type === "img") return '<img class="avatar-img" src="' + esc(s.data) + '" alt="">';
    var custom = !!(s && s.type === "initial" && s.color);
    var color = custom ? s.color : "var(--bg-soft)";
    var fg = custom ? "#ffffff" : "var(--ink-2)";
    return '<span class="avatar-initial" style="background:' + color + ";color:" + fg + ';">' + esc(userInitial()) + "</span>";
  }
  function saveAvatar(obj) {
    try {
      localStorage.setItem("lc_avatar", JSON.stringify(obj));
    } catch (err) {
      toast("头像保存失败：浏览器存储空间不足");
      return;
    }
    applyUserAvatar();
    toast("头像已更新");
  }
  /* 设置弹窗：预览 + 预设色点选中态 */
  function refreshAvatarPanel() {
    var prev = qs("[data-avatar-preview]");
    if (prev) prev.innerHTML = avatarInnerHtml();
    var s = avatarSetting();
    var cur = (s && s.type === "initial" && s.color) ? s.color : null;
    qsa("[data-avatar-color]").forEach(function (d) {
      d.classList.toggle("active", d.getAttribute("data-avatar-color") === cur);
    });
  }
  /* 全局应用：顶栏 / 侧栏 / 已渲染对话消息 / 我的页 / 设置弹窗预览 */
  function applyUserAvatar() {
    var top = qs("#topbar-avatar");
    if (top) top.innerHTML = avatarInnerHtml();
    qsa(".sider-user .avatar").forEach(function (a) { a.innerHTML = avatarInnerHtml(); });
    qsa(".msg.user .avatar").forEach(function (a) { a.innerHTML = avatarInnerHtml(); });
    qsa(".me-card .avatar").forEach(function (a) { a.innerHTML = avatarInnerHtml(); });
    refreshAvatarPanel();
  }
  /* 上传头像：仅图片、≤200KB（FileReader → dataURL） */
  function handleAvatarFile(input) {
    var file = input.files && input.files[0];
    if (!file) return;
    if (!/^image\//.test(file.type)) { toast("请选择图片文件"); return; }
    if (file.size > 200 * 1024) { toast("图片超过 200KB，请压缩后再上传"); return; }
    var reader = new FileReader();
    reader.onload = function () {
      saveAvatar({ type: "img", data: String(reader.result || "") });
    };
    reader.onerror = function () { toast("图片读取失败，请重试"); };
    reader.readAsDataURL(file);
  }

  /* ================= 路由 ================= */
  var ROUTES = ["workspace", "chat", "money", "papers", "library", "apps", "admin", "me", "login"];
  var NAV = [
    { group: "主面板", items: [
      { route: "workspace", icon: "home", label: "工作台" },
      { route: "chat", icon: "chat", label: "对话" },
      { route: "money", icon: "money", label: "记账" },
      { route: "papers", icon: "book", label: "文献" },
      { route: "library", icon: "edit", label: "我的文献" }
    ] },
    { group: "系统", items: [
      { route: "apps", icon: "grid", label: "应用中心" },
      { route: "admin", icon: "gear", label: "平台管理" },
      { route: "me", icon: "user", label: "我的" }
    ] }
  ];
  var TITLES = { workspace: "工作台", chat: "AI 对话", money: "记账本", papers: "文献", library: "我的文献", apps: "应用中心", admin: "平台管理", me: "我的", login: "登录" };

  function currentRoute() {
    var h = location.hash.replace(/^#\/?/, "").split("?")[0];
    return ROUTES.indexOf(h) !== -1 ? h : "workspace";
  }
  function go(route) { location.hash = "#/" + route; }

  var pendingAfterRender = null;
  function afterRender(fn) { pendingAfterRender = fn; }

  function renderSider() {
    var html = NAV.map(function (g) {
      return '<div class="sider-group"><div class="sider-group-label">' + g.group + "</div>" +
        g.items.map(function (it) {
          return '<a class="nav-item" href="#/' + it.route + '" data-route-link="' + it.route + '"><i data-ic="' + it.icon + '"></i>' + it.label + "</a>";
        }).join("") + "</div>";
    }).join("");
    qs("#sider-nav").innerHTML = html;
  }

  function render() {
    var r = currentRoute();
    if (!authGuard(r)) return;
    closeReader(); /* P8：路由切换（含退出登录）时收起批注阅读器 */
    document.body.dataset.route = r;
    qsa("[data-route-link]").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-route-link") === r);
    });
    document.title = TITLES[r] + " · 流光咖啡馆";
    var view = qs("#view");
    view.classList.remove("view-in");
    void view.offsetWidth; /* 重启动画 */
    view.innerHTML = PAGES[r]();
    view.classList.add("view-in");
    injectIcons(view);
    applyUserAvatar();
    window.scrollTo(0, 0);
    closeDrawers();
    if (INITS[r]) INITS[r](view);
    if (pendingAfterRender) { var fn = pendingAfterRender; pendingAfterRender = null; setTimeout(fn, 60); }
  }
  window.addEventListener("hashchange", render);

  function closeDrawers() {
    qsa(".sider.open, .conv-panel.open").forEach(function (el) { el.classList.remove("open"); });
    var m = qs("[data-drawer-mask]");
    if (m) m.classList.remove("open");
  }

  /* ================= 页面模板 ================= */
  function sparkline(values, cls) {
    var max = Math.max.apply(null, values);
    return '<span class="sparkline">' + values.map(function (v) {
      return '<i class="' + cls + '" style="height:' + Math.max(8, Math.round((v / max) * 100)) + '%"></i>';
    }).join("") + "</span>";
  }

  /* 模型池：对话选择器用「活数据」（GET /chat/models），管理页仍用演示数据 */
  var liveModels = []; /* [{id, name, provider, capabilities, reasoning, is_default}] */
  function modelPool() {
    var groups = {};
    liveModels.forEach(function (m) {
      (groups[m.provider] = groups[m.provider] || []).push(m);
    });
    return Object.keys(groups).map(function (k) {
      return { provider: k, items: groups[k].map(function (m) {
        return { id: m.id, name: m.name, context: (m.capabilities && m.capabilities.context) || "", files: !!(m.capabilities && m.capabilities.files), vision: !!(m.capabilities && m.capabilities.vision), reasoning: m.reasoning || (m.capabilities && m.capabilities.reasoning) || null, is_default: !!m.is_default };
      }) };
    });
  }
  function defaultModel() {
    var d = liveModels.filter(function (m) { return m.is_default; })[0];
    return d ? d.name : (liveModels[0] ? liveModels[0].name : "default");
  }
  /* 对话会话状态（活数据：conversation_id / 模型 id / 思考档位） */
  var chatState = { convId: null, modelId: null, thinkingLevel: null, sending: false, newConv: false };
  /* 模型思考档位默认值（P0-2 ⑤：默认取 meta.reasoning.default_level） */
  function defaultThinkingOf(modelId) {
    var m = liveModels.filter(function (x) { return x.id === modelId; })[0];
    var r = m && m.reasoning;
    return r && r.enabled ? (r.default_level || null) : null;
  }
  function capsOf(name) {
    var m = liveModels.filter(function (x) { return x.name === name; })[0];
    return (m && m.capabilities) || {};
  }
  function syncMpCheck() {
    qsa("[data-mp-item]").forEach(function (item) {
      var on = parseInt(item.getAttribute("data-mp-item"), 10) === chatState.modelId;
      item.classList.toggle("selected", on);
      var ck = item.querySelector(".mp-check");
      if (ck) ck.style.visibility = on ? "visible" : "hidden";
    });
  }
  function syncUploadBtn() {
    var btn = qs("[data-upload]");
    if (!btn) return;
    var name = null;
    liveModels.forEach(function (m) { if (m.id === chatState.modelId) name = m.name; });
    var ok = name ? !!capsOf(name).files : false;
    btn.classList.toggle("is-disabled", !ok);
    btn.title = ok ? "上传文件" : "当前模型不支持文件上传";
  }

  /* 编辑模型 meta：档位子表单（P1-1：value+label 增删行 + 默认档下拉；预留位只落数据） */
  var mmEditing = { pid: null, mid: null };
  function lvRowHtml(value, label) {
    return '<div class="lv-row" data-lv-row>' +
      '<input type="text" data-lv-value placeholder="value（官方协议值，如 high）" value="' + esc(value || "") + '">' +
      '<input type="text" data-lv-label placeholder="label（官方命名，如 高）" value="' + esc(label || "") + '">' +
      '<button class="icon-btn xs" type="button" data-lv-del aria-label="删除该档"><i data-ic="trash"></i></button></div>';
  }
  function collectLevelRows() {
    var levels = [];
    qsa("[data-lv-row]").forEach(function (row) {
      var v = row.querySelector("[data-lv-value]");
      var l = row.querySelector("[data-lv-label]");
      var value = v ? v.value.trim() : "";
      if (!value) return;
      levels.push({ value: value, label: (l && l.value.trim()) || value });
    });
    return levels;
  }
  function refreshMmDefaultOptions() {
    var sel = qs("[data-mm-default]");
    if (!sel) return;
    var cur = sel.getAttribute("data-cur") || "";
    var levels = collectLevelRows();
    sel.innerHTML = levels.map(function (l) {
      return '<option value="' + esc(l.value) + '"' + (l.value === cur ? " selected" : "") + ">" + esc(l.label) + "（" + esc(l.value) + "）</option>";
    }).join("");
    if (!levels.length) sel.innerHTML = '<option value="">（先添加档位）</option>';
  }
  function openModelMetaModal(mid) {
    var p = adminState.pvDetail;
    if (!p) return;
    var m = (p.models || []).filter(function (x) { return x.id === mid; })[0];
    if (!m) return;
    mmEditing = { pid: p.id, mid: m.id };
    var meta = m.meta || {};
    var r = meta.reasoning || null;
    var nameEl = qs("[data-mm-name]"); if (nameEl) nameEl.value = m.name;
    var ctxEl = qs("[data-mm-context]"); if (ctxEl) ctxEl.value = meta.context || "";
    var visionEl = qs("[data-mm-vision]"); if (visionEl) visionEl.checked = !!meta.vision;
    var filesEl = qs("[data-mm-files]"); if (filesEl) filesEl.checked = !!meta.files;
    var toolsEl = qs("[data-mm-tools]"); if (toolsEl) toolsEl.checked = !!meta.tools;
    var customEl = qs("[data-mm-custom]"); if (customEl) customEl.checked = !!meta.custom_protocol;
    /* 步 3：调用单价（meta.pricing，留空 = 不计量费用） */
    var priceInEl = qs("[data-mm-price-in]");
    if (priceInEl) priceInEl.value = (meta.pricing && meta.pricing.input_per_million != null) ? meta.pricing.input_per_million : "";
    var priceOutEl = qs("[data-mm-price-out]");
    if (priceOutEl) priceOutEl.value = (meta.pricing && meta.pricing.output_per_million != null) ? meta.pricing.output_per_million : "";
    var swEl = qs("[data-mm-reasoning-enabled]");
    var box = qs("[data-mm-reasoning-box]");
    var enabled = !!(r && r.enabled);
    if (swEl) setSwitch(swEl, enabled);
    if (box) box.classList.toggle("hide", !enabled);
    var rowsBox = qs("[data-mm-lv-rows]");
    var levels = (r && r.levels) || [];
    if (rowsBox) {
      rowsBox.innerHTML = levels.length
        ? levels.map(function (l) { return lvRowHtml(l.value, l.label); }).join("")
        : lvRowHtml("", "");
      injectIcons(rowsBox);
    }
    var sel = qs("[data-mm-default]");
    if (sel) sel.setAttribute("data-cur", (r && r.default_level) || "");
    refreshMmDefaultOptions();
    openModal("#modal-model-meta");
  }
  function saveModelMeta() {
    if (!mmEditing.pid || !mmEditing.mid) return;
    var enabled = false;
    var swEl = qs("[data-mm-reasoning-enabled]");
    if (swEl) enabled = swEl.classList.contains("on");
    var levels = enabled ? collectLevelRows() : [];
    var sel = qs("[data-mm-default]");
    var defaultLevel = null;
    if (enabled && sel && sel.value) defaultLevel = sel.value;
    /* 步 3：单价留空 = 不计量费用（pricing 键整体省略） */
    var priceIn = parseFloat((qs("[data-mm-price-in]") || {}).value);
    var priceOut = parseFloat((qs("[data-mm-price-out]") || {}).value);
    var meta = {
      context: (qs("[data-mm-context]") || {}).value || "",
      vision: !!(qs("[data-mm-vision]") || {}).checked,
      files: !!(qs("[data-mm-files]") || {}).checked,
      reasoning: { enabled: enabled, levels: levels, default_level: defaultLevel },
      tools: !!(qs("[data-mm-tools]") || {}).checked,
      custom_protocol: !!(qs("[data-mm-custom]") || {}).checked
    };
    if (!isNaN(priceIn) || !isNaN(priceOut)) {
      meta.pricing = {
        input_per_million: isNaN(priceIn) ? null : priceIn,
        output_per_million: isNaN(priceOut) ? null : priceOut
      };
    }
    API.put("/admin/models/providers/" + mmEditing.pid + "/models/" + mmEditing.mid, { meta: meta })
      .then(function () {
        toast("模型配置已保存");
        var mask = qs("#modal-model-meta");
        if (mask) mask.classList.remove("open");
        selectProvider(mmEditing.pid);
      })
      .catch(function (e) { toast(e.detail || "保存失败"); });
  }

  /* 平台管理活数据状态（/admin/* 联调） */
  var adminState = {
    users: [], roles: [], perms: [], providers: [], tokens: [],
    pvDetail: null, defaultRoute: null, addRowOpen: false,
    /* 步 3：模型指派 / 熔断状态 / 用量统计 */
    assignments: [], modelPool: [], circuitStates: [],
    usage: { summary: null, logs: null, start: "", end: "", page: 1, pageSize: 20 },
    /* 底座小件：服务 Key 表（/admin/service-keys；skEditing = null 新增，否则为编辑行） */
    serviceKeys: [], skEditing: null
  };

  /* ---------- 服务 Key 管理（异构服务钥匙集中管理：表格 + 中央弹窗新增/编辑） ---------- */
  var SK_RE = /^[a-z0-9_]{1,64}$/;
  function skeyRowHtml(k) {
    return '<tr data-sk-row="' + k.id + '">' +
      "<td><b>" + esc(k.service_key) + "</b></td>" +
      "<td>" + esc(k.vendor || "—") + "</td>" +
      '<td><code class="mono-mask">' + esc(k.api_key_masked || "") + "</code></td>" +
      '<td><span class="muted" style="font-size:13px;">' + esc(k.base_url || "—") + "</span></td>" +
      '<td><span class="muted" style="font-size:13px;">' + esc(k.note || "—") + "</span></td>" +
      '<td><button class="switch' + (k.enabled ? " on" : "") + '" type="button" role="switch" aria-checked="' + (k.enabled ? "true" : "false") + '" data-sk-toggle="' + k.id + '" aria-label="启用该服务钥匙"></button></td>' +
      '<td class="t-right">' +
        '<button class="link-op" type="button" data-sk-edit="' + k.id + '">编辑</button>' +
        '<button class="link-op danger" type="button" data-sk-del="' + k.id + '" style="margin-left:8px;">删除</button>' +
      "</td></tr>";
  }
  function renderServiceKeys() {
    var tb = qs("[data-sk-rows]");
    if (!tb) return;
    tb.innerHTML = adminState.serviceKeys.length
      ? adminState.serviceKeys.map(skeyRowHtml).join("")
      : '<tr><td colspan="7" class="muted" style="padding:14px;">暂无服务钥匙，点击右上角「新增钥匙」添加</td></tr>';
  }
  function loadServiceKeys() {
    API.get("/admin/service-keys").then(function (rows) {
      adminState.serviceKeys = rows || [];
      renderServiceKeys();
    }).catch(function (e) { toast(e.detail || "服务钥匙加载失败"); });
  }
  /* 弹窗复位/填充：row = null 新增（服务名可填），否则编辑（服务名只读、钥匙留空 = 不改） */
  function openSkeyModal(row) {
    adminState.skEditing = row || null;
    var title = qs("#modal-skey-title");
    if (title) title.textContent = row ? "编辑钥匙" : "新增钥匙";
    var svc = qs("#modal-skey [data-sk-service]");
    var vendor = qs("#modal-skey [data-sk-vendor]");
    var key = qs("#modal-skey [data-sk-key]");
    var url = qs("#modal-skey [data-sk-url]");
    var note = qs("#modal-skey [data-sk-note]");
    if (svc) { svc.value = row ? row.service_key : ""; svc.disabled = !!row; }
    if (vendor) vendor.value = row ? (row.vendor || "") : "";
    if (key) key.value = "";
    if (url) url.value = row ? (row.base_url || "") : "";
    if (note) note.value = row ? (row.note || "") : "";
    if (key) key.placeholder = row ? "留空 = 不修改" : "厂商颁发的完整 API 钥匙";
    openModal("#modal-skey");
  }
  function saveSkey() {
    var row = adminState.skEditing;
    var svc = qs("#modal-skey [data-sk-service]");
    var vendor = qs("#modal-skey [data-sk-vendor]");
    var key = qs("#modal-skey [data-sk-key]");
    var url = qs("#modal-skey [data-sk-url]");
    var note = qs("#modal-skey [data-sk-note]");
    var serviceKey = svc ? svc.value.trim() : "";
    var vendorVal = vendor ? vendor.value.trim() : "";
    var keyVal = key ? key.value.trim() : "";
    if (!row) {
      if (!serviceKey) { toast("先填服务名"); return; }
      if (!SK_RE.test(serviceKey)) { toast("服务名仅允许小写字母、数字、下划线"); return; }
      if (!vendorVal) { toast("先填厂商"); return; }
      if (!keyVal) { toast("先填 API 钥匙"); return; }
    } else if (!vendorVal) { toast("先填厂商"); return; }
    var body = { vendor: vendorVal, base_url: url ? url.value.trim() : "", note: note ? note.value.trim() : "" };
    var req;
    if (row) {
      if (keyVal) body.api_key = keyVal; /* 留空 = 不修改 */
      req = API.put("/admin/service-keys/" + row.id, body);
    } else {
      body.service_key = serviceKey;
      body.api_key = keyVal;
      req = API.post("/admin/service-keys", body);
    }
    req.then(function () {
      toast(row ? "钥匙已更新" : "钥匙已新增");
      var mask = qs("#modal-skey");
      if (mask && mask.close) { if (mask.open) mask.close(); } else if (mask) mask.classList.remove("open");
      loadServiceKeys();
    }).catch(function (e) { toast(e.detail || "保存失败"); });
  }

  /* ---------- 步 3 · 模型指派（每个应用一条有序模型链：chips + 拖拽排序 + 全局保存） ---------- */

  /* ================= 通用自定义下拉 xselect =================
   * 视觉/交互参考：Arco Design Select（触发器与弹层同宽、当前项右侧对勾、hover 高亮、
   * 圆角浮层带阴影 + 弹出动画、↑↓/Enter/Esc 键盘语义、超长列表限高滚动）与
   * LobeChat 模型选择器（选中项对勾回显、选项行名称 + 辅助信息）。
   * 用法：xselectHtml({ value, placeholder, options: [{ value, label }], attrs, cls })
   * 取值：xselectValue(root) / xselectLabel(root)；attrs 里可放业务 data-* 属性。
   * 事件全部走全局委托；选中后 root 派发 "xselect:change"（bubbles，detail = { value, label }），
   * 供后续页面按需订阅；本次页面直接读值即可（PUT 请求体格式不变）。 */
  function xselectHtml(opts) {
    var value = opts.value != null ? String(opts.value) : "";
    var placeholder = opts.placeholder || "请选择";
    var options = opts.options || [];
    var attrs = opts.attrs || "";
    var cls = opts.cls || "";
    var current = options.filter(function (o) { return String(o.value) === value; })[0];
    var label = current ? current.label : "";
    return '<div class="xselect' + (cls ? " " + cls : "") + (label ? "" : " is-placeholder") + '" data-xselect ' + attrs +
      ' data-value="' + esc(value) + '">' +
      '<button class="xselect-trigger" type="button" data-xselect-trigger aria-haspopup="listbox" aria-expanded="false">' +
      '<span class="xselect-label">' + esc(label || placeholder) + "</span>" +
      '<i data-ic="down" class="xselect-caret"></i></button>' +
      '<div class="xselect-pop hide" data-xselect-pop role="listbox">' +
      (options.length
        ? options.map(function (o) {
            var on = String(o.value) === value;
            return '<div class="xselect-opt' + (on ? " selected" : "") + '" role="option" aria-selected="' + (on ? "true" : "false") +
              '" data-xselect-opt="' + esc(String(o.value)) + '" title="' + esc(o.label) + '">' +
              '<span class="xselect-opt-label">' + esc(o.label) + "</span>" +
              '<i data-ic="check" class="xselect-check"></i></div>';
          }).join("")
        : '<div class="xselect-empty">暂无选项</div>') +
      "</div></div>";
  }
  function xselectValue(root) { return root ? (root.getAttribute("data-value") || "") : ""; }
  function xselectLabel(root) {
    if (!root) return "";
    var v = xselectValue(root);
    var hit = qsa("[data-xselect-opt]", root).filter(function (o) { return o.getAttribute("data-xselect-opt") === v; })[0];
    if (hit) { var l = hit.querySelector(".xselect-opt-label"); return l ? l.textContent : ""; }
    return root.classList.contains("is-placeholder") ? "" : ((qs(".xselect-label", root) || {}).textContent || "");
  }
  /* 弹层定位常量：与 trigger 间距、限高、最小下方余量（不足则向上翻） */
  var XSEL_GAP = 6, XSEL_MAX_H = 264, XSEL_MAX_W = 360;
  /* scroll/resize（捕获阶段，容器滚动也会冒到 window）→ 直接收起弹层（主流 popper 行为，
     跟随重算在表格横向滚动场景反而别扭）；最后一个弹层收起时解绑监听 */
  function xselectOnViewportChange() {
    qsa(".xselect-pop:not(.hide)").forEach(function (p) { xselectClosePop(p.closest("[data-xselect]")); });
  }
  function xselectBindViewport(on) {
    var fn = on ? "addEventListener" : "removeEventListener";
    window[fn]("scroll", xselectOnViewportChange, { capture: true, passive: true });
    window[fn]("resize", xselectOnViewportChange);
  }
  function xselectClosePop(root) {
    if (!root) return;
    var pop = qs("[data-xselect-pop]", root);
    if (pop) pop.classList.add("hide");
    root.classList.remove("open");
    var trg = qs("[data-xselect-trigger]", root);
    if (trg) trg.setAttribute("aria-expanded", "false");
    if (!qs(".xselect-pop:not(.hide)")) xselectBindViewport(false);
  }
  /* fixed 定位：读 trigger 视口坐标，计算弹层 left/top（下方空间不足 264px 则翻到上方） */
  function xselectPlacePop(root, pop) {
    var trg = qs("[data-xselect-trigger]", root);
    if (!trg) return;
    var r = trg.getBoundingClientRect();
    var popH = Math.min(pop.offsetHeight, XSEL_MAX_H);
    var below = window.innerHeight - r.bottom;
    var top = r.bottom + XSEL_GAP;
    pop.classList.toggle("up", below < popH + XSEL_GAP && r.top >= popH + XSEL_GAP);
    if (pop.classList.contains("up")) top = r.top - popH - XSEL_GAP;
    var maxW = Math.min(XSEL_MAX_W, Math.round(window.innerWidth * 0.8));
    var left = r.left;
    if (left + maxW > window.innerWidth - 8) left = Math.max(8, window.innerWidth - maxW - 8);
    pop.style.left = Math.round(left) + "px";
    pop.style.top = Math.round(top) + "px";
    pop.style.minWidth = Math.round(r.width) + "px";
  }
  function xselectOpenPop(root) {
    if (!root) return;
    /* 单开：打开前收起其它 xselect 弹层（同页多个指派行互不干扰） */
    qsa(".xselect-pop:not(.hide)").forEach(function (p) { xselectClosePop(p.closest("[data-xselect]")); });
    var pop = qs("[data-xselect-pop]", root);
    if (!pop) return;
    pop.classList.remove("hide");
    root.classList.add("open");
    var trg = qs("[data-xselect-trigger]", root);
    if (trg) trg.setAttribute("aria-expanded", "true");
    /* 定位 + 视口监听；rAF 再校一次——click 触发的 :active transform 回弹动画会短暂改变坐标系 */
    xselectPlacePop(root, pop);
    if (window.requestAnimationFrame) window.requestAnimationFrame(function () { if (!pop.classList.contains("hide")) xselectPlacePop(root, pop); });
    xselectBindViewport(true);
    /* 高亮当前选中项（无则首项），并对齐到可视区 */
    qsa(".xselect-opt", pop).forEach(function (o) { o.classList.remove("active"); });
    var cur = qs(".xselect-opt.selected", pop) || qs(".xselect-opt", pop);
    if (cur) {
      cur.classList.add("active");
      if (cur.scrollIntoView) cur.scrollIntoView({ block: "nearest" });
    }
  }
  function xselectToggle(root) {
    var pop = qs("[data-xselect-pop]", root);
    if (!pop) return;
    if (pop.classList.contains("hide")) xselectOpenPop(root);
    else xselectClosePop(root);
  }
  function xselectMove(root, dir) {
    var pop = qs("[data-xselect-pop]", root);
    if (!pop) return;
    var list = qsa(".xselect-opt", pop);
    if (!list.length) return;
    var idx = list.indexOf(qs(".xselect-opt.active", pop));
    idx = ((idx < 0 ? 0 : idx) + dir + list.length) % list.length;
    list.forEach(function (o, i) { o.classList.toggle("active", i === idx); });
    if (list[idx].scrollIntoView) list[idx].scrollIntoView({ block: "nearest" });
  }
  function xselectPick(root, opt) {
    if (!root || !opt) return;
    var value = opt.getAttribute("data-xselect-opt") || "";
    var labelEl = opt.querySelector(".xselect-opt-label");
    var label = labelEl ? labelEl.textContent : "";
    root.setAttribute("data-value", value);
    root.classList.remove("is-placeholder");
    var lbl = qs(".xselect-label", root);
    if (lbl) lbl.textContent = label;
    var pop = qs("[data-xselect-pop]", root);
    if (pop) qsa(".xselect-opt", pop).forEach(function (o) {
      var on = o === opt;
      o.classList.toggle("selected", on);
      o.setAttribute("aria-selected", on ? "true" : "false");
    });
    xselectClosePop(root);
    root.dispatchEvent(new CustomEvent("xselect:change", { bubbles: true, detail: { value: value, label: label } }));
  }
  /* ================= 角色下拉 role-pop（fixed 定位，防表格容器 overflow 裁剪） =================
   * 与 xselectPlacePop 同思路：读 trigger（.role-pill）的 getBoundingClientRect 计算坐标；
   * 默认下方 6px、left 对齐；下方空间不足且上方够高时翻到上方；右缘超出视口时左移钳制；
   * 打开时 rAF 二次校准；scroll(capture)/resize 期间直接收起（主流 popper 行为）。 */
  var ROLE_POP_GAP = 6, ROLE_POP_W = 220;
  function rolePopCloseAll() {
    qsa(".role-pop:not(.hide)").forEach(function (p) { p.classList.add("hide"); });
    rolePopBindViewport(false);
  }
  function rolePopOnViewportChange() { rolePopCloseAll(); }
  function rolePopBindViewport(on) {
    var fn = on ? "addEventListener" : "removeEventListener";
    window[fn]("scroll", rolePopOnViewportChange, { capture: true, passive: true });
    window[fn]("resize", rolePopOnViewportChange);
  }
  function rolePopPlace(cell) {
    var pop = qs(".role-pop", cell);
    var pill = qs("[data-role-picker]", cell);
    if (!pop || !pill) return;
    var r = pill.getBoundingClientRect();
    var popH = pop.offsetHeight;
    var below = window.innerHeight - r.bottom;
    var top = r.bottom + ROLE_POP_GAP;
    pop.classList.toggle("up", below < popH + ROLE_POP_GAP && r.top >= popH + ROLE_POP_GAP);
    if (pop.classList.contains("up")) top = r.top - popH - ROLE_POP_GAP;
    var left = r.left;
    if (left + ROLE_POP_W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - ROLE_POP_W - 8);
    pop.style.left = Math.round(left) + "px";
    pop.style.top = Math.round(top) + "px";
  }
  function rolePopOpen(cell) {
    var pop = qs(".role-pop", cell);
    if (!pop) return;
    /* 单开：打开前收起其它角色弹层 */
    rolePopCloseAll();
    pop.classList.remove("hide");
    /* 定位 + 视口监听；rAF 再校一次——click 触发的 :active transform 回弹动画会短暂改变坐标系 */
    rolePopPlace(cell);
    if (window.requestAnimationFrame) window.requestAnimationFrame(function () { if (!pop.classList.contains("hide")) rolePopPlace(cell); });
    rolePopBindViewport(true);
  }
  /* 模型指派：模型池 → xselect（替代原生 select；data-value 存模型 id，保存时 parseInt，请求体格式不变） */
  function modelPoolXselect(attrs, curId, placeholder) {
    return xselectHtml({
      value: curId,
      placeholder: placeholder || "选择模型",
      options: adminState.modelPool.map(function (m) {
        return { value: String(m.id), label: m.name + "（" + m.provider_name + "）" };
      }),
      attrs: attrs
    });
  }
  /* 模型链 chip：第 ① 个 = 主模型（品牌蓝边框 + 淡蓝底 + 「主」标签），其余 = 备用（灰边框 + 序号）；
   * 数据存 DOM（data-mid），保存时按 DOM 顺序收集；hover 出 ⋮⋮ 拖拽手柄与 ×。 */
  var CHAIN_NUMS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
  function chainChipHtml(ref, idx, alone) {
    var primary = idx === 0;
    return '<span class="chain-chip' + (primary ? " is-primary" : "") + '" data-chain-item draggable="true" data-mid="' + ref.id + '">' +
      '<i class="chain-grip" data-ic="grip" title="拖拽排序"></i>' +
      '<span class="chain-idx">' + (primary ? "主" : (CHAIN_NUMS[idx] || String(idx + 1))) + "</span>" +
      '<span class="chain-name" title="' + esc(ref.name) + '">' + esc(ref.name) + "</span>" +
      '<button class="chain-del' + (alone ? " hide" : "") + '" type="button" data-chain-del aria-label="移除">×</button></span>';
  }
  /* 增删/拖拽后重排：主标签、序号即时刷新；链中只剩 1 个模型时隐藏 ×（至少保留一个主模型） */
  function chainReindex(box) {
    if (!box) return;
    var chips = qsa("[data-chain-item]", box);
    chips.forEach(function (c, i) {
      c.classList.toggle("is-primary", i === 0);
      var idxEl = qs(".chain-idx", c);
      if (idxEl) idxEl.textContent = i === 0 ? "主" : (CHAIN_NUMS[i] || String(i + 1));
      var del = qs(".chain-del", c);
      if (del) del.classList.toggle("hide", chips.length <= 1);
    });
  }
  function chainIds(appKey) {
    var box = qs('[data-asg-chain="' + appKey + '"]');
    if (!box) return [];
    return qsa("[data-chain-item]", box).map(function (c) { return parseInt(c.getAttribute("data-mid"), 10); });
  }
  function assignmentRowHtml(a) {
    /* 链 = 主模型（服务端 primary_model_id，名称从模型池回查）+ 有序备用链 */
    var pool = adminState.modelPool;
    var chain = [];
    if (a.primary_model_id) {
      var pm = pool.filter(function (m) { return m.id === a.primary_model_id; })[0];
      chain.push({ id: a.primary_model_id, name: pm ? pm.name : ("模型 #" + a.primary_model_id) });
    }
    (a.fallback_chain || []).forEach(function (r) { chain.push({ id: r.id, name: r.name }); });
    var chips = chain.map(function (r, i) { return chainChipHtml(r, i, chain.length <= 1); }).join("");
    return '<tr data-asg-row="' + esc(a.app_key) + '">' +
      "<td><b>" + esc(a.app_key) + "</b></td>" +
      '<td><div class="chain-box" data-asg-chain="' + esc(a.app_key) + '">' + chips +
      '<button class="chain-add" type="button" data-asg-add="' + esc(a.app_key) + '" aria-label="添加模型"><i data-ic="plus"></i>添加模型</button>' +
      "</div></td>" +
      '<td><button class="switch' + (a.enabled ? " on" : "") + '" type="button" role="switch" aria-checked="' + (a.enabled ? "true" : "false") + '" data-asg-toggle aria-label="启用该指派"></button></td></tr>';
  }
  function renderAssignments() {
    var tb = qs("[data-asg-rows]");
    if (!tb) return;
    tb.innerHTML = adminState.assignments.length
      ? adminState.assignments.map(assignmentRowHtml).join("")
      : '<tr><td colspan="3" class="muted" style="padding:14px;">暂无指派</td></tr>';
    /* xselect 的 caret/check 图标为 data-ic 注入（异步重渲染后必须补注入） */
    injectIcons(tb);
    bindChainDrag(tb);
    refreshAsgSaveBtn();
  }
  /* 行脏判定：链成员/顺序或启用开关与基线（adminState.assignments，服务端回读值）不一致 */
  function asgRowDirty(a) {
    var row = qs('[data-asg-row="' + a.app_key + '"]');
    if (!row) return false;
    var base = [a.primary_model_id].concat((a.fallback_chain || []).map(function (r) { return r.id; })).join(",");
    var sw = qs("[data-asg-toggle]", row);
    var on = sw ? sw.classList.contains("on") : !!a.enabled;
    return chainIds(a.app_key).join(",") !== base || on !== !!a.enabled;
  }
  function asgDirtyRows() {
    return adminState.assignments.filter(asgRowDirty);
  }
  /* 全局「保存全部」：有任一改动（加/删/排序/开关）即亮起并显示改动行数，全部保存后恢复置灰 */
  function refreshAsgSaveBtn() {
    var btn = qs("[data-asg-save-all]");
    if (!btn) return;
    var saving = btn.classList.contains("saving");
    var n = asgDirtyRows().length;
    btn.disabled = saving || n === 0;
    var lbl = qs("[data-asg-save-label]", btn);
    if (lbl) lbl.textContent = saving ? "保存中…" : (n ? "保存全部（" + n + "）" : "保存全部");
  }
  /* HTML5 拖拽换位：复用工作台 bcard 的 grip + dragstart/dragover/drop 语义（lc_home_order 同一套模式），
   * 拖完即时重排序号并计入脏状态。事件委托绑在 tbody 上（只绑一次），动态追加的 chip 也能拖 */
  function bindChainDrag(tb) {
    if (tb.getAttribute("data-chain-drag-bound")) return;
    tb.setAttribute("data-chain-drag-bound", "1");
    tb.addEventListener("dragstart", function (e) {
      var chip = e.target.closest ? e.target.closest("[data-chain-item]") : null;
      if (!chip) return;
      chip.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", ""); } catch (err) {}
    });
    tb.addEventListener("dragend", function (e) {
      var chip = e.target.closest ? e.target.closest("[data-chain-item]") : null;
      if (!chip) return;
      chip.classList.remove("dragging");
      chainReindex(chip.closest("[data-asg-chain]"));
      refreshAsgSaveBtn();
    });
    tb.addEventListener("dragover", function (e) {
      var chip = e.target.closest ? e.target.closest("[data-chain-item]") : null;
      if (!chip) return;
      e.preventDefault();
      var box = chip.closest("[data-asg-chain]");
      if (!box) return;
      var dragged = qs(".chain-chip.dragging", box);
      if (!dragged || dragged === chip) return;
      var rect = chip.getBoundingClientRect();
      var before = (e.clientX - rect.left) < rect.width / 2;
      box.insertBefore(dragged, before ? chip : chip.nextSibling);
    });
  }
  /* 点「＋ 添加模型」：在该位置临时插入一个 xselect 锚点（复用现有组件与 xselectPlacePop 定位），
   * 选项实时剔除链中已选模型（防重复）；选中即追加到链尾，弹层收起后清理临时节点 */
  function asgOpenAddPop(btn, appKey) {
    var box = qs('[data-asg-chain="' + appKey + '"]');
    if (!box) return;
    var old = qs(".chain-addpop", box);
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var taken = chainIds(appKey);
    var options = adminState.modelPool.filter(function (m) { return taken.indexOf(m.id) === -1; })
      .map(function (m) { return { value: String(m.id), label: m.name + "（" + m.provider_name + "）" }; });
    var wrap = document.createElement("span");
    wrap.className = "chain-addpop";
    wrap.innerHTML = xselectHtml({ value: "", placeholder: "选择模型", options: options, attrs: "data-asg-add-sel" });
    box.insertBefore(wrap, btn.nextSibling);
    injectIcons(wrap);
    xselectOpenPop(qs("[data-xselect]", wrap));
  }
  /* xselect 选中 → 追加到链尾、清理临时锚点、重排序号并计入脏状态 */
  function asgPickAdd(root) {
    var wrap = root.closest(".chain-addpop");
    var box = root.closest("[data-asg-chain]");
    var mid = parseInt(xselectValue(root), 10);
    var name = xselectLabel(root).split("（")[0];
    if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap);
    var addBtn = box ? qs("[data-asg-add]", box) : null;
    if (box && addBtn && mid) {
      var n = qsa("[data-chain-item]", box).length;
      addBtn.insertAdjacentHTML("beforebegin", chainChipHtml({ id: mid, name: name }, n, false));
      chainReindex(box);
      refreshAsgSaveBtn();
    }
  }
  /* 全局保存：按行顺序串行发既有 PUT（请求体格式不变——链第 1 个 = 主模型，其余 = 有序备用链）；
   * 全部成功 → toast + 回读刷新、按钮恢复置灰；任一失败 → toast 报错且保持亮起可重试 */
  function saveAllAssignments() {
    var btn = qs("[data-asg-save-all]");
    if (!btn || btn.classList.contains("saving")) return;
    var dirty = asgDirtyRows();
    if (!dirty.length) return;
    btn.classList.add("saving");
    refreshAsgSaveBtn();
    var seq = Promise.resolve();
    dirty.forEach(function (a) {
      seq = seq.then(function () {
        var ids = chainIds(a.app_key);
        if (!ids.length) return Promise.reject({ detail: "「" + a.app_key + "」至少保留一个主模型" });
        var sw = qs('[data-asg-row="' + a.app_key + '"] [data-asg-toggle]');
        return API.put("/admin/models/assignments/" + a.app_key, {
          primary_model_id: ids[0],
          fallback_chain: ids.slice(1),
          enabled: sw ? sw.classList.contains("on") : true
        });
      });
    });
    seq.then(function () {
      toast("指派已保存");
      loadAssignments();
    }).catch(function (e) {
      toast((e && e.detail) || "保存失败，请重试");
    }).then(function () {
      if (btn) btn.classList.remove("saving");
      refreshAsgSaveBtn();
    });
  }
  function renderCircuitStates() {
    var tb = qs("[data-cb-rows]");
    if (!tb) return;
    tb.innerHTML = adminState.circuitStates.length
      ? adminState.circuitStates.map(function (s) {
          var open = s.state === "open";
          return "<tr><td>" + esc(s.model_name) + "</td>" +
            '<td><span class="pill ' + (open ? "pill-warn" : "pill-ok") + '">' + (open ? "熔断中" : "正常") + "</span></td>" +
            "<td>" + s.consecutive_failures + "</td>" +
            "<td>" + (open && s.next_probe_at ? esc((s.next_probe_at || "").replace("T", " ").slice(5, 19)) : "—") + "</td>" +
            '<td class="t-right">' + (open
              ? '<button class="btn btn-ghost btn-sm" type="button" data-cb-reset="' + s.model_id + '">恢复</button>'
              : '<span class="muted" style="font-size:12.5px;">—</span>') + "</td></tr>";
        }).join("")
      : '<tr><td colspan="5" class="muted" style="padding:14px;">暂无熔断记录（所有模型正常）</td></tr>';
  }
  function loadAssignments() {
    API.get("/admin/models/assignments").then(function (d) {
      adminState.assignments = (d && d.assignments) || [];
      adminState.modelPool = (d && d.model_pool) || [];
      renderAssignments();
    }).catch(function () {});
    API.get("/admin/models/circuit-states").then(function (s) {
      adminState.circuitStates = s || [];
      renderCircuitStates();
    }).catch(function () {});
  }

  /* ---------- 步 3 · 用量统计（one-api 式：概览卡片 + 表格 + 时间筛选） ---------- */
  function fmtNum(n) { return (n || 0).toLocaleString("zh-CN"); }
  function fmtCost(c) { return c === null || c === undefined ? "—" : "¥" + Number(c).toFixed(4); }
  function usageWindowParams() {
    var p = {};
    if (adminState.usage.start) p.start = adminState.usage.start + ":00+08:00";
    if (adminState.usage.end) p.end = adminState.usage.end + ":59+08:00";
    return p;
  }
  function renderUsage() {
    var cards = qs("[data-usage-cards]");
    var s = adminState.usage.summary;
    if (cards) {
      cards.innerHTML = s
        ? '<div class="stat-cell"><small>总调用</small><b>' + fmtNum(s.total_calls) + '</b><span class="stat-unit">次</span></div>' +
          '<div class="stat-cell"><small>成功率</small><b>' + Math.round(s.success_rate * 1000) / 10 + '</b><span class="stat-unit">%</span></div>' +
          '<div class="stat-cell"><small>Token（进 / 出）</small><b>' + fmtNum(s.input_tokens) + ' <span class="stat-unit">/ ' + fmtNum(s.output_tokens) + '</span></b></div>' +
          '<div class="stat-cell"><small>总费用</small><b>' + fmtCost(s.total_cost) + '</b></div>' +
          '<div class="stat-cell"><small>平均延迟</small><b>' + s.avg_latency_ms + '</b><span class="stat-unit">ms</span></div>'
        : '<div class="stat-cell"><small>总调用</small><b>—</b></div><div class="stat-cell"><small>成功率</small><b>—</b></div>' +
          '<div class="stat-cell"><small>Token（进 / 出）</small><b>—</b></div><div class="stat-cell"><small>总费用</small><b>—</b></div>' +
          '<div class="stat-cell"><small>平均延迟</small><b>—</b></div>';
    }
    var mb = qs("[data-usage-model-rows]");
    if (mb) {
      mb.innerHTML = s && s.by_model.length
        ? s.by_model.map(function (m) {
            return "<tr><td>" + esc(m.model_name) + "</td><td>" + m.calls + "</td>" +
              "<td>" + Math.round(m.success_calls / m.calls * 1000) / 10 + "%</td>" +
              "<td>" + fmtNum(m.input_tokens) + "</td><td>" + fmtNum(m.output_tokens) + "</td>" +
              "<td>" + fmtCost(m.cost) + "</td></tr>";
          }).join("")
        : '<tr><td colspan="6" class="muted" style="padding:14px;">所选时段暂无调用</td></tr>';
    }
    var ab = qs("[data-usage-app-rows]");
    if (ab) {
      ab.innerHTML = s && s.by_app.length
        ? s.by_app.map(function (a) {
            return "<tr><td>" + esc(a.app_key) + "</td><td>" + a.calls + "</td>" +
              "<td>" + Math.round(a.success_calls / a.calls * 1000) / 10 + "%</td>" +
              "<td>" + fmtNum(a.input_tokens) + "</td><td>" + fmtNum(a.output_tokens) + "</td>" +
              "<td>" + fmtCost(a.cost) + "</td></tr>";
          }).join("")
        : '<tr><td colspan="6" class="muted" style="padding:14px;">所选时段暂无调用</td></tr>';
    }
    renderUsageLogs();
  }
  function renderUsageLogs() {
    var tb = qs("[data-usage-log-rows]");
    if (!tb) return;
    var page = adminState.usage.logs;
    if (!page) {
      tb.innerHTML = '<tr><td colspan="8" class="muted" style="padding:14px;">加载中…</td></tr>';
      return;
    }
    tb.innerHTML = page.items.length
      ? page.items.map(function (l) {
          return "<tr><td>" + esc((l.created_at || "").replace("T", " ").slice(5, 19)) + "</td>" +
            "<td>" + esc(l.app_key) + "</td><td>" + esc(l.model_name) + "</td>" +
            "<td>" + fmtNum(l.input_tokens) + "</td><td>" + fmtNum(l.output_tokens) + "</td>" +
            "<td>" + l.latency_ms + "ms</td>" +
            '<td>' + (l.success ? '<span class="pill pill-ok">成功</span>' : '<span class="pill pill-warn" title="' + esc(l.error || "") + '">失败</span>') + "</td>" +
            "<td>" + fmtCost(l.cost) + "</td></tr>";
        }).join("")
      : '<tr><td colspan="8" class="muted" style="padding:14px;">所选时段暂无日志</td></tr>';
    var info = qs("[data-usage-pageinfo]");
    if (info) {
      var pages = Math.max(1, Math.ceil(page.total / page.page_size));
      info.textContent = "第 " + page.page + " / " + pages + " 页 · 共 " + page.total + " 条";
      var prev = qs("[data-usage-page=prev]"), next = qs("[data-usage-page=next]");
      if (prev) prev.disabled = page.page <= 1;
      if (next) next.disabled = page.page >= pages;
    }
  }
  function loadUsage(page) {
    adminState.usage.page = page || adminState.usage.page || 1;
    var params = usageWindowParams();
    var q = Object.keys(params).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    API.get("/admin/models/usage/summary" + (q ? "?" + q : "")).then(function (s) {
      adminState.usage.summary = s;
      renderUsage();
    }).catch(function (e) { toast(e.detail || "统计加载失败"); });
    var lq = q ? q + "&page=" + adminState.usage.page + "&page_size=" + adminState.usage.pageSize
               : "page=" + adminState.usage.page + "&page_size=" + adminState.usage.pageSize;
    API.get("/admin/models/usage/logs?" + lq).then(function (p) {
      adminState.usage.logs = p;
      renderUsageLogs();
    }).catch(function () {});
  }

  /* 提供商详情面板（管理页右侧，选中切换时局部重绘） */
  function modelRowHtml(m) {
    var meta = m.meta || {};
    return '<div class="mm-model" data-mid="' + m.id + '">' +
      '<button class="switch' + (m.enabled ? " on" : "") + '" type="button" role="switch" aria-checked="' + (m.enabled ? "true" : "false") + '" data-model-enable="' + m.id + '" aria-label="启用该模型"></button>' +
      '<span class="mname">' + esc(m.name) + (m.custom ? '<span class="badge-soon">自定义</span>' : "") + "</span>" +
      '<span class="mm-meta">' + esc(meta.context || "") + "</span>" +
      '<span class="mm-caps">' +
        (meta.vision ? '<i class="ic" data-ic="eye" title="支持图片理解"></i>' : "") +
        (meta.files ? '<i class="ic" data-ic="doc" title="支持文件上传"></i>' : "") +
      "</span>" +
      '<span class="flex-spacer"></span>' +
      (m.is_default
        ? '<span class="pill pill-ok">默认</span>'
        : '<button class="btn btn-ghost btn-sm" type="button" data-set-default="' + m.id + '">设为默认</button>') +
      (m.custom ? '<button class="btn btn-danger-ghost btn-sm" type="button" data-del-model="' + m.id + '">删除</button>' : "") +
      '<button class="btn btn-ghost btn-sm" type="button" data-edit-meta="' + m.id + '">编辑</button>' +
    "</div>";
  }
  function pvDetailHtml(p) {
    if (!p) return '<div class="muted" style="padding:16px;">加载中…</div>';
    var models = p.models || [];
    return '' +
      '<div class="mm-detail-head"><div><div class="mm-name">' + esc(p.name) +
        ' <span class="pill ' + (p.enabled ? "pill-ok" : "pill-mute") + '">' + (p.enabled ? "已启用" : "已停用") + "</span></div>" +
        '<div class="mm-url">' + esc(p.base_url || "（未配置 Base URL，mock 占位）") + "</div></div>" +
        '<button class="switch' + (p.enabled ? " on" : "") + '" type="button" role="switch" aria-checked="' + (p.enabled ? "true" : "false") + '" data-provider-toggle="' + p.id + '" aria-label="启用该提供商"></button></div>' +
      '<div class="mm-grid">' +
        '<div class="field" style="margin-bottom:0;"><label>Base URL</label><input type="text" data-pv-base value="' + esc(p.base_url) + '"></div>' +
        '<div class="field" style="margin-bottom:0;"><label>API Key</label><input type="text" data-pv-key value="" autocomplete="off" placeholder="' + (p.has_key ? "已配置 " + esc(p.api_key_masked) + "（留空不修改）" : "sk-…") + '"></div>' +
      "</div>" +
      '<div class="mm-ops">' +
        '<button class="btn btn-ghost btn-sm" type="button" data-fetch="' + p.id + '"><i data-ic="spark"></i><span class="bl">拉取模型</span></button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-test-pv="' + p.id + '"><i data-ic="zap"></i><span class="bl">测试连通性</span></button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-save-pv="' + p.id + '">保存</button>' +
      "</div>" +
      '<div class="mm-models"><div class="mm-models-head"><span>模型（' + models.length + "）</span>" +
        '<button class="btn btn-ghost btn-sm" type="button" data-add-model="' + p.id + '"><i data-ic="plus"></i>添加模型</button></div>' +
        '<div class="mm-model-list" data-mm-list>' + models.map(modelRowHtml).join("") + "</div>" +
        '<div class="mm-add hide" data-mm-add>' +
          '<input type="text" data-am-name placeholder="模型名，如 kimi-k2">' +
          '<button class="btn btn-sm" type="button" data-confirm-add="' + p.id + '">确认添加</button>' +
        "</div></div>";
  }
  function renderPvDetail() {
    var box = qs("#mm-detail");
    if (!box) return;
    box.innerHTML = pvDetailHtml(adminState.pvDetail);
    injectIcons(box);
  }
  function pvListHtml(activeId) {
    var html = adminState.providers.map(function (p) {
      var def = null;
      if (adminState.pvDetail && adminState.pvDetail.id === p.id) {
        def = (adminState.pvDetail.models || []).filter(function (m) { return m.is_default; })[0];
      }
      return '<div class="mm-item' + (String(p.id) === String(activeId) ? " active" : "") + '" data-pv="' + p.id + '" role="button" tabindex="0">' +
        '<span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="plug"></i></span>' +
        '<div class="grow"><div class="name">' + esc(p.name) + "</div>" +
        '<div class="sub">' + esc(p.vendor) + (p.is_default ? " · 默认提供商" : "") + "</div></div>" +
        '<span class="pill ' + (p.enabled ? "pill-ok" : "pill-mute") + '">' + (p.enabled ? "启用" : "停用") + "</span></div>";
    }).join("");
    return html + '<button class="btn btn-ghost btn-sm" type="button" data-modal-open="#modal-add-pv"><i data-ic="plus"></i>添加提供商</button>';
  }
  function renderPvList(activeId) {
    var box = qs("#mm-list");
    if (!box) return;
    box.innerHTML = pvListHtml(activeId);
    injectIcons(box);
  }
  function selectProvider(pid) {
    adminState.pvDetail = null;
    renderPvList(pid);
    API.get("/admin/models/providers/" + pid).then(function (d) {
      adminState.pvDetail = d;
      renderPvDetail();
      renderPvList(pid);
    }).catch(function (e) { toast(e.detail || "加载失败"); });
  }
  function permSw(on, code, label) {
    return '<button class="switch' + (on ? " on" : "") + '" type="button" role="switch" aria-checked="' + (on ? "true" : "false") + '" data-perm-switch="' + code + '" aria-label="' + esc(label) + '"></button>';
  }
  function tokenRowHtml(t) {
    return "<tr><td>" + esc(t.name) + "</td>" +
      '<td><code class="mono-mask">' + esc(t.token_mask) + "</code></td>" +
      "<td>" + (t.model_scope && t.model_scope.length ? esc(t.model_scope.join("、")) : "全部模型") + "</td>" +
      "<td>" + esc((t.created_at || "").slice(0, 10) || "—") + "</td>" +
      "<td>" + (t.active ? '<span class="pill pill-ok">生效中</span>' : '<span class="pill pill-mute">已删除</span>') + "</td>" +
      "<td>" + (t.active
        ? '<button class="link-op" type="button" data-rotate-token="' + t.id + '">重新生成</button>' +
          '<button class="link-op danger" type="button" data-revoke-token="' + t.id + '" style="margin-left:8px;">删除</button>'
        : '<span class="muted" style="font-size:12.5px;">—</span>') + "</td></tr>";
  }
  function renderTokenRows() {
    var tb = qs("#gw-token-rows");
    if (tb) tb.innerHTML = adminState.tokens.map(tokenRowHtml).join("");
  }
  /* 成员详情抽屉（Supabase 侧栏模式）：u = /admin/users/{id} 详情 */
  function udrawerHtml(u) {
    function has(code) { return (u.permissions || []).indexOf(code) !== -1; }
    function swRow(label, code) {
      return '<div class="ud-sw"><span>' + label + "</span>" + permSw(has(code), code, label) + "</div>";
    }
    var roleNames = (u.roles || []).map(function (r) { return r.name; }).join("、") || "未分配";
    return '' +
      '<div class="ud-head"><span class="avatar">' + esc((u.nickname || u.username).slice(0, 1)) + "</span>" +
      "<div style=\"flex:1;min-width:0;\"><div class=\"ud-name\">" + esc(u.nickname || u.username) + "</div>" +
      '<div class="ud-sub">@' + esc(u.username) + " · " + esc(roleNames) + "</div></div>" +
      '<button class="icon-btn" type="button" data-ud-close aria-label="关闭"><i data-ic="close"></i></button></div>' +
      '<div class="ud-body">' +
      '<div class="ud-sec">权限（应用到角色：' + esc(roleNames) + "）</div>" +
      swRow("使用 AI 对话", "app:chat") +
      swRow("使用记账", "app:money") +
      swRow("使用文献（第二批）", "app:papers") +
      swRow("管理用户与角色", "admin:users") +
      swRow("管理模型与网关", "admin:models") +
      '<div class="ud-sec">账号</div>' +
      '<div class="ud-kv"><span>状态</span><span>' + (u.is_active ? "启用" : "已停用") + "</span></div>" +
      '<div class="ud-kv"><span>注册时间</span><span>' + esc((u.created_at || "").slice(0, 10) || "—") + "</span></div>" +
      '<div class="ud-kv" data-reset-result style="display:none;"><span>新密码</span><span class="mono-mask" style="font-size:12px;"></span></div>' +
      "</div>" +
      '<div class="ud-foot">' +
      '<button class="btn btn-ghost btn-sm" type="button" data-reset-pass="' + u.id + '"' + (u.is_active ? "" : " disabled") + '><i data-ic="key"></i>重置密码</button>' +
      '<button class="btn btn-danger-ghost btn-sm" type="button" data-disable-account="' + u.id + '"' + (u.is_active ? "" : " disabled") + ">" + (u.is_active ? "停用账号" : "已停用") + "</button></div>";
  }
  /* 成员表 + 角色矩阵渲染 */
  function userRowHtml(u) {
    var rid = u.roles && u.roles.length ? u.roles[0].id : 0;
    return '<tr class="u-row" data-user-row="' + u.id + '">' +
      '<td><span class="u-cell"><span class="avatar">' + esc((u.nickname || u.username).slice(0, 1)) + '</span>' +
        '<span><span class="u-name">' + esc(u.nickname || u.username) + '</span><span class="u-sub">' + esc(u.username) + "</span></span></span></td>" +
      '<td><span class="role-cell">' +
        '<button class="role-pill' + (u.roles && u.roles.length && u.roles[0].name === "admin" ? " is-admin" : "") + '" type="button" data-role-picker>' +
          esc(u.roles && u.roles.length ? u.roles[0].name : "未分配") + '<i data-ic="down"></i></button>' +
        '<span class="role-pop hide">' +
          adminState.roles.map(function (r) {
            return '<span class="role-opt" data-role-opt="' + r.id + '" data-uid="' + u.id + '"><b>' + esc(r.name) + "</b><small>" + esc(r.description || "") + "</small></span>";
          }).join("") +
        "</span></span></td>" +
      '<td><span class="muted" style="font-size:13px;">' + (u.roles && u.roles.length ? "见角色权限" : "未分配") + "</span></td>" +
      '<td><span class="st' + (u.is_active ? "" : " off") + '"><i></i>' + (u.is_active ? "启用" : "停用") + "</span></td>" +
      '<td><span class="muted" style="font-size:13px;">' + esc((u.created_at || "").slice(0, 10) || "—") + "</span></td>" +
      '<td class="t-right"><button class="icon-btn xs" type="button" data-toast="点击成员行查看与设置权限" aria-label="详情" title="详情"><i data-ic="eye"></i></button></td>' +
    "</tr>";
  }
  function renderUsersTab() {
    var tb = qs("[data-u-rows]");
    if (tb) tb.innerHTML = adminState.users.length
      ? adminState.users.map(userRowHtml).join("")
      : '<tr><td colspan="6" class="muted" style="padding:14px;">暂无成员</td></tr>';
  }
  function renderRoleMatrix() {
    var box = qs("[data-role-matrix]");
    if (!box || !adminState.roles.length || !adminState.perms.length) return;
    function has(r, code) {
      return r.permissions.some(function (p) { return p.code === code; });
    }
    var head = adminState.roles.map(function (r) { return "<th>" + esc(r.name) + "</th>"; }).join("");
    var rows = adminState.perms.map(function (p) {
      var cells = adminState.roles.map(function (r) {
        return "<td>" + (has(r, p.code)
          ? '<span class="mx-yes"><i data-ic="check"></i></span>'
          : '<span class="mx-none">—</span>') + "</td>";
      }).join("");
      return "<tr><td>" + esc(p.name) + "</td>" + cells + "</tr>";
    }).join("");
    box.innerHTML = '<table class="table mx-table"><thead><tr><th>权限</th>' + head + "</tr></thead><tbody>" + rows + "</tbody></table>";
  }
  function loadAdminTabData() {
    API.get("/admin/users?page_size=100").then(function (p) {
      adminState.users = (p && p.items) || [];
      renderUsersTab();
    }).catch(function (e) { toast(e.detail || "成员加载失败"); });
    API.get("/admin/roles").then(function (r) {
      adminState.roles = r || [];
      renderUsersTab();
      renderRoleMatrix();
    }).catch(function () {});
    API.get("/admin/permissions").then(function (p) {
      adminState.perms = p || [];
      renderRoleMatrix();
    }).catch(function () {});
    API.get("/admin/models/providers").then(function (p) {
      adminState.providers = p || [];
      renderPvList(adminState.pvDetail ? adminState.pvDetail.id : (p && p.length ? p[0].id : null));
      if (!adminState.pvDetail && p && p.length) selectProvider(p[0].id);
    }).catch(function (e) { toast(e.detail || "提供商加载失败"); });
    API.get("/admin/models/gateway-tokens").then(function (t) {
      /* 列表只展示生效中密钥：已删除的（含种子数据）一律过滤掉 */
      adminState.tokens = (t || []).filter(function (x) { return x.active; });
      renderTokenRows();
    }).catch(function () {});
    API.get("/admin/models/default-route").then(function (d) {
      adminState.defaultRoute = d;
    }).catch(function () {});
    loadAssignments();       // 步 3：模型指派 + 熔断状态
    loadUsage(1);            // 步 3：用量统计（默认近 7 天）
    loadServiceKeys();       // 底座小件：服务 Key 表
  }

  var PAGES = {
    /* ---------- 每日看板 v2（2026-10-24 改版）：信息优先，卡片即跳板 ----------
     * 定位：按应用划分信息板块（板块注册表）；每板块只放「每天值得一眼的信息」（信息纪律）；
     * 整卡 <a> 即跳板，卡头右侧「应用名 →」；保留 grip 拖拽排序 lc_home_order（排序纪律）。
     * 结构：轻问候行（日期 + 时段问候 + 昵称，无全局指标带）+ bento 板块卡片区。
     * 桌面：三板块统一 span-12 全宽横条（宽度一致），卡片内部滚动（main.css 路由规则）；≤900px 单列堆叠。 */
    workspace: function () {
      var skelLines = '<div class="ws-skel"><i></i><i></i><i></i></div>';
      var cards = [
        /* 论文板块（大卡 · 新闻流式「今日推送」）：本期 mock，点标题/整卡 → #/papers */
        '<a class="bcard span-12" href="#/papers" draggable="true" data-bcard="papers">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;"><i data-ic="book"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">今日推送</span></div>' +
          '<span class="bcard-app">文献<i data-ic="arrow"></i></span></div>' +
          '<div class="bcard-body" data-ws-papers>' + skelLines + "</div>" +
        "</a>",
        /* 对话板块（小卡）：昨日对话数（大数字）+ 最近一条会话摘要 */
        '<a class="bcard span-12" href="#/chat" draggable="true" data-bcard="chat">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="chat"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">昨日对话</span></div>' +
          '<div class="bcard-tools">' +
          '<button class="icon-btn xs" type="button" data-new-conv-link aria-label="新建对话" title="新建对话"><i data-ic="edit"></i></button>' +
          '<span class="bcard-app">AI 对话<i data-ic="arrow"></i></span></div></div>' +
          '<div class="bcard-body">' +
            '<div class="ws-chatnum"><b data-ws-ycount>—</b><span>次对话</span></div>' +
            '<div class="bcard-preview" data-ws-lastconv><span class="bp-text muted">加载中…</span></div>' +
          "</div>" +
          '<div class="bcard-foot"><span class="bcard-go">继续聊<i data-ic="arrow"></i></span></div>' +
        "</a>",
        /* 记账板块（横条 span-12）：昨日消费 / 本周消费 / 本月收支 + 近 6 月迷你趋势 */
        '<a class="bcard span-12" href="#/money" draggable="true" data-bcard="money">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="money"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">收支一览</span></div>' +
          '<span class="bcard-app">记账本<i data-ic="arrow"></i></span></div>' +
          '<div class="bcard-body">' +
            '<div class="ws-money">' +
              '<div class="num"><small>昨日消费</small><b class="ex" data-ws-yexp>—</b></div>' +
              '<div class="num"><small>本周消费</small><b class="ex" data-ws-wexp>—</b></div>' +
              '<div class="num"><small>本月收入</small><b class="inc" data-ws-minc>—</b></div>' +
              '<div class="num"><small>本月支出</small><b class="ex" data-ws-mexp>—</b></div>' +
              '<div class="spark-wrap" data-ws-spark></div>' +
            "</div>" +
          "</div>" +
          '<div class="bcard-foot"><span class="bcard-micro" data-ws-moneyfoot>数据按账目日期归属</span></div>' +
        "</a>",
        /* 系统状态板块（步 5 · 底座：状态灯真实化 · GET /status；backup=null → 未配置灰灯。
           Kuma 监控台已按 2026-10-25 拍板拆除（两人自用、价值有限），灯即全部可视信息 */
        '<div class="bcard span-12" draggable="true" data-bcard="status">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;"><i data-ic="gear"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">系统状态</span></div></div>' +
          '<div class="bcard-body" data-ws-status>' + skelLines + "</div>" +
        "</div>"
      ];
      /* 读取拖拽排序缓存（排序纪律：常用在前，lc_home_order 持久化） */
      var order = [];
      try { order = JSON.parse(localStorage.getItem("lc_home_order") || "[]"); } catch (e) { order = []; }
      cards.sort(function (a, b) {
        var ia = order.indexOf(a.match(/data-bcard="(\w+)"/)[1]);
        var ib = order.indexOf(b.match(/data-bcard="(\w+)"/)[1]);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });
      /* 轻问候行：时段问候 + 昵称（data-ws-greet 异步填充）；不放全局指标带 */
      return '' +
        '<div class="greet"><h1 data-ws-greet>你好</h1>' +
        '<span class="date" data-ws-date></span></div>' +
        '<div class="sec-head"><span class="sec-title">每日看板</span>' +
        '<span class="muted" style="font-size:12.5px;">拖拽调整顺序</span></div>' +
        '<div class="bento-grid">' + cards.join("") + "</div>";
    },

    /* ---------- 对话：ChatApp（模型选择器 + 思考强度 + 润色 + Skill 面板；已联调真实 /chat SSE 双流） ---------- */
    chat: function () {
      return '' +
        '<div class="chat-layout">' +
          '<aside class="conv-panel">' +
            '<div class="conv-head"><span class="t">AI 对话</span>' +
            '<button class="icon-btn" type="button" data-new-conv aria-label="新建会话"><i data-ic="plus"></i></button></div>' +
            /* 左侧功能列（P1-3：新建会话/收藏/专家/Skill/MCP；收藏·专家·MCP 维持占位 toast 不动） */
            '<div class="fn-col">' +
              '<button class="fn-item" type="button" data-new-conv><i data-ic="plus"></i><span>新建会话</span></button>' +
              '<button class="fn-item" type="button" data-toast="收藏功能即将上线"><i data-ic="star"></i><span>收藏</span></button>' +
              '<button class="fn-item" type="button" data-toast="专家功能即将上线"><i data-ic="users"></i><span>专家</span></button>' +
              '<button class="fn-item" type="button" data-modal-open="#modal-skillhub"><i data-ic="spark"></i><span>Skill</span></button>' +
              '<button class="fn-item" type="button" data-toast="MCP 功能即将上线"><i data-ic="plug"></i><span>MCP</span></button>' +
            "</div>" +
            '<div class="conv-list" data-conv-list></div>' +
          "</aside>" +
          '<div class="drawer-mask" data-conv-mask></div>' +
          '<div class="chat-main">' +
            '<div class="chat-head">' +
              '<button class="icon-btn" type="button" data-open-conv aria-label="会话列表" id="conv-toggle"><i data-ic="menu"></i></button>' +
              "<span data-chat-title>通用对话</span>" +
              '<a class="icon-btn" href="#/workspace" aria-label="返回工作台" style="margin-left:auto;"><i data-ic="home"></i></a>' +
            "</div>" +
            '<div class="chat-scroll"><div class="chat-inner" data-chat-inner>' +
              '<div class="chat-empty muted" data-chat-empty>开始一段新对话吧</div>' +
            "</div></div>" +
            /* 输入框：参考 WorkBuddy——圆角白卡 + 底部工具条（附件/润色左，模型与发送右） */
            '<div class="composer-wrap">' +
              '<div class="composer">' +
                '<textarea rows="1" placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"></textarea>' +
                '<div class="composer-bar">' +
                  '<button class="icon-btn xs" type="button" data-upload aria-label="上传文件"><i data-ic="clip"></i></button>' +
                  '<button class="icon-btn xs" type="button" data-polish aria-label="AI 润色" title="AI 润色（替换原文，Ctrl+Z 撤销）"><i data-ic="wand"></i></button>' +
                  '<span class="flex-spacer"></span>' +
                  '<div class="mp-wrap">' +
                    '<button class="model-picker" type="button" data-model-picker><span data-mp-label>…</span><i data-ic="down"></i></button>' +
                    '<div class="mp-pop hide" data-mp-pop></div>' +
                  "</div>" +
                  '<button class="send-dark" type="button" data-send aria-label="发送"><i data-ic="send"></i></button>' +
                "</div>" +
              "</div>" +
            "</div>" +
          "</div>" +
        "</div>";
    },

    /* ---------- 记账（已联调真实 /money：账目/统计/AI parse） ---------- */
    money: function () {
      return '' +
        '<div class="page-head"><div><h1 class="page-title">记账本</h1>' +
        '<div class="page-desc" data-money-month>数据按账目日期归属月份</div></div></div>' +
        '<div class="card money-bar">' +
          '<div class="item"><small>本月支出</small><b class="ex" data-m-expense>—</b></div>' +
          '<div class="item"><small>本月收入</small><b class="inc" data-m-income>—</b></div>' +
          '<div class="item"><small>结余</small><b data-m-balance>—</b></div>' +
          '<div class="actions">' +
            '<button class="btn" type="button" data-modal-open="#modal-ai"><i data-ic="spark"></i>AI 记一笔</button>' +
            '<button class="btn" type="button" data-modal-open="#modal-tx"><i data-ic="plus"></i>记一笔</button>' +
          "</div></div>" +
        '<div class="section-title">最近账目</div>' +
        '<div class="card tx-list" data-tx-list><div class="tx-row muted" style="padding:14px 4px;">加载中…</div></div>' +
        '<div class="section-title">月度统计</div>' +
        '<div class="stat-grid">' +
          '<div class="card stat-card"><h3>按分类汇总（支出降序）</h3><div data-by-category></div></div>' +
          '<div class="card stat-card"><h3>近 6 个月趋势</h3><div class="trend" data-trend></div>' +
            '<div class="trend-legend"><span><i style="background:var(--expense);"></i>支出</span><span><i style="background:var(--income);"></i>收入</span></div></div>' +
        "</div>" +
        '<div class="section-title">分类管理</div>' +
        '<div class="card" style="padding:14px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;">' +
          '<div class="chips" style="flex:1;" data-chips data-money-chips><span class="muted" style="font-size:13px;">加载中…</span></div>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-modal-open="#modal-cats"><i data-ic="edit"></i>管理分类</button>' +
        "</div>";
    },

    /* ---------- 应用中心（已联调 GET /apps 注册表；分类分组 + 搜索） ---------- */
    apps: function () {
      return '' +
        '<div class="page-head"><div><h1 class="page-title">应用中心</h1>' +
        '<div class="page-desc">全部应用按分类分组，可搜索</div></div></div>' +
        '<div class="search-bar"><i data-ic="search"></i>' +
        '<input type="search" placeholder="搜索应用名称或描述" data-app-search></div>' +
        '<div data-app-groups><div class="muted" style="padding:14px 4px;">加载中…</div></div>' +
        '<div class="empty-state hide" data-app-empty>没有匹配的应用</div>';
    },

    /* ---------- 文献（步 C 重排，P7 线框：顶栏 digest + 左导航 + 中间卡片流 + 右详情面板；
       参考 Zotero 三栏 / Semantic Scholar 卡片 / SciSpace 详情面板） ---------- */
    papers: function () {
      return '' +
        '<div class="pp-page">' +
          /* 顶栏：今日命中 + 高相关红标 + 更新时间 + 立即检索 + 订阅设置齿轮 */
          '<div class="card pp-topbar">' +
            '<div class="pp-digest">' +
              '<span class="pp-count">今日命中 <b data-pp-total>—</b> 篇</span>' +
              '<span class="pill pp-high hide" data-pp-high></span>' +
              '<span class="pp-updated" data-pp-updated></span>' +
            "</div>" +
            '<div class="pp-actions">' +
              /* P13 本期：自然语言检索（一句话 → AI 扩词 → 临时聚合抓取，防抖 + loading） */
              '<div class="pp-nl">' +
                '<input class="pp-nl-input" type="text" data-pp-nlinput autocomplete="off"' +
                  ' placeholder="语义检索：一句话描述想找的文献，回车检索"' +
                  ' aria-label="语义检索">' +
                '<button class="btn btn-ghost btn-sm pp-nl-btn" type="button" data-pp-nlsearch><i data-ic="spark"></i>语义检索</button>' +
              "</div>" +
              '<button class="btn btn-ghost btn-sm pp-crawl" type="button" data-pp-crawl><i data-ic="refresh"></i>立即检索</button>' +
              '<button class="icon-btn" type="button" data-pp-subscribe aria-label="订阅设置"><i data-ic="gear"></i></button>' +
            "</div>" +
          "</div>" +
          '<div class="pp-body">' +
            /* 左导航（我的笔记 = 灰字占位，后批） */
            '<nav class="card pp-nav">' +
              '<button class="pp-nav-item active" type="button" data-pp-nav="digest"><i data-ic="inbox"></i>今日推送</button>' +
              '<button class="pp-nav-item" type="button" data-pp-nav="favorites"><i data-ic="star"></i>我的收藏</button>' +
              '<button class="pp-nav-item" type="button" data-pp-nav="all"><i data-ic="book"></i>全部论文</button>' +
              /* 轮① P22：「我的笔记」改名「我的文献」，指向一级页 #/library（阅读/批注唯一入口） */
              '<button class="pp-nav-item" type="button" data-pp-libnav><i data-ic="edit"></i>我的文献</button>' +
            "</nav>" +
            /* 中间卡片流（展示设置工具条 P18 + 卡片列） */
            '<div class="pp-list">' +
              '<div class="card pp-toolbar">' +
                '<span class="pp-tb-label">排序</span>' +
                xselectHtml({
                  value: paperState.prefs.sort,
                  placeholder: "时间",
                  options: [
                    { value: "time", label: "时间" },
                    { value: "if", label: "影响因子" },
                    { value: "score", label: "相关度" }
                  ],
                  attrs: 'data-pp-sort',
                  cls: "pp-tb-xsel"
                }) +
                '<span class="pp-tb-label">IF 下限</span>' +
                '<input class="pp-tb-input" type="number" min="0" step="0.1" data-pp-ifmin placeholder="不限"' +
                  ' value="' + (paperState.prefs.if_min != null ? esc(String(paperState.prefs.if_min)) : "") + '" aria-label="影响因子下限">' +
                '<span class="pp-tb-label">展示</span>' +
                '<input class="pp-tb-input pp-tb-num" type="number" min="1" max="500" step="1" data-pp-limit aria-label="展示条数"' +
                  ' value="' + esc(String(paperState.prefs.display_limit)) + '">' +
                '<span class="pp-tb-hint muted">改动即时生效并保存为我的展示偏好</span>' +
              "</div>" +
              '<div class="pp-cards" data-pp-list><div class="muted" style="padding:14px 4px;font-size:13px;">加载中…</div></div>' +
            "</div>" +
            /* 右侧详情面板（点卡片展开；本批不接预览） */
            '<aside class="card pp-detail hide" data-pp-detail></aside>' +
          "</div>" +
        "</div>";
    },

    /* ---------- 我的文献（轮① P22 一级页：阅读/批注/翻译唯一入口）
       P29 改版：导航式重排（参考 Zotero 平板端「库列表→点行进阅读→返回」、Notion
       「全宽列表 vs 阅读」切换）——默认单列全宽文献列表（无选中时不再有大片空白），
       点行进整页阅读视图（左上角「← 返回」回列表并恢复滚动位置）；
       「解析中」tab 保留五段阶段条。 ---------- */
    library: function () {
      return '' +
        '<div class="pp-page lib-page">' +
          '<div class="card pp-topbar">' +
            '<div class="pp-digest">' +
              '<span class="pp-count">我的文献 <b data-lib-count>—</b> 篇</span>' +
              '<span class="pp-updated muted" data-lib-tabhint></span>' +
            "</div>" +
            '<div class="pp-actions">' +
              '<button class="btn btn-sm" type="button" data-lib-import><i data-ic="plus"></i>导入文献</button>' +
              '<button class="pp-nav-item' + (libraryState.tab === "parsing" ? " active" : "") + '" type="button" data-lib-tab="all">全部</button>' +
              '<button class="pp-nav-item' + (libraryState.tab === "parsing" ? " active" : "") + '" type="button" data-lib-tab="parsing">解析中</button>' +
              '<button class="icon-btn" type="button" data-lib-settings title="我的文献设置" aria-label="我的文献设置"><i data-ic="gear"></i></button>' +
            "</div>" +
            /* 轮③ P27：设置小项（自动翻译开关，存 papers_prefs） */
            '<div class="lib-settings hide" data-lib-settingspop>' +
              '<label class="lib-set-row">' +
                '<input type="checkbox" data-lib-autotranslate>' +
                "<span>导入/解析后自动翻译（中英对照）</span>" +
              "</label>" +
              '<div class="muted" style="font-size:12px;margin-top:4px;">开启后，解析完成的文献会自动生成段落级中文对照译文</div>' +
            "</div>" +
          "</div>" +
          '<div class="lib-body">' +
            /* P29：默认态 = 单列全宽列表；阅读态（.is-reading）列表隐藏、阅读器整页 */
            '<div class="card lib-list" data-lib-list><div class="muted" style="padding:14px 4px;font-size:13px;">加载中…</div></div>' +
            '<div class="lib-reader-host hide" data-lib-reader></div>' +
          "</div>" +
        "</div>";
    },

    /* ---------- 平台管理：用户与角色（Supabase 式表格 + 角色矩阵 + 详情抽屉）/ 模型管理（LobeChat 式双栏）/ 网关密钥（已联调 /admin/*） ---------- */
    admin: function () {
      return '' +
        '<div class="page-head"><div><h1 class="page-title">平台管理</h1>' +
        '<div class="page-desc">成员、模型与网关</div></div></div>' +
        '<div class="admin-tabs">' +
          '<button class="admin-tab active" type="button" data-admin-tab="#pane-users"><i data-ic="users" style="vertical-align:-3px;"></i> 用户与角色</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-models"><i data-ic="plug" style="vertical-align:-3px;"></i> 模型管理</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-tokens"><i data-ic="token" style="vertical-align:-3px;"></i> 网关密钥</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-assign"><i data-ic="bot" style="vertical-align:-3px;"></i> 模型指派</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-usage"><i data-ic="chart" style="vertical-align:-3px;"></i> 用量统计</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-keys"><i data-ic="key" style="vertical-align:-3px;"></i> Key 管理</button>' +
        "</div>" +
        /* 用户与角色 */
        '<div class="admin-pane active" id="pane-users">' +
          '<div class="sec-head"><span class="sec-title">成员</span>' +
            '<button class="btn btn-sm" type="button" data-toast="注册开关关闭时暂不可邀请（可用 /admin/users 接口创建）"><i data-ic="plus"></i>邀请成员</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table u-table"><thead>' +
          "<tr><th>成员</th><th>角色</th><th>权限</th><th>状态</th><th>注册时间</th><th></th></tr></thead>" +
          '<tbody data-u-rows><tr><td colspan="6" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
          '<div style="font-size:12.5px;color:var(--ink-3);margin-top:10px;">点击成员行设置权限（应用到其角色）</div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">角色权限</span></div>' +
          '<div class="card role-matrix" style="padding:8px 6px;overflow-x:auto;" data-role-matrix><div class="muted" style="padding:14px;">加载中…</div></div>' +
          /* 成员详情抽屉（Supabase 侧栏模式） */
          '<div class="ud-mask hide" data-ud-mask></div>' +
          '<aside class="udrawer hide" data-udrawer></aside>' +
        "</div>" +
        /* 模型管理（方案 1：左列表 + 右详情） */
        '<div class="admin-pane" id="pane-models">' +
          '<div class="mm-layout">' +
            '<div class="mm-list" id="mm-list"><div class="muted" style="padding:12px;">加载中…</div></div>' +
            '<div class="card mm-detail" id="mm-detail"><div class="muted" style="padding:16px;">加载中…</div></div>' +
          "</div>" +
        "</div>" +
        /* 网关密钥 */
        '<div class="admin-pane" id="pane-tokens">' +
          '<div class="gw-endpoint"><span class="gw-endpoint-label">接入地址</span>' +
            '<code class="mono-mask" id="gw-url">' + esc(API.BASE) + '/gw/v1</code>' +
            '<button class="btn btn-ghost btn-sm" type="button" data-copy-text="#gw-url">复制</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>名称</th><th>密钥</th><th>模型范围</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead>" +
          '<tbody id="gw-token-rows"><tr><td colspan="6" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
          '<button class="btn btn-sm mt8" type="button" data-modal-open="#modal-token"><i data-ic="plus"></i>新建密钥</button>' +
        "</div>" +
        /* 模型指派（步 3 D2：每个应用一条有序模型链——第 1 个是主模型，其余是备用链） */
        '<div class="admin-pane" id="pane-assign">' +
          '<div class="page-desc" style="margin-bottom:12px;">每个应用一条模型链：第 1 个是主模型，其余是备用链，主模型挂了按顺序自动顶上；连挂 3 次自动熔断摘出、恢复后自动切回。</div>' +
          '<div class="sec-head"><span class="sec-title">模型指派</span>' +
            '<button class="btn btn-sm asg-save-all" type="button" data-asg-save-all disabled><span data-asg-save-label>保存全部</span></button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>应用（app_key）</th><th>模型链（第 1 个为主模型，悬停拖拽 ⋮⋮ 排序）</th><th>启用</th></tr></thead>" +
          '<tbody data-asg-rows><tr><td colspan="3" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">熔断状态</span>' +
            '<button class="btn btn-ghost btn-sm" type="button" data-asg-reload>刷新</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>模型</th><th>状态</th><th>连续失败</th><th>下次探测</th><th></th></tr></thead>" +
          '<tbody data-cb-rows><tr><td colspan="5" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
        "</div>" +
        /* 用量统计（步 3 D3：one-api 式 概览卡片 + 表格 + 时间筛选） */
        '<div class="admin-pane" id="pane-usage">' +
          '<div class="usage-filter">' +
            '<input type="datetime-local" data-usage-start aria-label="开始时间">' +
            '<span class="muted">至</span>' +
            '<input type="datetime-local" data-usage-end aria-label="结束时间">' +
            '<button class="btn btn-sm" type="button" data-usage-query><i data-ic="search"></i>查询</button>' +
            '<span class="muted" style="font-size:12.5px;">默认近 7 天；日志无限期保留，可按时段筛选（Q3）</span>' +
          "</div>" +
          '<div class="stat-strip" data-usage-cards></div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">按模型</span></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>模型</th><th>调用</th><th>成功率</th><th>输入 Token</th><th>输出 Token</th><th>费用</th></tr></thead>" +
          '<tbody data-usage-model-rows><tr><td colspan="6" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">按应用</span></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>app_key</th><th>调用</th><th>成功率</th><th>输入 Token</th><th>输出 Token</th><th>费用</th></tr></thead>" +
          '<tbody data-usage-app-rows><tr><td colspan="6" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">调用日志</span>' +
            '<span class="flex-spacer"></span><span class="muted" style="font-size:12.5px;" data-usage-pageinfo></span>' +
            '<button class="btn btn-ghost btn-sm" type="button" data-usage-page="prev">上一页</button>' +
            '<button class="btn btn-ghost btn-sm" type="button" data-usage-page="next">下一页</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>时间</th><th>app_key</th><th>模型</th><th>输入</th><th>输出</th><th>延迟</th><th>结果</th><th>费用</th></tr></thead>" +
          '<tbody data-usage-log-rows><tr><td colspan="8" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
        "</div>" +
        /* 服务 Key 管理（底座小件：异构服务 MinerU/FunASR 等钥匙集中管理，只托管不走网关） */
        '<div class="admin-pane" id="pane-keys">' +
          '<div class="page-desc" style="margin-bottom:12px;">非 LLM 异构服务（MinerU 解析、FunASR 语音、DashScope 等）的钥匙集中托管：后端服务按服务名取钥匙直连厂商，轮换改库即生效。钥匙一律掩码显示，仅新增/编辑时写入完整值。</div>' +
          '<div class="sec-head"><span class="sec-title">服务钥匙</span>' +
            '<button class="btn btn-sm" type="button" data-sk-add><i data-ic="plus"></i>新增钥匙</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>服务名</th><th>厂商</th><th>钥匙</th><th>网址</th><th>备注</th><th>启用</th><th>操作</th></tr></thead>" +
          '<tbody data-sk-rows><tr><td colspan="7" class="muted" style="padding:14px;">加载中…</td></tr></tbody></table></div>' +
        "</div>";
    },

    /* ---------- 我的：三域设置统一入口（通用 / 应用 / 管理） ---------- */
    me: function () {
      var u = LC_USER || { username: "…", nickname: "…", roles: [] };
      var isAdmin = (u.roles || []).indexOf("admin") !== -1;
      return '' +
        '<div class="page-head"><div><h1 class="page-title">我的</h1>' +
        '<div class="page-desc">账号信息、设置与关于</div></div></div>' +
        '<div class="card me-card"><span class="avatar">' + avatarInnerHtml() + "</span>" +
        '<div style="flex:1;"><div class="nick">' + esc(u.nickname || u.username) + '</div><div class="sub">' + esc(u.username) + " · " + (isAdmin ? "管理员" : "成员") + "</div></div>" +
        '<button class="btn btn-ghost btn-sm" type="button" data-logout><i data-ic="logout"></i>退出登录</button></div>' +
        '<div class="section-title">设置</div>' +
        '<div class="card me-list">' +
          '<div class="me-item" role="button" tabindex="0" data-modal-open="#modal-set-general" style="cursor:pointer;">' +
            '<i data-ic="gear"></i><span class="grow">通用设置</span>' +
            '<span class="val">账号与登录</span><i data-ic="arrow" style="color:var(--ink-3);"></i></div>' +
          '<div class="me-item" role="button" tabindex="0" data-modal-open="#modal-set-apps" style="cursor:pointer;">' +
            '<i data-ic="grid"></i><span class="grow">应用设置</span>' +
            '<span class="val">记账 · 对话 · 文献</span><i data-ic="arrow" style="color:var(--ink-3);"></i></div>' +
          '<a class="me-item" href="#/admin">' +
            '<i data-ic="shield"></i><span class="grow">管理设置</span>' +
            '<span class="val">用户 · 模型网关 · 仅管理员</span><i data-ic="arrow" style="color:var(--ink-3);"></i></a>' +
        "</div>" +
        '<div class="section-title">关于</div>' +
        '<div class="card me-list">' +
          '<div class="me-item"><i data-ic="book"></i><span class="grow">应用版本</span><span class="val">LumenCafe 原型 v2 · 第一批（对话 + 记账）</span></div>' +
          '<div class="me-item"><i data-ic="shield"></i><span class="grow">开源计划</span><span class="val">打磨成熟后 MIT 开源</span></div>' +
        "</div>";
    },

    /* ---------- 登录 ---------- */
    login: function () {
      return '' +
        '<div class="login-wrap"><div class="login-card">' +
          '<div class="login-brand"><div class="brand-logo"><i data-ic="logo"></i></div><h1>流光咖啡馆</h1>' +
          "<p>属于我们两个人的 AI 应用面板</p></div>" +
          '<form id="login-form">' +
            '<div class="field"><label for="login-user">用户名</label>' +
            '<input id="login-user" type="text" value="admin" autocomplete="username"></div>' +
            '<div class="field"><label for="login-pass">密码</label>' +
            '<input id="login-pass" type="password" value="" autocomplete="current-password" placeholder="请输入密码"></div>' +
            '<button class="btn btn-block" type="submit">进入咖啡馆</button>' +
            '<div class="login-err hide" data-login-err style="margin-top:10px;color:var(--danger,#d83931);font-size:13px;"></div>' +
          "</form>" +
        "</div></div>";
    }
  };

  /* ================= 对话活数据（/chat 联调） ================= */
  /* 思考档位行（P0-2：按模型 meta.reasoning 动态渲染，标签用官方命名）
   * 三分支：levels 非空 → 档位按钮组；enabled 但 levels 空 → 开/关二态；其余 → 不渲染 */
  function reasoningRowHtml(it) {
    var r = it.reasoning;
    if (!r || !r.enabled) return "";
    var levels = r.levels || [];
    var cur = chatState.thinkingLevel;
    /* 当前选择不属于该模型档位时回落默认档 */
    if (levels.length && cur !== null && !levels.some(function (l) { return l.value === cur; })) {
      cur = r.default_level || null;
    }
    if (!levels.length) {
      if (cur !== "on" && cur !== "off" && cur !== "enabled" && cur !== "disabled") cur = r.default_level || "on";
      return '<div class="mp-reason">' +
        '<span class="mp-reason-label">思考</span>' +
        '<button class="lv-chip' + (cur === "on" || cur === "enabled" ? " active" : "") + '" type="button" data-mp-level="on">开</button>' +
        '<button class="lv-chip' + (cur === "off" || cur === "disabled" ? " active" : "") + '" type="button" data-mp-level="off">关</button>' +
        "</div>";
    }
    return '<div class="mp-reason">' +
      '<span class="mp-reason-label">思考</span>' +
      levels.map(function (l) {
        return '<button class="lv-chip' + (l.value === cur ? " active" : "") + '" type="button" data-mp-level="' + esc(l.value) + '" title="协议值：' + esc(l.value) + '">' + esc(l.label) + "</button>";
      }).join("") +
      "</div>";
  }

  function renderMpPop() {
    var pop = qs("[data-mp-pop]");
    if (!pop) return;
    pop.innerHTML = modelPool().map(function (g) {
      return '<div class="mp-group"><div class="mp-group-label">' + esc(g.provider) + "</div>" +
        g.items.map(function (it) {
          return '<div class="mp-item" data-mp-item="' + it.id + '" role="button" tabindex="0">' +
            '<span class="mp-name">' + esc(it.name) + (it.is_default ? '<span class="pill pill-ok">默认</span>' : "") + "</span>" +
            '<span class="mp-meta">' + (it.context || "") + "</span>" +
            (it.reasoning && it.reasoning.enabled ? '<i class="ic" data-ic="spark" title="支持思考"></i>' : "") +
            (it.files ? '<i class="ic" data-ic="doc" title="支持文件上传"></i>' : "") +
            (it.vision ? '<i class="ic" data-ic="eye" title="支持图片理解"></i>' : "") +
            '<i class="ic mp-check" data-ic="check" style="visibility:hidden;"></i>' +
            reasoningRowHtml(it) + "</div>";
        }).join("") + "</div>";
    }).join("");
    injectIcons(pop);
  }
  function renderConvList(convs) {
    var box = qs("[data-conv-list]");
    if (!box) return;
    chatState.convs = convs || [];
    box.innerHTML = (convs && convs.length)
      ? convs.map(function (c) {
          return '<div class="conv-item' + (c.id === chatState.convId ? " active" : "") + '" data-cid="' + c.id + '"><span class="ct">' + esc(c.title) + '</span><span class="del" data-ic="trash" data-conv-del></span></div>';
        }).join("")
      : '<div class="muted" style="padding:10px 12px;font-size:13px;">暂无会话，发送首条消息自动创建</div>';
    injectIcons(box);
  }
  function refreshConversations(keepCurrent) {
    API.get("/chat/conversations?app_id=chat").then(function (convs) {
      renderConvList(convs || []);
      /* convId=null 可能是用户主动进入的「新建会话」空态（newConv=true），此时不得自动选中；
         仅在未要求保持、或确实无任何选中且非主动空态时回退选中首个会话 */
      if (!keepCurrent || (!chatState.convId && !chatState.newConv)) {
        var first = (convs || [])[0];
        if (first) selectConversation(first.id, first.title);
      }
    }).catch(function () {});
  }
  function selectConversation(id, title) {
    chatState.convId = id;
    chatState.newConv = false;
    var t = qs("[data-chat-title]");
    if (t) t.textContent = title || "对话";
    qsa(".conv-item").forEach(function (i) {
      i.classList.toggle("active", parseInt(i.getAttribute("data-cid"), 10) === id);
    });
    API.get("/chat/history?app_id=chat&conversation_id=" + id).then(function (h) {
      renderChatMessages((h && h.messages) || []);
    }).catch(function (e) { toast(e.detail || "历史加载失败"); });
  }
  /* 思维面板折叠态记忆：仅记最后一条消息是否展开（N-增3，本机 localStorage） */
  function thinkOpenPref() {
    try { return localStorage.getItem("lc_think_open") === "1"; } catch (e) { return false; }
  }
  function saveThinkOpenPref(open) {
    try { localStorage.setItem("lc_think_open", open ? "1" : "0"); } catch (e) {}
  }
  /* 思维面板 HTML（历史消息态：无耗时数据则不显示秒数） */
  function thinkBoxHtml(reasoning, isLast) {
    if (!reasoning) return "";
    var open = isLast && thinkOpenPref();
    return '<div class="think-box' + (open ? " open" : "") + '"' + (isLast ? " data-think-last" : "") + ">" +
      '<div class="think-head" data-think-toggle role="button" tabindex="0">' +
      '<i data-ic="spark"></i><span class="think-title">已深度思考</span>' +
      '<i data-ic="down" class="think-caret"></i></div>' +
      '<div class="think-body' + (open ? "" : " hide") + '"><p></p></div></div>';
  }
  function renderChatMessages(messages) {
    var inner = qs("[data-chat-inner]");
    if (!inner) return;
    var lastIdx = -1;
    messages.forEach(function (m, i) { if (m.role === "assistant") lastIdx = i; });
    inner.innerHTML = messages.map(function (m, i) {
      var isAi = m.role === "assistant";
      var think = isAi ? thinkBoxHtml(m.reasoning, i === lastIdx) : "";
      return '<div class="msg ' + (isAi ? "ai" : "user") + '"><span class="avatar">' + (isAi ? '<i data-ic="bot"></i>' : avatarInnerHtml()) + "</span>" +
        '<div class="msg-body">' + think + '<div class="msg-text"><p>' + esc(m.content) + "</p></div></div></div>";
    }).join("");
    /* 思维全文以纯文本填充（防注入，保持换行） */
    qsa(".think-box", inner).forEach(function (box) {
      var msg = messages.filter(function (m) { return m.role === "assistant"; });
      var idx = qsa(".msg.ai", inner).indexOf(box.closest(".msg"));
      var body = box.querySelector(".think-body p");
      if (body && msg[idx]) body.textContent = msg[idx].reasoning || "";
    });
    injectIcons(inner);
    var sc = qs(".chat-scroll");
    if (sc) sc.scrollTop = sc.scrollHeight;
  }

  /* ================= 我的技能（中央弹窗 #modal-skillhub：上传 SKILL.md / 搜索过滤 / 开关 / 卸载） ================= */
  var mySkillsCache = []; /* 已安装技能全量（缓存，搜索框本地过滤） */
  var skillFilterQ = "";
  function loadMySkills() {
    var body = qs("[data-myskills-body]");
    if (!body) return;
    body.innerHTML = '<div class="muted" style="padding:12px 0;font-size:13px;">加载中…</div>';
    API.skills.mine().then(function (list) {
      mySkillsCache = list || [];
      renderMySkills();
    }).catch(function () {
      body.innerHTML = '<div class="muted" style="padding:12px 0;font-size:13px;">加载失败，请稍后重试</div>';
    });
  }
  function renderMySkills() {
    var body = qs("[data-myskills-body]");
    if (!body) return;
    var countEl = qs("[data-skill-count]");
    if (countEl) countEl.textContent = mySkillsCache.length ? mySkillsCache.length + " 个技能" : "未安装";
    var q = (skillFilterQ || "").toLowerCase();
    var list = q ? mySkillsCache.filter(function (s) {
      return (s.name || "").toLowerCase().indexOf(q) !== -1 ||
        (s.description || "").toLowerCase().indexOf(q) !== -1;
    }) : mySkillsCache;
    body.innerHTML = list.length ? list.map(function (s) {
      /* 来源徽标 + 存放位置：skillhub=平台安装；local-upload=本地上传；local=手工包（只读） */
      var isLocal = s.source === "local";
      var srcLabel = s.source === "local" ? "本地" : (s.source === "local-upload" ? "本地上传" : "SkillHub");
      var metaLine = '<span class="pill ' + (isLocal ? "pill-mute" : "pill-ok") + '">' + srcLabel + "</span>" +
        (s.path ? '<code class="myskill-path">' + esc(s.path) + "</code>" : "");
      return '<div class="tx-row" style="padding:10px 0;align-items:flex-start;">' +
        '<span class="skill-ico" style="width:28px;height:28px;"><i data-ic="' + esc(s.icon || "spark") + '"></i></span>' +
        '<span class="grow" style="min-width:0;"><div class="cat">' + esc(s.name) + "</div>" +
        '<div class="note">' + esc(s.description || "") + "</div>" +
        '<div class="myskill-meta">' + metaLine + "</div></span>" +
        (isLocal
          ? '<span class="muted" style="font-size:12px;flex:none;">只读</span>'
          : '<button class="switch' + (s.enabled ? " on" : "") + '" type="button" role="switch" aria-checked="' + (s.enabled ? "true" : "false") + '" data-myskill-toggle="' + s.id + '" data-enabled="' + (s.enabled ? "1" : "0") + '" aria-label="启用该技能"></button>' +
            '<button class="btn btn-danger-ghost btn-sm" type="button" data-myskill-del="' + s.id + '">卸载</button>') +
        "</div>";
    }).join("") : (q
      ? '<div class="muted" style="padding:14px 0;font-size:13px;">没有匹配的技能</div>'
      : '<div class="muted" style="padding:14px 0;font-size:13px;">还没有技能，点击上方上传 SKILL.md</div>');
    injectIcons(body);
  }
  /* 上传技能：仅 .md、≤64KB（后端再校验一遍）；FormData 直传，成功后刷新列表 */
  var skillUploading = false;
  function handleSkillFile(input) {
    var file = input.files && input.files[0];
    input.value = ""; /* 清空，允许再次选择同一文件 */
    if (!file || skillUploading) return;
    if (!/\.md$/i.test(file.name)) { toast("请选择 .md 技能文件"); return; }
    if (file.size > 64 * 1024) { toast("文件超过 64KB，请精简后再上传"); return; }
    skillUploading = true;
    var btn = qs("[data-skill-upload]");
    if (btn) btn.classList.add("is-loading");
    API.skills.upload(file).then(function (d) {
      toast("技能已安装到 " + ((d && d.path) || "skills/"));
      loadMySkills();
    }).catch(function (e) {
      toast((e && e.detail) || "上传失败，请重试");
    }).then(function () {
      skillUploading = false;
      if (btn) btn.classList.remove("is-loading");
    });
  }

  /* ================= 润色（P0-3：composer 魔棒；替换原文 + 可撤销一次） ================= */
  var polishBusy = false;
  var polishBackup = null; /* {text, sel}：上一次润色前的原文，Ctrl+Z 恢复 */
  function syncPolishBtn() {
    var btn = qs("[data-polish]");
    var ta = qs(".composer textarea");
    if (!btn || !ta) return;
    var len = ta.value.trim().length;
    var ok = len > 0 && len <= 4000 && !polishBusy;
    btn.classList.toggle("is-disabled", !ok);
  }
  function autoGrowComposer(ta) {
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
  }
  function doPolish(btn) {
    var ta = qs(".composer textarea");
    if (!ta || polishBusy) return;
    var text = ta.value.trim();
    if (!text || text.length > 4000) return;
    polishBusy = true;
    syncPolishBtn();
    btn.classList.add("is-loading");
    API.polish(text).then(function (d) {
      /* 直接替换输入框原文、不自动发送；备份原文支持 Ctrl+Z 撤销一次 */
      polishBackup = { text: ta.value, sel: ta.selectionStart || 0 };
      ta.value = (d && d.polished) || text;
      autoGrowComposer(ta);
      ta.focus();
      toast("已润色，Ctrl+Z 撤销");
    }).catch(function (e) {
      toast((e && e.detail) || "润色失败，原文未改动");
    }).then(function () {
      polishBusy = false;
      btn.classList.remove("is-loading");
      syncPolishBtn();
    });
  }

  /* ================= 记账活数据（/money 联调） ================= */
  var moneyCats = []; /* [{id, name, kind, built_in}] */
  var aiDraft = null; /* AI 记一笔解析草稿 */
  function monthNow() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }
  function catName(cid) {
    var c = moneyCats.filter(function (x) { return x.id === cid; })[0];
    return c ? c.name : "未分类";
  }
  function renderMoneyChips(view) {
    var box = qs("[data-money-chips]", view || undefined);
    if (!box) return;
    box.innerHTML = moneyCats.map(function (c, i) {
      return '<button class="chip' + (i === 0 ? " active" : "") + '" type="button">' + esc(c.name) + "</button>";
    }).join("") || '<span class="muted" style="font-size:13px;">暂无分类</span>';
  }
  function renderTxCatChips() {
    var box = qs("[data-tx-cats]");
    if (!box) return;
    var wantIncome = qs("#modal-tx .seg button.active") && qs("#modal-tx .seg button.active").textContent.trim() === "收入";
    var kinds = wantIncome ? ["income", "both"] : ["expense", "both"];
    var list = moneyCats.filter(function (c) { return kinds.indexOf(c.kind) !== -1; });
    box.innerHTML = list.map(function (c, i) {
      return '<button class="chip' + (i === 0 ? " active" : "") + '" type="button" data-cid="' + c.id + '" data-kind="' + c.kind + '">' + esc(c.name) + "</button>";
    }).join("") || '<span class="muted" style="font-size:13px;">暂无可用分类</span>';
  }
  function renderCatsModal() {
    var body = qs("#cats-body");
    if (!body) return;
    body.innerHTML = moneyCats.map(function (c) {
      var note = c.built_in ? "预置 · 可改名 / 可隐藏 / 不可删除" : "自定义分类";
      var btn = c.built_in
        ? '<button class="btn btn-ghost btn-sm" type="button" data-toast="预置分类不可删除">删除</button>'
        : '<button class="btn btn-danger-ghost btn-sm" type="button" data-del-cat="' + c.id + '">删除</button>';
      return '<div class="tx-row" style="padding:10px 0;"><span class="grow"><div class="cat">' + esc(c.name) + '</div>' +
        '<div class="note">' + note + "</div></span>" + btn + "</div>";
    }).join("") +
      '<div class="field mt16" style="margin-bottom:0;"><label>新建分类</label>' +
      '<input type="text" data-new-cat-name placeholder="分类名称，如：宠物"></div>';
  }
  function loadMoneyPage(view) {
    view = view || qs("#view");
    var mm = monthNow();
    var monthEl = qs("[data-money-month]", view);
    if (monthEl) monthEl.textContent = mm.slice(0, 4) + " 年 " + parseInt(mm.slice(5), 10) + " 月 · 数据按账目日期归属月份";
    var dateInput = qs("[data-tx-date]");
    if (dateInput && !dateInput.value) dateInput.value = mm + "-" + String(new Date().getDate()).padStart(2, "0");

    API.get("/money/categories").then(function (cats) {
      moneyCats = cats || [];
      renderMoneyChips(view);
      renderTxCatChips();
      renderCatsModal();
    }).catch(function (e) { toast(e.detail || "分类加载失败"); });

    API.get("/money/stats/monthly?month=" + mm).then(function (s) {
      var e1 = qs("[data-m-expense]"); if (e1) e1.textContent = fenShort(s.expense_total);
      var e2 = qs("[data-m-income]"); if (e2) e2.textContent = fenShort(s.income_total);
      var e3 = qs("[data-m-balance]"); if (e3) e3.textContent = fenShort(s.balance);
      var byCat = qs("[data-by-category]");
      if (byCat) {
        if (!s.by_category || !s.by_category.length) {
          byCat.innerHTML = '<div class="muted" style="font-size:13px;padding:8px 0;">本月暂无支出</div>';
        } else {
          var max = Math.max.apply(null, s.by_category.map(function (c) { return c.total; }));
          byCat.innerHTML = s.by_category.map(function (c) {
            return '<div class="bar-row"><span class="lbl">' + esc(c.name) + '</span>' +
              '<span class="track"><span class="fill" style="width:' + Math.round((c.total / max) * 100) + '%"></span></span>' +
              '<span class="val">' + fenShort(c.total) + '<span class="muted" style="font-weight:400"> · ' + c.count + "笔</span></span></div>";
          }).join("");
        }
      }
    }).catch(function (e) { toast(e.detail || "统计加载失败"); });

    API.get("/money/stats/trend?months=6").then(function (s) {
      var trendEl = qs("[data-trend]");
      if (!trendEl) return;
      var months = (s && s.months) || [];
      var tMax = Math.max.apply(null, months.map(function (m) { return Math.max(m.expense_total, m.income_total); }).concat([1]));
      trendEl.innerHTML = months.map(function (m) {
        return '<div class="col"><span class="bars">' +
          '<span class="bar ex" style="height:' + Math.max(3, Math.round((m.expense_total / tMax) * 100)) + '%" title="支出 ' + fen(m.expense_total) + '"></span>' +
          '<span class="bar inc" style="height:' + Math.max(3, Math.round((m.income_total / tMax) * 100)) + '%" title="收入 ' + fen(m.income_total) + '"></span>' +
          '</span><span class="cap">' + m.month.slice(5) + "月</span></div>";
      }).join("");
    }).catch(function () {});

    API.get("/money/transactions?page_size=6").then(function (p) {
      var txEl = qs("[data-tx-list]");
      if (!txEl) return;
      var items = (p && p.items) || [];
      txEl.innerHTML = items.length ? items.map(function (t) {
        var sign = t.type === "expense" ? "-" : "+";
        var md = t.date.slice(5).replace("-", "/");
        return '<div class="tx-row"><span class="date">' + md + '</span>' +
          '<span class="grow"><div class="cat">' + esc(catName(t.category_id)) + "</div>" +
          (t.note ? '<div class="note">' + esc(t.note) + "</div>" : "") + "</span>" +
          '<span class="amt ' + t.type + '">' + sign + fenShort(t.amount) + "</span></div>";
      }).join("") : '<div class="muted" style="padding:14px 4px;font-size:13px;">本月还没有账目，点「记一笔」开始</div>';
    }).catch(function () {});
  }

  /* ================= 工作台活数据（/chat /money /admin 联调） ================= */
  /* 步 5 · 系统状态灯（gethomepage 风格三点灯：api / db / backup） */
  function statusLampsHtml(s) {
    function row(ok, name, sub, mut) {
      var dot = mut
        ? '<span class="status-dot"></span>'
        : '<span class="status-dot' + (ok ? " on" : " err") + '"></span>';
      return '<div class="ws-lamp">' + dot +
        '<span class="ws-lamp-name">' + esc(name) + "</span>" +
        '<span class="ws-lamp-sub">' + esc(sub || "") + "</span></div>";
    }
    var rows = row(s.api !== false, "API 服务", "v" + (s.version || "—"));
    rows += row(s.db === true, "数据库", s.db ? "连接正常" : "探活失败");
    if (!s.backup) {
      /* backup=null：backup_state 卷未挂载/无 last_run.json → 未配置灰灯 */
      rows += row(false, "备份", "未配置", true);
    } else {
      var b = s.backup;
      var when = (b.at || "").replace("T", " ").slice(5, 16);
      rows += row(b.succeeded === true, "备份",
        b.succeeded ? "上次成功 " + when : when + " · " + (b.error || "失败"));
    }
    return '<div class="ws-lamps">' + rows + "</div>";
  }

  function fillWorkspace(view) {
    view = view || qs("#view");
    /* 轻问候行：日期 + 时段问候 + 昵称 */
    var d = new Date();
    var wk = ["日", "一", "二", "三", "四", "五", "六"][d.getDay()];
    var dEl = qs("[data-ws-date]", view);
    if (dEl) dEl.textContent = (d.getMonth() + 1) + "月" + d.getDate() + "日 星期" + wk;
    var h = d.getHours();
    var greetWord = h < 6 ? "凌晨好" : h < 12 ? "上午好" : h < 18 ? "下午好" : "晚上好";
    var nick = (LC_USER && (LC_USER.nickname || LC_USER.username)) || "朋友";
    var gEl = qs("[data-ws-greet]", view);
    if (gEl) gEl.textContent = greetWord + "，" + nick;

    /* 记账板块：昨日/本周支出 + 本月收支（真数据 · GET /money/stats/summary） */
    API.get("/money/stats/summary").then(function (s) {
      function set(sel, v) { var el = qs(sel, view); if (el) el.textContent = v; }
      set("[data-ws-yexp]", fenShort(s.yesterday_expense || 0));
      set("[data-ws-wexp]", fenShort(s.week_expense || 0));
      set("[data-ws-minc]", fenShort(s.month_income || 0));
      set("[data-ws-mexp]", fenShort(s.month_expense || 0));
      var foot = qs("[data-ws-moneyfoot]", view);
      if (foot) {
        var hasAny = (s.yesterday_expense || s.week_expense || s.month_income || s.month_expense);
        foot.textContent = hasAny ? "数据按账目日期归属" : "还没有账目，点卡片记一笔";
      }
    }).catch(function () {
      var foot = qs("[data-ws-moneyfoot]", view);
      if (foot) foot.textContent = "记账数据加载失败，点卡片重试";
    });
    /* 记账板块：近 6 月支出迷你趋势 */
    API.get("/money/stats/trend?months=6").then(function (s) {
      var box = qs("[data-ws-spark]", view);
      if (!box || !s || !s.months || !s.months.length) return;
      var exp = s.months.map(function (m2) { return m2.expense_total; });
      if (exp.every(function (v) { return v === 0; })) {
        box.innerHTML = '<span class="muted" style="font-size:12px;">近 6 月暂无支出</span>';
        return;
      }
      box.innerHTML = sparkline(exp, "ex") + "<small>近 6 月支出</small>";
    }).catch(function () {});

    /* 对话板块：昨日对话数 + 最近一条会话（GET /chat/conversations/summary） */
    API.get("/chat/conversations/summary?app_id=chat").then(function (s) {
      var cnt = qs("[data-ws-ycount]", view);
      if (cnt) cnt.textContent = (s && s.yesterday_count) || 0;
      var box = qs("[data-ws-lastconv]", view);
      if (!box) return;
      var last = s && s.latest;
      box.innerHTML = last
        ? '<span class="bp-text">' + esc(last.title) + '</span><span class="bp-time">' + esc((last.updated_at || "").slice(5, 16).replace("T", " ")) + "</span>"
        : '<span class="bp-text muted">还没有对话，点卡片开始聊聊</span>';
    }).catch(function () {
      var box = qs("[data-ws-lastconv]", view);
      if (box) box.innerHTML = '<span class="bp-text muted">对话数据加载失败，点卡片重试</span>';
    });

    /* 论文板块：今日推送（本期 mock · API.papers.feed；真接口第二批 n8n 接入） */
    API.papers.feed(6).then(function (items) {
      var box = qs("[data-ws-papers]", view);
      if (!box) return;
      if (items && items.length) {
        box.innerHTML = '<div class="ws-feed">' + items.map(function (p) {
          return '<div class="ws-feed-row">' +
            '<span class="ft">' + esc(p.title) + "</span>" +
            '<span class="fm">' + esc(p.journal || "") + (p.time ? " · " + esc(p.time) : "") + "</span>" +
          "</div>";
        }).join("") + "</div>";
      } else {
        /* 空态：订阅关键词后每天推送 + 跳应用设置入口 */
        box.innerHTML = '<div class="ws-empty"><span class="t">订阅关键词后每天推送</span>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-ws-paper-settings>去设置<i data-ic="arrow"></i></button></div>';
        injectIcons(box);
      }
    }).catch(function () {
      var box = qs("[data-ws-papers]", view);
      if (box) box.innerHTML = '<div class="ws-empty"><span class="t muted">推送加载失败，点卡片重试</span></div>';
    });

    /* 系统状态灯（步 5：真数据 · GET /status；失败留白底提示不影响其他卡片） */
    API.status().then(function (s) {
      var box = qs("[data-ws-status]", view);
      if (!box || !s) return;
      box.innerHTML = statusLampsHtml(s);
    }).catch(function () {
      var box = qs("[data-ws-status]", view);
      if (box) box.innerHTML = '<span class="muted" style="font-size:13px;">状态加载失败，刷新重试</span>';
    });
  }

  /* ================= 应用中心活数据（GET /apps 注册表） ================= */
  function appRowHtml(a) {
    return '<div class="app-row" data-app-open="' + esc(a.id) + '" role="button" tabindex="0">' +
      '<span class="ico-box" style="background:' + esc(a.color || "#f0f6ff") + ';color:#1664ff;"><i data-ic="' + esc(a.icon || "grid") + '"></i></span>' +
      '<div class="grow"><div class="name">' + esc(a.name) + "</div>" +
      '<div class="desc">' + esc(a.desc || "") + "</div></div>" +
      '<div class="ops"><button class="btn btn-ghost btn-sm" type="button">打开</button></div></div>';
  }
  function renderAppsPage(view) {
    API.get("/apps").then(function (d) {
      var apps = ((d && d.apps) || []).filter(function (a) { return !a.hidden; });
      var cats = (d && d.categories) || [];
      var catName = {};
      cats.forEach(function (c) { catName[c.id] = c.name; });
      var byCat = {};
      apps.forEach(function (a) {
        var k = a.category_id == null ? 0 : a.category_id;
        (byCat[k] = byCat[k] || []).push(a);
      });
      var keys = Object.keys(byCat);
      var groups = keys.map(function (k) {
        return '<div class="app-group"><div class="app-group-title">' + esc(k === "0" ? "未分类" : (catName[k] || "分类 " + k)) + "</div>" +
          byCat[k].map(appRowHtml).join("") + "</div>";
      }).join("");
      var box = qs("[data-app-groups]", view);
      if (box) {
        box.innerHTML = groups || '<div class="muted" style="padding:14px 4px;">注册表暂无应用</div>';
        injectIcons(box);
      }
    }).catch(function (e) { toast(e.detail || "应用加载失败"); });
  }

  /* ================= 文献页活数据（步 C 三栏骨架；digest / daily / favorites 三源） ================= */
  var paperState = {
    nav: "digest", items: [], digest: null, crawlBusy: false,
    /* P18 展示设置 + P21 抓取期过滤参数（同一份 papers_prefs，拍板 P21）
     * 轮③ P27：auto_translate（导入/解析后自动中英对照翻译，默认关） */
    prefs: {
      display_limit: 50, sort: "time", if_min: null,
      year_from: null, year_to: null, authors: [],
      auto_translate: false
    },
    saved: {},        // P19：paper_id -> bool，今日推送/我的收藏双列表共享收藏态
    lib: {},          // 轮① P22：paper_id -> bool，「我的文献」在库态（卡片/详情按钮 ✓ 已在库）
    libLoaded: false, // 在库态是否已拉取（GET /papers/library 一次，之后本地增量维护）
    prefsLoaded: false
  };

  /* ================= 轮①：我的文献工作区（P22 一级页 #/library） =================
   * 阅读/批注/翻译的唯一入口（拍板 P22）；三栏 = 左文献列表 / 中阅读器（复用 P8
   * 批注阅读器，挂载态）/ 右批注栏（阅读器内建）。删除 = 级联删（拍板 P24）。 */
  var libraryState = {
    items: [],          // GET /papers/library 条目（LibraryItemOut）
    parsingItems: [],   // 轮② P26：GET /papers/library/parsing（解析中 tab 数据源）
    tab: "all",         // all | parsing（解析中 tab：五段阶段条）
    currentId: 0,       // 当前在阅读视图中打开的文献
    scrollY: 0          // P29：进入阅读视图前保存的列表滚动位置（返回时恢复）
  };

  var PP_IF_TIP = "影响因子近似口径：OpenAlex 引文影响指标 FWCI（字段加权引用影响，非 JCR 官方值）";
  /* IF≈ 徽标：常驻可见的「?」角标（口径说明不再只藏在 tooltip 里） */
  function _ifBadge(v) {
    return '<span class="pp-if" title="' + esc(PP_IF_TIP) + '">IF≈' + esc(String(v)) +
      '<sup class="pp-if-q" aria-label="影响因子为近似口径，仅供参考">?</sup></span>';
  }

  var PP_NAV_EMPTY = {
    digest: "今日暂无命中：点右上角「⚙ 订阅设置」配置关键词与数据源，再「⟳ 立即检索」跑一轮",
    favorites: "还没有收藏文献：点卡片上的 ☆ 即可收藏",
    all: "暂无文献：先配置订阅，再点「立即检索」抓一轮",
    notes: "还没有已解析的笔记：打开文献详情，点「★ 收藏并解析」，完成后会出现在这里"
  };
  /* 数据源 key → 徽标名（GET /papers/sources 同集） */
  var PP_SRC_NAMES = { pubmed: "PubMed", arxiv: "arXiv", openalex: "OpenAlex", semantic_scholar: "S2", doaj: "DOAJ" };
  function _srcName(key) { return PP_SRC_NAMES[key] || key || ""; }
  /* PaperOut 无 source 字段：从全局去重键前缀推导（pmid 列 = source:external_id） */
  function _srcFromPmid(pmid) {
    var i = String(pmid || "").indexOf(":");
    return i > 0 ? String(pmid).slice(0, i) : (String(pmid || "").match(/^\d+$/) ? "pubmed" : "");
  }

  function _paperAuthors(authors) {
    if (!authors || !authors.length) return "";
    var s = authors.slice(0, 3).join(", ");
    return authors.length > 3 ? s + " 等" : s;
  }
  /* 卡片/详情元数据行（P15）：作者(前2+等) · 期刊 · 年份 · 被引 N · IF≈x.x（近似带 tooltip） */
  function _paperMetaLine(v) {
    var parts = [];
    var auth = v.authors || [];
    if (auth.length) parts.push(esc(auth.slice(0, 2).join(", ")) + (auth.length > 2 ? " 等" : ""));
    if (v.journal) parts.push(esc(v.journal));
    if (v.year) parts.push(esc(String(v.year)));
    if (v.cited_count != null) parts.push("被引 " + esc(String(v.cited_count)));
    if (v.if_approx != null) {
      parts.push(_ifBadge(v.if_approx));
    }
    return parts.join(" · ");
  }
  /* digest 条目（DigestItemOut，无摘要字段）→ 卡片统一视图 */
  function _digestCardView(it) {
    return {
      id: it.paper_id, title: it.title, source: it.source,
      year: it.year, url: it.url || "", matched: it.matched_keywords || [],
      hi: !!it.is_high_relevance, abstract: "", saved: !!it.saved,
      authors: it.authors || [], journal: it.journal || "",
      cited_count: it.cited_count == null ? null : it.cited_count,
      if_approx: it.if_approx == null ? null : it.if_approx
    };
  }
  /* 列表接口条目（PaperOut）→ 卡片统一视图 */
  function _paperCardView(p) {
    return {
      id: p.id, title: p.title, source: _srcFromPmid(p.pmid),
      year: p.pub_date ? String(p.pub_date).slice(0, 4) : null,
      url: p.doi ? ("https://doi.org/" + p.doi) : "", matched: p.tags || [], hi: false,
      abstract: p.abstract || "", saved: !!p.saved,
      authors: p.authors || [], journal: p.journal || "",
      cited_count: p.cited_count == null ? null : p.cited_count,
      if_approx: p.if_approx == null ? null : p.if_approx
    };
  }

  /* 顶栏 digest 摘要（今日命中 N 篇 · M 篇高相关 · 已更新于 HH:MM） */
  function renderDigestBar() {
    var totalEl = qs("[data-pp-total]"), highEl = qs("[data-pp-high]"), updEl = qs("[data-pp-updated]");
    if (!totalEl) return;
    var d = paperState.digest;
    if (!d) { totalEl.textContent = "—"; if (updEl) updEl.textContent = ""; if (highEl) highEl.classList.add("hide"); return; }
    totalEl.textContent = String(d.total_today);
    if (highEl) {
      var hc = d.high_relevance_count || 0;
      highEl.textContent = hc + " 篇高相关";
      highEl.classList.toggle("hide", hc <= 0);
    }
    if (updEl) {
      updEl.textContent = d.last_run_at ? "已更新于 " + String(d.last_run_at).slice(11, 16) : "今日尚未抓取";
      if (d.last_run_status === "failed") updEl.textContent += " · 上轮抓取失败";
    }
  }
  function refreshDigestBar() {
    API.get("/papers/digest").then(function (d) { paperState.digest = d; renderDigestBar(); }).catch(function () {});
  }

  /* 中间卡片流：标题 + 来源徽标 + 高相关红标 + 年份 + 元数据行 + 两行摘要 + 操作行（收藏/下载占位/解读） */
  function paperCardHtml(v) {
    var kws = v.matched.slice(0, 4).map(function (k) { return '<span class="pill pill-mute">' + esc(k) + "</span>"; }).join("");
    if (v.matched.length > 4) kws += '<span class="pill pill-mute">+' + (v.matched.length - 4) + "</span>";
    var src = v.source ? '<span class="pp-src">' + esc(_srcName(v.source)) + "</span>" : "";
    var hi = v.hi ? '<span class="pill pp-hi">高相关</span>' : "";
    var year = v.year ? '<span class="pp-year">' + esc(String(v.year)) + "</span>" : '<span class="pp-year"></span>';
    var metaLine = _paperMetaLine(v);
    /* P19 双列表共享收藏态：savedMap 优先于卡片自带快照 */
    var isSaved = paperState.saved[v.id] !== undefined ? !!paperState.saved[v.id] : !!v.saved;
    /* 轮① P22：我的文献在库态（libMap 底账，加入后即时 ✓） */
    var inLib = !!paperState.lib[v.id];
    return '<article class="pp-card" data-pp-card="' + v.id + '" role="button" tabindex="0">' +
      '<div class="pp-card-head">' + src + hi + year + "</div>" +
      '<h3 class="pp-card-title">' + esc(v.title) + "</h3>" +
      (metaLine ? '<div class="pp-card-meta">' + metaLine + "</div>" : "") +
      '<p class="pp-card-abs' + (v.abstract ? "" : " is-loading") + '" data-pp-abs="' + v.id + '">' +
        (v.abstract ? esc(v.abstract) : "摘要加载中…") + "</p>" +
      (kws ? '<div class="pp-card-kws">' + kws + "</div>" : "") +
      '<div class="pp-card-ops">' +
        '<button class="pp-op' + (isSaved ? " is-on" : "") + '" type="button" data-paper-save="' + v.id + '">' +
          '<i data-ic="star"></i>' + (isSaved ? "已收藏" : "收藏") + "</button>" +
        '<button class="pp-op' + (inLib ? " is-on" : "") + '" type="button" data-paper-lib="' + v.id + '">' +
          '<i data-ic="book"></i>' + (inLib ? "✓ 已在库" : "＋ 我的文献") + "</button>" +
        '<button class="pp-op is-disabled" type="button" data-pp-dl="' + v.id + '" title="下批开放">' +
          '<i data-ic="dl"></i>下载</button>' +
        '<button class="pp-op" type="button" data-paper-explain="' + v.id + '">' +
          '<i data-ic="spark"></i>解读</button>' +
      "</div>" +
    "</article>";
  }
  function renderPaperCards() {
    var box = qs("[data-pp-list]");
    if (!box) return;
    if (!paperState.items.length) {
      /* digest 空态分两种：最近一轮检索无新命中（窗口口径，给 HH:MM）vs 尚未配置/抓取 */
      var emptyText = PP_NAV_EMPTY[paperState.nav] || PP_NAV_EMPTY.all;
      var dg = paperState.digest;
      if (paperState.nav === "digest" && dg && dg.last_run_at && !(dg.total_today > 0)) {
        emptyText = "最近一轮检索（" + String(dg.last_run_at).slice(11, 16) + "）无新命中：" +
          "点「⟳ 立即检索」可再跑一轮，或放宽订阅关键词";
      }
      box.innerHTML = '<div class="card" style="padding:22px;"><div class="muted" style="font-size:13.5px;">' +
        emptyText + "</div></div>";
      return;
    }
    box.innerHTML = paperState.items.map(paperCardHtml).join("");
    injectIcons(box);
    /* digest 卡片不带摘要字段：逐卡懒加载补摘要（异步填槽，不挡列表渲染） */
    if (paperState.nav === "digest") {
      paperState.items.slice(0, 30).forEach(function (v) {
        API.get("/papers/" + v.id).then(function (p) {
          var el = qs('[data-pp-abs="' + v.id + '"]');
          if (!el) return;
          el.textContent = (p && p.abstract) ? p.abstract : "（无摘要）";
          el.classList.remove("is-loading");
        }).catch(function () {
          var el2 = qs('[data-pp-abs="' + v.id + '"]');
          if (el2) { el2.textContent = "（摘要加载失败）"; el2.classList.remove("is-loading"); }
        });
      });
    }
  }
  /* 展示偏好 → 查询串（P18：sort/limit 恒带；if_min 仅设置时带，空=不限） */
  function _prefsQuery() {
    var p = paperState.prefs;
    var s = "?sort=" + encodeURIComponent(p.sort) +
            "&limit=" + encodeURIComponent(String(p.display_limit));
    if (p.if_min != null && p.if_min !== "") s += "&if_min=" + encodeURIComponent(String(p.if_min));
    return s;
  }
  /* P19：把当前列表条目的收藏快照并入共享 savedMap（详情/操作行以 map 为准） */
  function _syncSavedFromItems() {
    paperState.items.forEach(function (v) { paperState.saved[v.id] = !!v.saved; });
  }

  function loadPapersNav() {
    var box = qs("[data-pp-list]");
    if (box) box.innerHTML = '<div class="card" style="padding:22px;"><span class="thinking" style="display:inline-flex;"><i></i><i></i><i></i></span></div>';
    closePaperDetail();
    if (paperState.nav === "digest") {
      API.get("/papers/digest" + _prefsQuery()).then(function (d) {
        paperState.digest = d;
        renderDigestBar();
        paperState.items = (d.items || []).map(_digestCardView);
        _syncSavedFromItems();
        renderPaperCards();
      }).catch(function (e) { toast(e.detail || "今日推送加载失败"); });
      return;
    }
    /* P16+P8 我的笔记：已收藏 ∩ 解析 done（标题 + 解析时间 + 批注数/最后批注时间 + 进入笔记） */
    if (paperState.nav === "notes") {
      API.get("/papers/parsed").then(function (items) {
        var box2 = qs("[data-pp-list]");
        if (!box2) return;
        if (!items || !items.length) {
          box2.innerHTML = '<div class="card" style="padding:22px;"><div class="muted" style="font-size:13.5px;">' +
            PP_NAV_EMPTY.notes + "</div></div>";
          return;
        }
        box2.innerHTML = '<div class="pp-notes">' + items.map(function (p) {
          var t = p.parsed_at ? String(p.parsed_at).slice(0, 16).replace("T", " ") : "";
          var cnt = p.annotations_count || 0;
          var annLine = cnt > 0
            ? cnt + " 条批注" + (p.last_annotation_at
                ? " · 最后 " + String(p.last_annotation_at).slice(5, 16).replace("T", " ")
                : "")
            : "暂无批注";
          return '<div class="card pp-note-item">' +
            '<div class="pp-note-title">' + esc(p.title) + "</div>" +
            '<div class="pp-note-meta muted">' + esc(_paperAuthors(p.authors) || "") +
              (t ? (p.authors && p.authors.length ? " · " : "") + "解析于 " + esc(t) : "") + "</div>" +
            '<div class="pp-note-ann">' + esc(annLine) + "</div>" +
            '<div class="pp-note-ops"><button class="btn btn-primary btn-sm" type="button" data-pp-noteentry="' +
              p.id + '">进入笔记</button></div>' +
          "</div>";
        }).join("") + "</div>";
      }).catch(function (e) { toast(e.detail || "笔记列表加载失败"); });
      return;
    }
    var path = paperState.nav === "favorites" ? "/papers/favorites" : "/papers/daily" + _prefsQuery();
    API.get(path).then(function (items) {
      paperState.items = (items || []).map(_paperCardView);
      _syncSavedFromItems();
      renderPaperCards();
    }).catch(function (e) { toast(e.detail || "文献加载失败"); });
  }

  /* 展示偏好：GET /me 读取 → 控件回显；改动即时生效并 PUT /me/settings 保存（P18） */
  function loadPapersPrefs() {
    return API.get("/me").then(function (me) {
      var p = (((me || {}).settings) || {}).papers_prefs;
      if (p && typeof p === "object") {
        if (["time", "if", "score"].indexOf(p.sort) !== -1) paperState.prefs.sort = p.sort;
        var lim = parseInt(p.display_limit, 10);
        if (!isNaN(lim) && lim >= 1 && lim <= 500) paperState.prefs.display_limit = lim;
        var ifm = parseFloat(p.if_min);
        paperState.prefs.if_min = (p.if_min != null && !isNaN(ifm) && ifm >= 0) ? ifm : null;
        /* P21 抓取期过滤参数（同一份 papers_prefs） */
        var yf = parseInt(p.year_from, 10);
        paperState.prefs.year_from = (p.year_from != null && !isNaN(yf)) ? yf : null;
        var yt = parseInt(p.year_to, 10);
        paperState.prefs.year_to = (p.year_to != null && !isNaN(yt)) ? yt : null;
        paperState.prefs.authors = (Array.isArray(p.authors)
          ? p.authors.map(String).map(function (a) { return a.trim(); }).filter(Boolean)
          : []);
        /* 轮③ P27：自动翻译开关（后端 parse_papers_prefs 同口径容错） */
        paperState.prefs.auto_translate = p.auto_translate === true;
      }
      paperState.prefsLoaded = true;
      syncPrefsControls();
    }).catch(function () { paperState.prefsLoaded = true; });
  }
  /* 不派发 xselect:change 的静默回显（避免触发 loadPapersNav 双加载） */
  function _xselectSetSilent(root, value, label) {
    if (!root) return;
    root.setAttribute("data-value", value);
    root.classList.remove("is-placeholder");
    var lbl = qs(".xselect-label", root);
    if (lbl) lbl.textContent = label;
    qsa("[data-xselect-opt]", root).forEach(function (o) {
      var on = o.getAttribute("data-xselect-opt") === value;
      o.classList.toggle("selected", on);
      o.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
  function syncPrefsControls() {
    var sortLabels = { time: "时间", if: "影响因子", score: "相关度" };
    var xs = qs("[data-pp-sort]");
    _xselectSetSilent(xs, paperState.prefs.sort, sortLabels[paperState.prefs.sort] || "时间");
    var ifmin = qs("[data-pp-ifmin]");
    if (ifmin) ifmin.value = paperState.prefs.if_min != null ? String(paperState.prefs.if_min) : "";
    var lim = qs("[data-pp-limit]");
    if (lim) lim.value = String(paperState.prefs.display_limit);
  }
  var _prefsSaveTimer = null;
  function savePapersPrefs() {
    clearTimeout(_prefsSaveTimer);
    _prefsSaveTimer = setTimeout(function () {
      API.put("/me/settings", { key: "papers_prefs", value: paperState.prefs }).catch(function () {});
    }, 300);
  }

  /* 立即检索（轮② P26）：点击后按钮区变进度弹层——POST 触发本轮抓取，
   * 弹层 1.5s 轮询 GET /papers/crawl-now/status（runs 轮始 insert + 轮内 update），
   * 阶段式进度条（抓取中→翻译回填→完成）+ 当前关键词 + 各源计数；
   * POST 返回（本轮完成）或轮询到终态时自动关闭并刷新 digest。 */
  var crawlProg = { el: null, timer: null };
  var CRAWL_PHASE_LABEL = ["抓取中", "翻译回填", "完成"];
  function crawlNow(btn) {
    if (paperState.crawlBusy) return;
    paperState.crawlBusy = true;
    if (btn) { btn.classList.add("is-loading"); btn.disabled = true; }
    openCrawlProgress();
    API.post("/papers/crawl-now", {}).then(function (r) {
      paperState.crawlBusy = false;
      if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; }
      if (closeCrawlProgress()) {
        toast("检索完成：本轮新入库 " + (r.added || 0) + " 篇");
        if (paperState.nav === "digest") loadPapersNav(); else refreshDigestBar();
      }
    }).catch(function (e) {
      paperState.crawlBusy = false;
      if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; }
      if (closeCrawlProgress()) {
        toast((e && e.detail) || "检索失败");
      }
    });
  }
  function openCrawlProgress() {
    closeCrawlProgress();
    var mask = document.createElement("div");
    mask.className = "crawl-prog-mask";
    mask.setAttribute("data-crawl-mask", "");
    mask.innerHTML = '' +
      '<div class="card crawl-prog" role="status" aria-live="polite">' +
        '<div class="cp-head"><span class="cp-title">文献检索中</span>' +
          '<span class="thinking" style="display:inline-flex;"><i></i><i></i><i></i></span>' +
          '<button class="icon-btn" type="button" data-crawl-close aria-label="关闭"><i data-ic="close"></i></button></div>' +
        '<div class="cp-track">' + _crawlPhaseSegs(0, false) + "</div>" +
        '<div class="cp-kw muted">正在发起检索…</div>' +
        '<div class="cp-srcs"></div>' +
      "</div>";
    document.body.appendChild(mask);
    injectIcons(mask);
    crawlProg.el = mask;
    pollCrawlProgress();
  }
  function _crawlPhaseSegs(activeIdx, isDone) {
    return CRAWL_PHASE_LABEL.map(function (label, i) {
      var cls = "cp-seg";
      if (isDone || i < activeIdx) cls += " is-done";
      else if (i === activeIdx) cls += " is-active";
      return '<span class="' + cls + '">' + esc(label) + "</span>";
    }).join("");
  }
  function renderCrawlProgress(s) {
    var box = crawlProg.el && crawlProg.el.querySelector(".crawl-prog");
    if (!box) return;
    var prog = s.progress || {};
    var phase = prog.phase || "fetching";
    var idx = phase === "translating" ? 1 : (phase === "done" ? 2 : 0);
    var done = s.state === "done" || s.state === "failed";
    var title = box.querySelector(".cp-title");
    if (title) {
      title.textContent = s.state === "failed" ? "检索失败"
        : done ? "检索完成" : (phase === "translating" ? "翻译回填中" : "文献检索中");
    }
    var track = box.querySelector(".cp-track");
    if (track) track.innerHTML = _crawlPhaseSegs(idx, s.state === "done");
    var kw = box.querySelector(".cp-kw");
    if (kw) {
      var parts = [];
      if (prog.current_keyword) parts.push("当前：" + prog.current_keyword);
      if (prog.total_keywords) {
        parts.push("关键词 " + (prog.done_keywords || 0) + "/" + prog.total_keywords);
      }
      if (s.state === "failed" && s.error) parts.push("失败原因：" + s.error);
      kw.textContent = parts.join("　") || "检索中…";
      kw.classList.toggle("cp-kw-err", s.state === "failed");
    }
    var srcs = box.querySelector(".cp-srcs");
    if (srcs) {
      var per = (prog.per_source) || {};
      var chips = Object.keys(per).map(function (src) {
        var c = per[src] || {};
        return '<span class="cp-chip">' + esc(src) + "：抓 " + (c.fetched || 0) +
          " · 新 " + (c.added || 0) + "</span>";
      });
      srcs.innerHTML = chips.join("");
      srcs.style.display = chips.length ? "" : "none";
    }
  }
  function pollCrawlProgress() {
    clearTimeout(crawlProg.timer);
    crawlProg.timer = setTimeout(function () {
      if (!crawlProg.el) return;
      API.get("/papers/crawl-now/status").then(function (s) {
        if (!crawlProg.el) return;  // POST 已到终态并关闭
        renderCrawlProgress(s);
        if (s && s.state === "running") {
          pollCrawlProgress();
        } else if (s && s.state !== "idle") {
          /* 轮询先看到终态（POST 响应还在路上）：直接关闭收尾，刷新 digest */
          if (closeCrawlProgress()) {
            if (s.state === "done") {
              toast("检索完成：本轮新入库 " + (s.added || 0) + " 篇");
              if (paperState.nav === "digest") loadPapersNav(); else refreshDigestBar();
            } else {
              toast("检索失败：" + (s.error || "未知原因"));
            }
          }
        } else {
          pollCrawlProgress();  // idle：本轮 runs 行尚未 insert，继续等
        }
      }).catch(function () { pollCrawlProgress(); });
    }, 1500);
  }
  function closeCrawlProgress() {
    if (!crawlProg.el) return false;
    clearTimeout(crawlProg.timer);
    crawlProg.el.remove();
    crawlProg.el = null;
    return true;
  }

  /* P13 本期·语义检索：一句话 → POST /papers/semantic-search（AI 扩词 + 临时聚合抓取）
   * 与立即检索共用 crawlBusy 防重（后端同一把抓取锁，409 时给出提示）；防抖 300ms。 */
  var _nlTimer = null;
  function nlSearch(btn) {
    var input = qs("[data-pp-nlinput]");
    var q = input ? input.value.trim() : "";
    if (!q) { toast("先用一句话描述你想找的文献"); return; }
    if (paperState.crawlBusy) { toast("已有检索正在进行，请稍后再试"); return; }
    clearTimeout(_nlTimer);
    _nlTimer = setTimeout(function () { _doNlSearch(q, btn); }, 300);
  }
  function _doNlSearch(q, btn) {
    paperState.crawlBusy = true;
    if (btn) { btn.classList.add("is-loading"); btn.disabled = true; }
    API.post("/papers/semantic-search", { description: q }).then(function (r) {
      paperState.crawlBusy = false;
      if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; }
      var kws = (r.keywords || []).slice(0, 5);
      toast("已按语义扩词：" + (kws.join(" / ") || "—") + "，新入库 " + (r.added || 0) + " 篇");
      loadPapersNav();  // digest 窗口随 semantic run 刷新，列表立即可见新入库
    }).catch(function (e) {
      paperState.crawlBusy = false;
      if (btn) { btn.classList.remove("is-loading"); btn.disabled = false; }
      toast((e && e.detail) || "语义检索失败");
    });
  }

  /* 轮② P28 解析入口收紧：详情面板不触发解析；P29 做减法再进一步——解析状态降级为
   * 只读小字标（不再引导跳转「我的文献」，不引导发起解析），失败原因收进 title 提示。 */
  function _parseStateHtml(p) {
    var st = p.parse_status || "none";
    var tip = st === "failed" && p.parse_error
      ? ' title="失败原因：' + esc(p.parse_error) + '"' : "";
    return '<span class="pp-parse-ro lib-st lib-st-' + esc(st) + '"' + tip + ">" +
      esc(_libStText(st)) + "</span>";
  }

  /* 右侧详情面板（P29 做减法）：只保留元数据 + 收藏 +「＋ 我的文献」（已加入态 ✓），
   * 解析状态为只读小字标；「AI 解读」「我的笔记」两区与「到我的文献中阅读与批注」
   * 按钮全部移除（减法拍板，笔记/批注入口收敛到 #/library 阅读视图）。 */
  function paperDetailHtml(p, view) {
    var url = (view && view.url) || "";
    if (!url && p.pmid) url = "https://pubmed.ncbi.nlm.nih.gov/" + p.pmid + "/";
    var kws = ((view && view.matched) || p.tags || []).map(function (k) {
      return '<span class="pill pill-mute">' + esc(k) + "</span>";
    }).join("");
    var isSaved = paperState.saved[p.id] !== undefined ? !!paperState.saved[p.id] : !!p.saved;
    var citeParts = [];
    if (p.cited_count != null) citeParts.push("被引 " + esc(String(p.cited_count)));
    if (p.if_approx != null) {
      citeParts.push(_ifBadge(p.if_approx));
    }
    return '' +
      '<div class="pp-detail-head">' +
        '<div class="pp-detail-title">' + esc(p.title) + "</div>" +
        '<button class="icon-btn" type="button" data-pp-close aria-label="关闭"><i data-ic="close"></i></button></div>' +
      '<div class="pp-detail-meta">' +
        esc(_paperAuthors(p.authors) || "（作者不详）") + "<br>" +
        esc(p.journal || "—") + (p.pub_date ? " · " + esc(String(p.pub_date)) : "") +
        (citeParts.length ? "<br>" + citeParts.join(" · ") : "") +
        (url ? '<br><a href="' + esc(url) + '" target="_blank" rel="noopener">打开原文链接 ↗</a>' : "") +
      "</div>" +
      (kws ? '<div class="pp-detail-kws">' + kws + "</div>" : "") +
      /* P29 主操作行：解析状态只读小字标 + 收藏 +「＋ 我的文献」 */
      '<div class="pp-detail-ops">' + _parseStateHtml(p) +
        '<button class="btn btn-ghost btn-sm' + (isSaved ? " is-on" : "") +
          '" type="button" data-paper-save="' + p.id + '">' +
          '<i data-ic="star"></i>' + (isSaved ? "已收藏" : "收藏") + "</button>" +
        '<button class="btn btn-ghost btn-sm' + (paperState.lib[p.id] ? " is-on" : "") +
          '" type="button" data-paper-lib="' + p.id + '">' +
          '<i data-ic="book"></i>' + (paperState.lib[p.id] ? "✓ 已在库" : "＋ 我的文献") + "</button></div>" +
      '<div class="pp-detail-sec">摘要</div>' +
      '<div class="pp-abstract">' + esc(p.abstract || "（无摘要）") + "</div>" +
      (p.abstract_zh
        ? '<div class="pp-detail-sec">中文摘要</div><div class="pp-abstract">' + esc(p.abstract_zh) + "</div>"
        : "");
  }
  function openPaperDetail(pid) {
    var view = null;
    paperState.items.forEach(function (v) { if (v.id === pid) view = v; });
    API.get("/papers/" + pid).then(function (p) {
      var box = qs("[data-pp-detail]");
      if (!box) return;
      box.innerHTML = paperDetailHtml(p, view);
      injectIcons(box);
      box.classList.remove("hide");
      qsa("[data-pp-card]").forEach(function (c) {
        c.classList.toggle("is-active", parseInt(c.getAttribute("data-pp-card"), 10) === pid);
      });
    }).catch(function (e) { toast(e.detail || "详情加载失败"); });
  }
  function closePaperDetail() {
    var box = qs("[data-pp-detail]");
    if (box) box.classList.add("hide");
    qsa("[data-pp-card]").forEach(function (c) { c.classList.remove("is-active"); });
  }

  /* ================= 轮①：我的文献工作区逻辑（P22/P24） ================= */
  var LIB_ST_TEXT = {
    none: "未解析", pending: "排队中", running: "解析中", done: "已解析", failed: "解析失败"
  };
  function _libStText(st) { return LIB_ST_TEXT[st] || st || "未解析"; }

  /* 在库态底账：GET /papers/library 一次，之后加/删本地增量维护（按钮态不闪烁） */
  function ensureLibMap(force) {
    if (paperState.libLoaded && !force) return Promise.resolve(paperState.lib);
    return API.get("/papers/library").then(function (items) {
      paperState.lib = {};
      (items || []).forEach(function (p) { paperState.lib[p.id] = true; });
      paperState.libLoaded = true;
      return paperState.lib;
    }).catch(function () { return {}; });
  }

  /* 左列表数据源：同步在库态底账（papers 页按钮立即可见 ✓ 已在库） */
  function loadLibrary() {
    return API.get("/papers/library").then(function (items) {
      libraryState.items = items || [];
      paperState.lib = {};
      (items || []).forEach(function (p) { paperState.lib[p.id] = true; });
      paperState.libLoaded = true;
      renderLibraryList();
      var cnt = qs("[data-lib-count]");
      if (cnt) cnt.textContent = String(libraryState.items.length);
      /* 轮②：解析中 tab 下刷新列表后同步拉取任务进度 */
      if (libraryState.tab === "parsing") refreshParsingTab();
    }).catch(function (e) { toast(e.detail || "我的文献加载失败"); });
  }

  function _libVisibleItems() {
    if (libraryState.tab !== "parsing") return libraryState.items;
    /* 轮② P26：解析中 tab 数据源 = GET /papers/library/parsing（非 done 任务，含 phase） */
    return libraryState.parsingItems;
  }

  /* 轮② P26：解析五段阶段条（下载→上传→排队→解析中→完成）。
   * 点亮规则：parse_phase 之前的段恒亮；当前段 active（解析中段流动）；失败态当前段标红；
   * done 全亮（解析中列表不含 done，仅为完整语义保留）。 */
  var LIB_PHASES = ["download", "upload", "queue", "parsing", "done"];
  var LIB_PHASE_LABEL = { download: "下载", upload: "上传", queue: "排队", parsing: "解析中", done: "完成" };
  function _phaseIdx(p) {
    var st = p.parse_status || "none";
    if (st === "done") return 4;
    var phase = p.parse_phase;
    if (!phase) phase = st === "pending" ? "queue" : "parsing";
    var idx = LIB_PHASES.indexOf(phase);
    return idx < 0 ? 0 : idx;
  }
  function _phaseBarHtml(p) {
    var st = p.parse_status || "none";
    var idx = _phaseIdx(p);
    /* P30 解耦：全文已就绪（获取/上传动作完成）→ 首段「下载」恒亮（由独立动作承接） */
    var hasFile = (p.fulltext_status || "none") !== "none";
    var segs = LIB_PHASES.map(function (ph, i) {
      var cls = "lps";
      if (i < idx || st === "done" || (i === 0 && hasFile)) cls += " is-done";
      else if (i === idx) cls += st === "failed" ? " is-err" : (ph === "parsing" ? " is-flow" : " is-active");
      return '<span class="' + cls + '" title="' + LIB_PHASE_LABEL[ph] + '"></span>';
    }).join("");
    var labels = LIB_PHASES.map(function (ph, i) {
      var cls = i === idx && st !== "done" ? "on" : "";
      return '<span class="' + cls + '">' + LIB_PHASE_LABEL[ph] + "</span>";
    }).join("");
    var err = st === "failed" && p.parse_error
      ? '<div class="lps-errtext">' + esc(p.parse_error) + "</div>" : "";
    return '<div class="lib-phases">' +
      '<div class="lps-track">' + segs + "</div>" +
      '<div class="lps-labels">' + labels + "</div>" + err + "</div>";
  }

  /* 解析中 tab：拉取未完成任务并 2s 轮询（仍有 pending/running 才续轮；离开页面自动停） */
  var _parsingTimer = null;
  function refreshParsingTab() {
    if (libraryState.tab !== "parsing") return;
    if (!qs("[data-lib-list]")) return;  // 已离开 #/library
    API.get("/papers/library/parsing").then(function (items) {
      libraryState.parsingItems = items || [];
      renderLibraryList();
      var active = libraryState.parsingItems.some(function (p) {
        return p.parse_status === "pending" || p.parse_status === "running";
      });
      scheduleParsingPoll(active ? 2000 : 0);
    }).catch(function () { scheduleParsingPoll(4000); });
  }
  function scheduleParsingPoll(delay) {
    clearTimeout(_parsingTimer);
    _parsingTimer = null;
    if (!delay) return;
    _parsingTimer = setTimeout(refreshParsingTab, delay);
  }

  /* 轮③ P27：我的文献设置小项——「导入/解析后自动翻译」开关（存 papers_prefs）。
   * 打开弹层时按当前 prefs 回显；切换即时 PUT 保存（与订阅设置同一 prefs 通道）。 */
  function toggleLibSettings() {
    var pop = qs("[data-lib-settingspop]");
    if (!pop) return;
    var auto = qs("[data-lib-autotranslate]", pop);
    if (auto) auto.checked = !!paperState.prefs.auto_translate;
    pop.classList.toggle("hide");
  }
  function saveAutoTranslate(input) {
    paperState.prefs.auto_translate = !!input.checked;
    API.put("/me/settings", { key: "papers_prefs", value: paperState.prefs })
      .then(function () {
        toast(paperState.prefs.auto_translate ? "已开启自动翻译：解析完成即生成中英对照" : "已关闭自动翻译");
      })
      .catch(function (e) {
        input.checked = !input.checked;  // 保存失败回滚开关态
        paperState.prefs.auto_translate = !!input.checked;
        toast(e.detail || "保存失败");
      });
  }

  function renderLibraryList() {
    var box = qs("[data-lib-list]");
    if (!box) return;
    var items = _libVisibleItems();
    var hint = qs("[data-lib-tabhint]");
    if (hint) {
      hint.textContent = libraryState.tab === "parsing"
        ? (items.length ? items.length + " 个解析任务" : "")
        : "";
    }
    if (!items.length) {
      box.innerHTML = '<div class="muted" style="padding:18px 6px;font-size:13px;">' +
        (libraryState.tab === "parsing"
          ? "没有解析中的文献"
          : (libraryState.items.length
              ? "全部文献都已解析完成 ✓"
              : "还没有文献：点右上角「导入文献」上传 PDF / 粘贴 arXiv ID 或 DOI，或到文献页点「＋ 我的文献」把论文加进来")) +
        "</div>";
      return;
    }
    var showPhase = libraryState.tab === "parsing";
    box.innerHTML = items.map(function (p) {
      var st = p.parse_status || "none";
      var meta = [];
      if (p.journal) meta.push(esc(p.journal));
      if (p.pub_date) meta.push(esc(String(p.pub_date).slice(0, 4)));
      var cnt = p.annotations_count || 0;
      /* P30 全文与解析解耦：行尾按钮按「全文状态 × 解析状态」演化（五态）——
       * ① 无文件 → [获取全文][上传]（获取失败过 → [重试获取][上传] + 原因小字）；
       * ② 有文件未解析 → [解析][替换文件]（「需重新解析」标志 → ⟳ 高亮主按钮）；
       * ③ 解析中/排队 → 五段阶段条（不变）；④ failed → [重试解析][替换文件]；
       * ⑤ done → 照旧（无操作钮）。上传/替换走同一文件选择弹窗。 */
      var ft = p.fulltext_status || "none";
      var fterr = p.fulltext_error || "";
      var parseBtn = "";
      var ftErrHtml = "";
      var busy = st === "pending" || st === "running";
      if (ft === "none") {
        parseBtn =
          '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-fetch="' + p.id + '">' +
            '<i data-ic="dl"></i>' + (fterr ? "重试获取" : "获取全文") + "</button>" +
          '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-upload="' + p.id + '">' +
            '<i data-ic="doc"></i>上传</button>';
        if (fterr) {
          ftErrHtml = '<div class="lib-ft-err" title="获取失败：' + esc(fterr) +
            '（可重试获取，或上传自有 PDF）">' + esc(fterr) + "</div>";
        }
      } else if (!busy && st === "none") {
        parseBtn = p.needs_reparse
          ? '<button class="btn btn-primary btn-sm lib-act lib-reparse" type="button" data-lib-parse="' + p.id + '">' +
            '<i data-ic="refresh"></i>⟳ 重新解析</button>'
          : '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-parse="' + p.id + '">' +
            '<i data-ic="refresh"></i>解析</button>';
        parseBtn += '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-upload="' + p.id + '">' +
          '<i data-ic="doc"></i>替换文件</button>';
      } else if (st === "failed") {
        parseBtn = '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-parse="' + p.id + '">' +
          '<i data-ic="refresh"></i>重试解析</button>' +
          '<button class="btn btn-ghost btn-sm lib-act" type="button" data-lib-upload="' + p.id + '">' +
          '<i data-ic="doc"></i>替换文件</button>';
      }
      /* 解析中/排队（busy）与 done：无行尾动作钮（阶段条照旧 / done 照旧） */
      return '<div class="lib-item' + (libraryState.currentId === p.id ? " is-active" : "") +
          '" data-lib-open="' + p.id + '" role="button" tabindex="0">' +
        '<div class="lib-item-main">' +
          '<div class="lib-item-title">' + esc(p.title) + "</div>" +
          (meta.length ? '<div class="lib-item-meta muted">' + meta.join(" · ") + "</div>" : "") +
          (showPhase ? _phaseBarHtml(p) : "") +
          ftErrHtml +
        "</div>" +
        '<div class="lib-item-side">' +
          '<span class="lib-st lib-st-' + esc(st) + '">' + _libStText(st) + "</span>" +
          '<span class="muted lib-item-ann">' + (cnt > 0 ? cnt + " 条批注" : "无批注") + "</span>" +
          parseBtn +
          '<button class="icon-btn lib-del" type="button" data-lib-del="' + p.id +
            '" title="删除" aria-label="删除"><i data-ic="trash"></i></button>' +
        "</div>" +
      "</div>";
    }).join("");
    injectIcons(box);
  }

  /* P29：滚动容器探测——桌面端内容区在 .main 内滚（overflow-y:auto），移动端整页滚。
   * 返回列表时按同一容器恢复滚动位置。 */
  function _libScrollBox() {
    var list = qs("[data-lib-list]");
    if (!list) return null;
    var el = list.parentElement;
    while (el && el !== document.body) {
      var ov = getComputedStyle(el).overflowY;
      if ((ov === "auto" || ov === "scroll") && el.scrollHeight > el.clientHeight) return el;
      el = el.parentElement;
    }
    return null;
  }

  /* P29：点行进整页阅读视图（Notion「全宽列表 vs 阅读」切换）——列表隐藏、阅读器整页，
   * 顶部左上角「← 返回」回列表并恢复进入前的滚动位置（Zotero 平板端导航范式）。 */
  function libOpenReader(pid) {
    var host = qs("[data-lib-reader]");
    if (!host) return;
    libraryState.currentId = pid;
    var box = _libScrollBox();
    libraryState.scrollY = box ? box.scrollTop : (window.scrollY || 0);
    qsa("[data-lib-open]").forEach(function (el) {
      el.classList.toggle("is-active", parseInt(el.getAttribute("data-lib-open"), 10) === pid);
    });
    var page = host.closest(".lib-page");
    if (page) page.classList.add("is-reading");
    host.classList.remove("hide");
    host.innerHTML = '' +
      '<div class="lib-backbar">' +
        '<button class="btn btn-ghost btn-sm" type="button" data-lib-back>' +
          '<i data-ic="back"></i>返回</button>' +
        '<span class="muted lib-backbar-hint">阅读视图 · 左侧原文 · 右侧批注栏</span>' +
      "</div>" +
      /* 阅读器挂在内层容器：正文加载失败时提示写在内层，不冲掉返回条 */
      '<div class="lib-reader-mount"></div>';
    injectIcons(host);
    openReader(pid, null, qs(".lib-reader-mount", host));
    /* 整页阅读从顶部开始 */
    if (box) box.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  /* P29：返回列表——收起阅读视图、恢复列表与滚动位置 */
  function libBackToList() {
    closeReader();
    libraryState.currentId = 0;
    var host = qs("[data-lib-reader]");
    if (host) { host.classList.add("hide"); host.innerHTML = ""; }
    var page = qs(".lib-page");
    if (page) page.classList.remove("is-reading");
    qsa("[data-lib-open]").forEach(function (el) { el.classList.remove("is-active"); });
    var y = libraryState.scrollY || 0;
    requestAnimationFrame(function () {
      var box = _libScrollBox();
      if (box) box.scrollTop = y;
      else window.scrollTo(0, y);
    });
  }

  /* 删除确认弹窗（拍板 P24：红字原句，不可恢复语义） */
  function openLibDeleteConfirm(pid, title) {
    closeLibDeleteConfirm();
    var mask = document.createElement("div");
    mask.className = "modal-mask lib-del-mask";
    mask.setAttribute("data-lib-delmask", "");
    mask.innerHTML = '' +
      '<div class="card lib-del-dialog" role="alertdialog" aria-label="删除文献">' +
        '<div class="lib-del-title">删除文献</div>' +
        '<div class="lib-del-quote">' + esc(title || ("文献 #" + pid)) + "</div>" +
        '<div class="lib-del-warn">删除后该文献及其相关笔记会一并删除，且不可恢复</div>' +
        '<div class="lib-del-ops">' +
          '<button class="btn btn-ghost btn-sm" type="button" data-lib-delcancel>取消</button>' +
          '<button class="btn btn-danger-ghost btn-sm lib-del-confirm" type="button" data-lib-delconfirm="' +
            pid + '">确认删除</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(mask);
  }
  function closeLibDeleteConfirm() {
    qsa("[data-lib-delmask]").forEach(function (m) { m.remove(); });
  }
  function libConfirmDelete(pid) {
    API.del("/papers/" + pid + "/library").then(function (r) {
      closeLibDeleteConfirm();
      delete paperState.lib[pid];
      libraryState.items = libraryState.items.filter(function (p) { return p.id !== pid; });
      if (libraryState.currentId === pid) {
        /* P29：阅读视图中删当前篇 → 收起阅读视图回列表 */
        libBackToList();
      }
      renderLibraryList();
      var cnt = qs("[data-lib-count]");
      if (cnt) cnt.textContent = String(libraryState.items.length);
      toast("已删除" + (r && r.deleted_paper ? "" : "（已解除你的归属）"));
    }).catch(function (e) {
      closeLibDeleteConfirm();
      toast(e.detail || "删除失败");
    });
  }
  /* 卡片/详情「＋ 我的文献」按钮 → 幂等加入（P22：与收藏并存的工作台手势） */
  function addToLibrary(btn) {
    var pid = parseInt(btn.getAttribute("data-paper-lib"), 10);
    if (paperState.lib[pid]) { toast("已在「我的文献」中"); go("library"); return; }
    btn.disabled = true;
    API.post("/papers/" + pid + "/library", {}).then(function () {
      paperState.lib[pid] = true;
      qsa('[data-paper-lib="' + pid + '"]').forEach(function (b) {
        b.classList.add("is-on");
        var lbl = b.childNodes[b.childNodes.length - 1];
        if (lbl && lbl.nodeType === 3) lbl.textContent = "✓ 已在库";
      });
      toast("已加入我的文献");
    }).catch(function (e) {
      btn.disabled = false;
      toast(e.detail || "加入失败");
    });
  }

  /* ================= P30：上传/替换全文弹窗（独立动作二，付费墙文献的正解）
   * 「上传」（无文件态）与「替换文件」（有文件态）共用同一文件选择弹窗：
   * FileReader 读 bytes → base64 → POST /papers/{id}/fulltext（≤30MB，后端魔数校验）。
   * 替换已解析（done）/解析中的文件 → 后端四清解析产物 + 「需重新解析」标志，
   * 列表行尾出现高亮「⟳ 重新解析」，用户一点即重跑。 */
  var _fulltextPid = 0;
  function openFulltextModal(pid) {
    closeFulltextModal();
    _fulltextPid = pid;
    var mask = document.createElement("div");
    mask.className = "modal-mask lib-del-mask";
    mask.setAttribute("data-lib-ftmask", "");
    mask.innerHTML = '' +
      '<div class="card lib-import-dialog" role="dialog" aria-label="上传全文">' +
        '<div class="lib-del-title">上传全文 PDF</div>' +
        '<div class="imp-pane" data-import-pane="pdf">' +
          '<label class="imp-field"><span class="muted">选择 PDF 文件（≤30MB；替换已解析文件后将置为「需重新解析」）</span>' +
          '<input type="file" accept="application/pdf,.pdf" data-lib-ftfile></label>' +
          '<div class="imp-filename muted" data-lib-ftname>未选择文件</div>' +
        "</div>" +
        '<div class="imp-err hide" data-lib-fterr></div>' +
        '<div class="lib-del-ops">' +
          '<button class="btn btn-ghost btn-sm" type="button" data-lib-ftclose>取消</button>' +
          '<button class="btn btn-primary btn-sm" type="button" data-lib-ftsubmit>上传</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(mask);
    var fileInput = mask.querySelector("[data-lib-ftfile]");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        var f = fileInput.files && fileInput.files[0];
        var lbl = mask.querySelector("[data-lib-ftname]");
        if (lbl) lbl.textContent = f ? (f.name + "（" + Math.ceil(f.size / 1024) + " KB）") : "未选择文件";
      });
    }
  }
  function closeFulltextModal() {
    qsa("[data-lib-ftmask]").forEach(function (m) { m.remove(); });
    _fulltextPid = 0;
  }
  function submitFulltext(btn) {
    var mask = qs("[data-lib-ftmask]");
    if (!mask || !_fulltextPid) return;
    var err = mask.querySelector("[data-lib-fterr]");
    if (err) { err.textContent = ""; err.classList.add("hide"); }
    var fileInput = mask.querySelector("[data-lib-ftfile]");
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) {
      if (err) { err.textContent = "请先选择一个 PDF 文件"; err.classList.remove("hide"); }
      return;
    }
    if (file.size > IMPORT_MAX_BYTES) {
      if (err) { err.textContent = "PDF 超过 30MB 上限，请压缩后重新上传"; err.classList.remove("hide"); }
      return;
    }
    btn.disabled = true;
    var reader = new FileReader();
    reader.onload = function () {
      var dataUrl = String(reader.result || "");
      var b64 = dataUrl.indexOf(",") >= 0 ? dataUrl.split(",")[1] : dataUrl;
      API.post("/papers/" + _fulltextPid + "/fulltext", { pdf_base64: b64 })
        .then(function (r) {
          closeFulltextModal();
          toast(r && r.needs_reparse
            ? "已替换全文：解析产物已重置，点「⟳ 重新解析」重跑"
            : "全文已上传，可发起解析");
          loadLibrary();
        })
        .catch(function (e2) {
          btn.disabled = false;
          var msg = (e2 && e2.detail) || "上传失败";
          if (err) { err.textContent = msg; err.classList.remove("hide"); }
          toast(msg);
        });
    };
    reader.onerror = function () {
      btn.disabled = false;
      if (err) { err.textContent = "文件读取失败，请重试"; err.classList.remove("hide"); }
    };
    reader.readAsDataURL(file);
  }

  /* ================= 轮②：导入文献弹窗（P25：PDF 上传 / arXiv ID / DOI） =================
   * 两路统一 POST /papers/library/import：
   * - pdf：FileReader 直读 bytes → base64 JSON（后端 ≤30MB 校验 + 魔数校验）；
   * - identifier：粘贴 arXiv ID / DOI（后端拉元数据 + 下 OA 全文）。
   * 成功 → toast + 关闭 + 跳「解析中」tab 看阶段条；失败（下载失败等）→ 条目已落
   * failed 态，弹层内红字原因 + toast「导入失败：<原因>」（P25 必须通知用户）。 */
  var IMPORT_MAX_BYTES = 30 * 1024 * 1024;
  var importState = { mode: "pdf" };

  function openImportModal() {
    closeImportModal();
    importState.mode = "pdf";
    var mask = document.createElement("div");
    mask.className = "modal-mask lib-del-mask";
    mask.setAttribute("data-lib-importmask", "");
    mask.innerHTML = '' +
      '<div class="card lib-import-dialog" role="dialog" aria-label="导入文献">' +
        '<div class="lib-del-title">导入文献</div>' +
        '<div class="imp-tabs">' +
          '<button class="pp-nav-item active" type="button" data-import-mode="pdf"><i data-ic="doc"></i>上传 PDF</button>' +
          '<button class="pp-nav-item" type="button" data-import-mode="identifier"><i data-ic="search"></i>arXiv ID / DOI</button>' +
        "</div>" +
        /* 路上传 */
        '<div class="imp-pane" data-import-pane="pdf">' +
          '<label class="imp-field"><span class="muted">选择 PDF 文件（≤30MB，上传后自动解析）</span>' +
          '<input type="file" accept="application/pdf,.pdf" data-import-file></label>' +
          '<div class="imp-filename muted" data-import-filename>未选择文件</div>' +
        "</div>" +
        /* 路标识符 */
        '<div class="imp-pane hide" data-import-pane="identifier">' +
          '<label class="imp-field"><span class="muted">粘贴 arXiv ID（如 2401.12345）或 DOI（如 10.1000/xyz）——自动拉元数据并下载开放获取全文</span>' +
          '<input type="text" data-import-ident placeholder="2401.12345 或 10.1000/xyz.2026"></label>' +
        "</div>" +
        '<div class="imp-err hide" data-import-err></div>' +
        '<div class="lib-del-ops">' +
          '<button class="btn btn-ghost btn-sm" type="button" data-lib-importclose>取消</button>' +
          '<button class="btn btn-primary btn-sm" type="button" data-import-submit>导入</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(mask);
    injectIcons(mask);
    var fileInput = mask.querySelector("[data-import-file]");
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        var f = fileInput.files && fileInput.files[0];
        var lbl = mask.querySelector("[data-import-filename]");
        if (lbl) lbl.textContent = f ? (f.name + "（" + Math.ceil(f.size / 1024) + " KB）") : "未选择文件";
      });
    }
  }
  function closeImportModal() {
    qsa("[data-lib-importmask]").forEach(function (m) { m.remove(); });
  }
  function switchImportMode(mode) {
    importState.mode = mode;
    var mask = qs("[data-lib-importmask]");
    if (!mask) return;
    qsa("[data-import-mode]", mask).forEach(function (b) {
      b.classList.toggle("active", b.getAttribute("data-import-mode") === mode);
    });
    qsa("[data-import-pane]", mask).forEach(function (pane) {
      pane.classList.toggle("hide", pane.getAttribute("data-import-pane") !== mode);
    });
    var err = mask.querySelector("[data-import-err]");
    if (err) { err.textContent = ""; err.classList.add("hide"); }
  }
  function _importFail(msg) {
    var err = qs("[data-import-err]");
    if (err) { err.textContent = msg; err.classList.remove("hide"); }
    toast("导入失败：" + msg);  // P25：失败必须通知用户
  }
  function submitImport(btn) {
    var mask = qs("[data-lib-importmask]");
    if (!mask) return;
    var err = mask.querySelector("[data-import-err]");
    if (err) { err.textContent = ""; err.classList.add("hide"); }
    if (importState.mode === "pdf") {
      var fileInput = mask.querySelector("[data-import-file]");
      var file = fileInput && fileInput.files && fileInput.files[0];
      if (!file) { _importFail("请先选择一个 PDF 文件"); return; }
      if (file.size > IMPORT_MAX_BYTES) {
        _importFail("PDF 超过 30MB 上限，请压缩后重新上传");
        return;
      }
      btn.disabled = true;
      var reader = new FileReader();
      reader.onload = function () {
        var dataUrl = String(reader.result || "");
        var b64 = dataUrl.indexOf(",") >= 0 ? dataUrl.split(",")[1] : dataUrl;
        API.post("/papers/library/import", {
          kind: "pdf", filename: file.name, pdf_base64: b64
        }).then(function (r) { _importDone(r, btn); })
          .catch(function (e) { btn.disabled = false; _importFail((e && e.detail) || "导入失败"); });
      };
      reader.onerror = function () { btn.disabled = false; _importFail("文件读取失败，请重试"); };
      reader.readAsDataURL(file);
    } else {
      var input = mask.querySelector("[data-import-ident]");
      var ident = input ? input.value.trim() : "";
      if (!ident) { _importFail("请输入 arXiv ID 或 DOI"); return; }
      btn.disabled = true;
      API.post("/papers/library/import", { kind: "identifier", identifier: ident })
        .then(function (r) { _importDone(r, btn); })
        .catch(function (e) { btn.disabled = false; _importFail((e && e.detail) || "导入失败"); });
    }
  }
  function _importDone(r, btn) {
    if (!r || r.parse_status === "failed") {
      btn.disabled = false;
      _importFail((r && r.parse_error) || "未知原因");
      return;
    }
    closeImportModal();
    toast("导入成功：" + (r.title || ("文献 #" + r.paper_id)));
    /* 成功后跳「解析中」tab 看五段阶段条（r.parse_status pending/running/done 均可见） */
    libraryState.tab = "parsing";
    loadLibrary().then(function () {
      qsa("[data-lib-tab]").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-lib-tab") === "parsing");
      });
      refreshParsingTab();
    });
  }

  /* ================= P8 批注式笔记阅读器（论文域后批①）
   * 参考案例（AGENTS.md §一 设计强制规则，动手前已检索）：
   * - Zotero Reader（zotero.org/support/pdf_reader）：选中文字 → 弹出高亮/批注
   *   操作；批注聚在侧栏（引用+批注正文+位置），点批注「Show on Page」跳回原文；
   *   批注可聚合导出 Markdown 且链接回原文位置——本阅读器的交互主干；
   * - hypothes.is（W3C Web Annotation）：锚点 = 精确引用（quote）+ 定位双保险，
   *   重定位失败（orphan）不静默丢弃、引用恒可见——对应 anchor_quote 字段与
   *   右栏引用块；后端 block_id（p{页}_b{页内序}）承担 RangeSelector 角色；
   * - Obsidian/Roam：[[双向链接]] + backlinks 面板——对应批注出链 chips +
   *   被链数（后端查询派生，边单写不双写）。
   * 布局（拍板 P8）：整页中央弹层，左原文段落流、右批注栏（SciSpace/Zotero 式），
   * 手机端单栏、批注栏变浮层可切换。 */
  var readerState = {
    open: false, paperId: 0, title: "", blocks: [], annotations: [],
    legacyNote: "", sel: null, meta: {}, flashAid: null, editingId: null, inline: false,
    /* 轮③ P27：中英对照翻译（translations = block_id → 中文译文） */
    translations: {}, translateStatus: "none", translateError: null
  };

  function _fmtAnnoTime(t) {
    return t ? String(t).slice(0, 16).replace("T", " ") : "";
  }

  /* 打开阅读器：正文（/content）+ 批注（/annotations）+ 旧全文笔记（详情）+
   * 互链选择器候选（/annotations/recent，建 id→meta 索引供跨篇跳转与 chips 展示）。
   * 轮① P22 起支持挂载态：传 mount 容器（我的文献页中栏）则不遮罩、不锁 body 滚动，
   * 批注交互与遮罩态完全一致（同一组件两种挂载，详情面板抽成可挂载）。 */
  function openReader(pid, flashAid, mount) {
    closeReader();
    var host = mount || null;
    var overlay = document.createElement("div");
    overlay.className = "pp-reader" + (host ? " pp-reader-inline" : "");
    overlay.setAttribute("data-pp-reader", "");
    overlay.innerHTML = '' +
      '<div class="pp-reader-head">' +
        '<div class="pp-reader-title"><i data-ic="edit"></i><span data-pp-rtitle>加载中…</span></div>' +
        '<div class="pp-reader-ops">' +
          /* 轮③ P27：中英对照翻译按钮（未译/失败=「翻译」，已译=「重新翻译」，翻译中流动） */
          '<button class="btn btn-ghost btn-sm pp-translate-btn" type="button" data-pp-translate' +
            ' title="段落级中英对照翻译（MinerU 块锚点，结果缓存）">' +
            '<i data-ic="spark"></i><span data-pp-translate-label>翻译</span></button>' +
          '<button class="btn btn-ghost btn-sm" type="button" data-pp-rexport><i data-ic="dl"></i>导出 Markdown</button>' +
          '<button class="btn btn-ghost btn-sm pp-reader-railbtn" type="button" data-pp-railtoggle aria-label="批注栏"><i data-ic="menu"></i>批注</button>' +
          '<button class="icon-btn" type="button" data-pp-rclose aria-label="关闭阅读器"><i data-ic="close"></i></button>' +
        "</div>" +
      "</div>" +
      '<div class="pp-reader-body">' +
        '<div class="pp-reader-main" data-pp-rmain><div class="muted" style="padding:30px 6px;">正文加载中…</div></div>' +
        '<aside class="pp-reader-rail" data-pp-rail></aside>' +
      "</div>" +
      '<div class="pp-selpop hide" data-pp-selpop></div>';
    if (host) {
      host.appendChild(overlay);
    } else {
      document.body.appendChild(overlay);
      document.body.classList.add("pp-reading");
    }
    injectIcons(overlay);
    readerState = {
      open: true, paperId: pid, title: "", blocks: [], annotations: [],
      legacyNote: "", sel: null, meta: {}, flashAid: flashAid || null, editingId: null,
      inline: !!host,
      translations: {}, translateStatus: "none", translateError: null
    };
    renderTranslateBtn();

    API.get("/papers/" + pid + "/content").then(function (c) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.blocks = (c && c.blocks) || [];
      readerState.title = (c && c.title) || "";
      var t = qs("[data-pp-rtitle]");
      if (t) t.textContent = readerState.title;
      renderReaderMain();
    }).catch(function (e) {
      toast((e && e.detail) || "正文加载失败");
      closeReader();
      /* 挂载态（我的文献页）：给可行动的提示，不留空白（P29：库内行尾「解析」发起） */
      if (host) {
        host.innerHTML = '<div class="card lib-empty muted">' +
          esc((e && e.detail) || "正文加载失败") +
          "<br>该文献还没有解析产物：回到列表确认解析完成后再进入阅读。</div>";
      }
    });

    API.get("/papers/" + pid + "/annotations").then(function (list) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.annotations = list || [];
      (list || []).forEach(function (a) { readerState.meta[a.id] = a; });
      renderReaderRail();
      renderReaderMain();
      if (readerState.flashAid) {
        var f = readerState.flashAid;
        readerState.flashAid = null;
        setTimeout(function () { flashCard(f); }, 120);
      }
    }).catch(function () {});

    API.get("/papers/" + pid).then(function (d) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.legacyNote = (d && d.note) || "";
      if (readerState.legacyNote) renderReaderRail();
    }).catch(function () {});

    API.get("/papers/annotations/recent?limit=50").then(function (list) {
      (list || []).forEach(function (a) { readerState.meta[a.id] = a; });
      if (readerState.open) renderReaderRail();
    }).catch(function () {});

    /* 轮③ P27：对照译文 + 翻译状态（无权限/非库内 → 隐藏翻译按钮不打扰） */
    API.get("/papers/" + pid + "/translation").then(function (t) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.translations = (t && t.translations) || {};
      readerState.translateStatus = (t && t.translate_status) || "none";
      readerState.translateError = (t && t.translate_error) || null;
      renderReaderMain();
      renderTranslateRailNote();
      renderTranslateBtn();
      if (readerState.translateStatus === "running") scheduleTranslatePoll();
    }).catch(function () {
      var btn = qs("[data-pp-translate]");
      if (btn) btn.classList.add("hide");
    });
  }

  function closeReader() {
    var overlay = qs("[data-pp-reader]");
    if (overlay) overlay.remove();
    document.body.classList.remove("pp-reading");
    readerState.open = false;
    readerState.sel = null;
    readerState.editingId = null;
    clearTimeout(_translateTimer);
    _translateTimer = null;
  }

  /* ── 轮③ P27：中英对照翻译交互 ── */
  function renderTranslateBtn() {
    var btn = qs("[data-pp-translate]");
    if (!btn) return;
    var st = readerState.translateStatus || "none";
    btn.classList.toggle("is-flow", st === "running");
    btn.disabled = st === "running";
    btn.title = st === "failed" && readerState.translateError
      ? "翻译失败：" + readerState.translateError + "（点击重试）"
      : "段落级中英对照翻译（MinerU 块锚点，结果缓存）";
    var lbl = qs("[data-pp-translate-label]", btn);
    if (lbl) lbl.textContent = st === "running" ? "翻译中…" : (st === "done" ? "重新翻译" : "翻译");
  }

  function startTranslate() {
    var pid = readerState.paperId;
    if (!pid) return;
    var force = readerState.translateStatus === "done";  // 「重新翻译」清缓存全量重译
    var btn = qs("[data-pp-translate]");
    if (btn) btn.disabled = true;
    readerState.translateStatus = "running";
    renderTranslateBtn();
    API.post("/papers/" + pid + "/translate", { force: force }).then(function (r) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.translateStatus = (r && r.translate_status) || "none";
      readerState.translateError = (r && r.translate_error) || null;
      renderTranslateBtn();
      if (readerState.translateStatus === "running") scheduleTranslatePoll();
      else if (readerState.translateStatus === "done") refreshTranslation();
      else if (readerState.translateStatus === "failed") {
        toast("翻译失败：" + (readerState.translateError || "未知原因"));
      }
    }).catch(function (e) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.translateStatus = "failed";
      readerState.translateError = (e && e.detail) || "请求失败";
      renderTranslateBtn();
      toast((e && e.detail) || "翻译请求失败");
    });
  }

  /* 翻译中：2s 轮询状态到终态（引擎异步执行场景；进程内同步通常已终态） */
  var _translateTimer = null;
  function scheduleTranslatePoll() {
    clearTimeout(_translateTimer);
    _translateTimer = setTimeout(pollTranslate, 2000);
  }
  function pollTranslate() {
    if (!readerState.open || !readerState.paperId) return;
    var pid = readerState.paperId;
    API.get("/papers/" + pid + "/translate-status").then(function (s) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.translateStatus = (s && s.translate_status) || "none";
      readerState.translateError = (s && s.translate_error) || null;
      renderTranslateBtn();
      if (readerState.translateStatus === "running") scheduleTranslatePoll();
      else if (readerState.translateStatus === "done") refreshTranslation();
    }).catch(function () { scheduleTranslatePoll(); });
  }
  function refreshTranslation() {
    var pid = readerState.paperId;
    API.get("/papers/" + pid + "/translation").then(function (t) {
      if (!readerState.open || readerState.paperId !== pid) return;
      readerState.translations = (t && t.translations) || {};
      readerState.translateStatus = (t && t.translate_status) || "done";
      readerState.translateError = (t && t.translate_error) || null;
      renderReaderMain();
      renderTranslateRailNote();
      renderTranslateBtn();
    }).catch(function () {});
  }
  /* 右栏批注头下加一行对照译文状态说明（done 时提示可重新翻译；failed 给原因） */
  function renderTranslateRailNote() {
    var rail = qs("[data-pp-rail]");
    if (!rail) return;
    var note = qs("[data-pp-rtrans]", rail);
    var st = readerState.translateStatus || "none";
    var html = "";
    if (st === "done") {
      var n = 0;
      Object.keys(readerState.translations || {}).forEach(function () { n += 1; });
      html = '<div class="pp-rtrans" data-pp-rtrans>已生成中英对照译文（' + n + ' 段）</div>';
    } else if (st === "failed" && readerState.translateError) {
      html = '<div class="pp-rtrans is-err" data-pp-rtrans>翻译失败：' +
        esc(readerState.translateError) + "</div>";
    }
    if (note) note.outerHTML = html || "<div data-pp-rtrans></div>";
    else if (html) {
      var head = qs(".pp-rail-head", rail);
      if (head) head.insertAdjacentHTML("afterend", html);
    }
  }

  /* 左栏：正文段落流（text_level → 标题层级；table/image 占位卡带页码）；
   * 有批注的段落右侧插「N 批注」旗标，点击跳右栏对应卡片 */
  function renderReaderMain() {
    var main = qs("[data-pp-rmain]");
    if (!main) return;
    if (!readerState.blocks.length) {
      main.innerHTML = '<div class="muted" style="padding:30px 6px;">暂无正文段落</div>';
      return;
    }
    var counts = {};
    (readerState.annotations || []).forEach(function (a) {
      counts[a.anchor_block_id] = (counts[a.anchor_block_id] || 0) + 1;
    });
    main.innerHTML = readerState.blocks.map(function (b) {
      var flag = counts[b.block_id]
        ? '<button type="button" class="pp-rflag" data-pp-blockjump="' + b.block_id +
          '" title="该段有 ' + counts[b.block_id] + ' 条批注，点击跳转">' + counts[b.block_id] + " 批注</button>"
        : "";
      var tag = "p";
      var cls = "pp-rblock pp-rblock-" + b.type;
      var inner;
      if (b.type === "text") {
        if (b.text_level) { tag = "h" + Math.min(4, b.text_level); cls += " pp-rh"; }
        inner = esc(b.text);
        /* 轮③ P27：有对照译文时英文段下紧跟中文段（上下对照，移动端友好；muted 小字） */
        var zh = (readerState.translations || {})[b.block_id];
        if (zh) inner += '<div class="pp-rzh">' + esc(zh) + "</div>";
      } else if (b.type === "table" || b.type === "image") {
        cls += " pp-rmedia";
        inner = '<span class="pp-rmediatag">' + (b.type === "table" ? "表" : "图") +
                " · 第 " + (b.page_idx + 1) + " 页</span>" + (b.text ? esc(b.text) : "");
      } else {
        inner = esc(b.text);
      }
      return "<" + tag + ' class="' + cls + '" data-block-id="' + b.block_id + '">' + inner + flag + "</" + tag + ">";
    }).join("");
  }

  /* 右栏：旧全文笔记（兼容卡）+ 批注卡片（按原文段落序排列）；
   * 卡片 = 引用块（点击跳原文）+ 正文 + 出链 chips / 被链数 + 操作行 */
  function _annCardHtml(a) {
    var chips = (a.links || []).map(function (tid) {
      var m = readerState.meta[tid];
      var label = m ? (m.anchor_quote || "").slice(0, 24) : ("批注 #" + tid);
      var cross = m && m.paper_id !== readerState.paperId;
      return '<button class="pp-rchip" type="button" data-pp-rajump="' + tid + '" title="' +
        esc(m ? ("“" + m.anchor_quote + "”") : "") + '">→ ' + esc(label) + (cross ? " · 他篇" : "") + "</button>";
    }).join("");
    var bl = a.backlink_count
      ? '<span class="pp-rchip pp-rchip-bl" title="有 ' + a.backlink_count + ' 条其他批注链接到本条">被链 ' + a.backlink_count + "</span>"
      : "";
    var editing = readerState.editingId === a.id;
    var bodyHtml = editing
      ? '<textarea class="pp-raedit" data-pp-ratext="' + a.id + '" rows="3" placeholder="批注正文（可空 = 纯划线）">' +
        esc(a.body) + "</textarea>" +
        '<div class="pp-raops"><button class="btn btn-primary btn-sm" type="button" data-pp-rasave="' + a.id + '">保存</button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-pp-racancel="' + a.id + '">取消</button></div>'
      : (a.body
          ? '<div class="pp-rabody">' + esc(a.body) + "</div>"
          : '<div class="pp-rabody muted">（划线）</div>');
    return '<div class="pp-racard' + (a.body ? "" : " is-mark") + '" data-pp-racard="' + a.id + '">' +
      '<button class="pp-raquote" type="button" data-pp-annjump="' + a.anchor_block_id +
        '" title="跳转到原文 ' + esc(a.anchor_block_id) + '">“' + esc((a.anchor_quote || "").slice(0, 140)) + '”</button>' +
      '<div class="pp-rameta muted">' + esc(a.anchor_block_id) + " · " + esc(_fmtAnnoTime(a.updated_at)) + "</div>" +
      bodyHtml +
      ((chips || bl) ? '<div class="pp-rchips">' + chips + bl + "</div>" : "") +
      (editing ? "" : '<div class="pp-raops">' +
        '<button class="pp-raop" type="button" data-pp-raedit="' + a.id + '">编辑</button>' +
        '<button class="pp-raop" type="button" data-pp-ralink="' + a.id + '">链到…</button>' +
        '<button class="pp-raop pp-raop-danger" type="button" data-pp-radel="' + a.id + '">删除</button>' +
      "</div>") +
    "</div>";
  }

  function renderReaderRail() {
    var rail = qs("[data-pp-rail]");
    if (!rail) return;
    var order = {};
    readerState.blocks.forEach(function (b, i) { order[b.block_id] = i; });
    var anns = (readerState.annotations || []).slice().sort(function (x, y) {
      var ox = order[x.anchor_block_id];
      var oy = order[y.anchor_block_id];
      if (ox == null) ox = 999999;
      if (oy == null) oy = 999999;
      return ox - oy || x.id - y.id;
    });
    var legacy = readerState.legacyNote
      ? '<div class="pp-racard pp-ralegacy"><div class="pp-rasec">全文笔记</div>' +
        '<div class="pp-rabody">' + esc(readerState.legacyNote) + "</div></div>"
      : "";
    rail.innerHTML =
      '<div class="pp-rail-head">批注 <b>' + anns.length + '</b> 条' +
        '<span class="pp-rail-hint muted">选中左侧文字可划线 / 批注</span></div>' +
      legacy +
      (anns.length
        ? anns.map(_annCardHtml).join("")
        : '<div class="pp-raempty muted">还没有批注——在左侧选中一段文字开始</div>');
    injectIcons(rail);
  }

  function reloadReaderAnns() {
    API.get("/papers/" + readerState.paperId + "/annotations").then(function (list) {
      readerState.annotations = list || [];
      (list || []).forEach(function (a) { readerState.meta[a.id] = a; });
      renderReaderRail();
      renderReaderMain();
    }).catch(function () {});
  }

  /* 选中文字 → 弹出「划线 / 批注」（Zotero 式 selection popup） */
  function renderSelPopDefault() {
    var pop = qs("[data-pp-selpop]");
    if (!pop) return;
    pop.setAttribute("data-mode", "default");
    pop.innerHTML = '<button type="button" class="pp-selbtn" data-pp-selmark><i data-ic="star"></i>划线</button>' +
      '<button type="button" class="pp-selbtn" data-pp-selcomment><i data-ic="edit"></i>批注</button>';
    injectIcons(pop);
  }
  function hideSelPop() {
    var pop = qs("[data-pp-selpop]");
    if (pop) { pop.classList.add("hide"); pop.removeAttribute("data-mode"); }
    readerState.sel = null;
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed) sel.removeAllRanges();
  }
  function updateSelPop() {
    var pop = qs("[data-pp-selpop]");
    var main = qs("[data-pp-rmain]");
    if (!pop || !main) return;
    var mode = pop.getAttribute("data-mode");
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) {
      /* 编辑中（composer）：聚焦 textarea 会塌掉正文选中态，此时保留弹层，
       * 锚点数据已在 readerState.sel，等 保存/取消 收尾 */
      if (mode === "composer") return;
      hideSelPop();
      return;
    }
    var text = sel.toString().replace(/\s+/g, " ").trim();
    if (!text) { hideSelPop(); return; }
    var node = sel.anchorNode;
    var elN = node && node.nodeType === 3 ? node.parentElement : node;
    var blockEl = elN && elN.closest ? elN.closest("[data-block-id]") : null;
    if (!blockEl || !main.contains(blockEl)) { hideSelPop(); return; }
    readerState.sel = { quote: text.slice(0, 2000), blockId: blockEl.getAttribute("data-block-id") };
    if (mode !== "composer") renderSelPopDefault();
    pop.classList.remove("hide");
    var rect = sel.getRangeAt(0).getBoundingClientRect();
    var pw = pop.offsetWidth;
    var ph = pop.offsetHeight;
    var top = rect.top - ph - 8;
    if (top < 70) top = rect.bottom + 8;
    var left = rect.left + rect.width / 2 - pw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - pw - 8));
    pop.style.top = top + "px";
    pop.style.left = left + "px";
  }
  function selPopComposer() {
    var pop = qs("[data-pp-selpop]");
    if (!pop || !readerState.sel) return;
    pop.setAttribute("data-mode", "composer");
    pop.innerHTML = '<textarea class="pp-seltext" data-pp-seltext rows="3" placeholder="批注这段文字…"></textarea>' +
      '<div class="pp-selops"><button type="button" class="btn btn-primary btn-sm" data-pp-selsave>保存</button>' +
      '<button type="button" class="btn btn-ghost btn-sm" data-pp-selcancel>取消</button></div>';
    var ta = qs("[data-pp-seltext]", pop);
    if (ta) ta.focus();
  }
  function createAnnotationFromSel(body) {
    var selData = readerState.sel;
    if (!selData) { toast("请先在左侧正文中选中文字"); return; }
    API.post("/papers/" + readerState.paperId + "/annotations", {
      anchor_quote: selData.quote,
      anchor_block_id: selData.blockId,
      body: body || ""
    }).then(function () {
      var sel = window.getSelection();
      if (sel) sel.removeAllRanges();
      hideSelPop();
      toast(body ? "批注已保存" : "已划线");
      reloadReaderAnns();
    }).catch(function (e) { toast((e && e.detail) || "保存失败"); });
  }

  /* 互链：中央弹窗选择器（AGENTS.md 统一中央弹窗），候选 = 本篇批注 +
   * 跨论文最近批注（去重、排除自身与已链） */
  function openLinkPicker(aid) {
    var ann = null;
    (readerState.annotations || []).forEach(function (a) { if (a.id === aid) ann = a; });
    if (!ann) return;
    var cur = {};
    (ann.links || []).forEach(function (x) { cur[x] = true; });
    var seen = {};
    var candidates = [];
    (readerState.annotations || []).forEach(function (a) {
      if (a.id !== aid && !cur[a.id] && !seen[a.id]) { seen[a.id] = 1; candidates.push(a); }
    });
    Object.keys(readerState.meta).forEach(function (k) {
      var m = readerState.meta[k];
      var id = parseInt(k, 10);
      if (id !== aid && !cur[id] && !seen[id]) { seen[id] = 1; candidates.push(m); }
    });
    candidates = candidates.slice(0, 20);
    var dlg = document.createElement("dialog");
    dlg.className = "modal-mask";
    dlg.setAttribute("data-pp-linkdlg", "");
    dlg.innerHTML = '<div class="modal">' +
      '<div class="modal-head"><h3>链到…</h3>' +
      '<button class="icon-btn" type="button" data-pp-linkclose aria-label="关闭"><i data-ic="close"></i></button></div>' +
      '<div class="modal-body"><div class="pp-linkpick">' +
      (candidates.length
        ? candidates.map(function (m) {
            var same = m.paper_id === readerState.paperId;
            return '<button class="pp-linkpick-item" type="button" data-pp-ralinkpick="' + aid + "|" + m.id + '">' +
              '<span class="pp-linkpick-quote">“' + esc((m.anchor_quote || "").slice(0, 64)) + '”</span>' +
              '<span class="pp-linkpick-meta muted">' + (same ? "本篇" : esc((m.paper_title || "他篇").slice(0, 24))) + "</span>" +
            "</button>";
          }).join("")
        : '<div class="muted" style="padding:14px 4px;">暂无其他批注可选——先去别的段落划几条线</div>') +
      "</div></div></div>";
    document.body.appendChild(dlg);
    injectIcons(dlg);
    if (dlg.showModal) dlg.showModal();
    else dlg.classList.add("open");
    dlg.addEventListener("close", function () { dlg.remove(); });
  }

  /* 跳转与高亮（Zotero Show on Page 式） */
  function flashCard(aid) {
    var card = qs('[data-pp-racard="' + aid + '"]');
    if (!card) return;
    card.scrollIntoView({ block: "center", behavior: "smooth" });
    card.classList.add("is-flash");
    setTimeout(function () { card.classList.remove("is-flash"); }, 1500);
  }
  function flashBlock(blockId) {
    var b = qs('[data-block-id="' + blockId + '"]');
    if (!b) return;
    b.scrollIntoView({ block: "center", behavior: "smooth" });
    b.classList.add("is-flash");
    setTimeout(function () { b.classList.remove("is-flash"); }, 1500);
  }
  function jumpToAnnotation(tid) {
    var m = readerState.meta[tid];
    if (!m) { toast("目标批注不存在（可能已删除）"); return; }
    if (m.paper_id === readerState.paperId) { flashCard(tid); return; }
    openReader(m.paper_id, tid);  // 跨论文：整篇切换后高亮目标卡片
  }

  /* 导出 Markdown（拍板 P8：标题/元信息/逐条批注 quote+body+链接，.md 下载） */
  function exportReaderMd() {
    var order = {};
    var pageOf = {};
    readerState.blocks.forEach(function (b, i) {
      order[b.block_id] = i;
      pageOf[b.block_id] = b.page_idx + 1;
    });
    var anns = (readerState.annotations || []).slice().sort(function (x, y) {
      var ox = order[x.anchor_block_id];
      var oy = order[y.anchor_block_id];
      if (ox == null) ox = 999999;
      if (oy == null) oy = 999999;
      return ox - oy || x.id - y.id;
    });
    var lines = [
      "# " + (readerState.title || ("文献 #" + readerState.paperId)),
      "",
      "> 流光咖啡馆 · 文献批注导出 · " + localToday() + " · 共 " + anns.length + " 条批注",
      "",
    ];
    if (readerState.legacyNote) {
      lines.push("## 全文笔记", "", readerState.legacyNote, "");
    }
    anns.forEach(function (a, i) {
      var page = pageOf[a.anchor_block_id];
      lines.push("## " + (i + 1) + ". " + a.anchor_block_id + (page ? "（第 " + page + " 页）" : ""));
      lines.push("");
      lines.push("> " + String(a.anchor_quote || "").replace(/\s+/g, " "));
      lines.push("");
      if (a.body) { lines.push(a.body); lines.push(""); }
      if ((a.links || []).length) {
        var parts = a.links.map(function (tid) {
          var m = readerState.meta[tid];
          if (!m) return "#" + tid;
          var where = m.paper_id === readerState.paperId ? "" : "（他篇：" + (m.paper_title || m.paper_id) + "）";
          return "#" + tid + " “" + String(m.anchor_quote || "").slice(0, 40) + "”" + where;
        });
        lines.push("链接：" + parts.join("；"));
        lines.push("");
      }
    });
    var blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    var aEl = document.createElement("a");
    var slug = (readerState.title || "paper").replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 60);
    aEl.href = URL.createObjectURL(blob);
    aEl.download = slug + "-批注.md";
    document.body.appendChild(aEl);
    aEl.click();
    setTimeout(function () { URL.revokeObjectURL(aEl.href); aEl.remove(); }, 500);
    toast("已导出 " + anns.length + " 条批注");
  }

  /* ================= 订阅设置弹窗（步 C；P5 拍板：文献页内齿轮单入口） =================
   * 区块：订阅关键词 / AI 生成 / 检索条件（P21）/ 数据源市场（P17：含待接入源展示）。
   * 读写通道：GET /me（subscribe_keywords / subscribe_sources / papers_prefs）+ PUT /me/settings。 */
  var subState = {
    loaded: false, keywords: [], sources: [], allSources: [], baseline: "",
    p21: { year_from: null, year_to: null, authors: [], if_min: null }  // P21 抓取期过滤
  };
  var SUB_DEFAULT_SOURCES = ["pubmed", "arxiv", "openalex"];

  function subSnapshot() { return JSON.stringify({ k: subState.keywords, s: subState.sources, p: subState.p21 }); }
  function subRefreshSaveBtn() {
    var btn = qs("[data-sub-save]");
    if (btn) btn.disabled = subSnapshot() === subState.baseline;
  }
  function renderSubKeywords() {
    var box = qs("[data-sub-kw-box]");
    if (!box) return;
    var input = qs("[data-sub-kw-input]");
    var tags = subState.keywords.map(function (k, i) {
      return '<span class="sub-kw-tag">' + esc(k) +
        '<button class="sub-kw-del" type="button" data-sub-kw-del="' + i + '" aria-label="移除"><i data-ic="close"></i></button></span>';
    }).join("");
    box.innerHTML = tags + '<input class="sub-kw-input" type="text" data-sub-kw-input placeholder="输入关键词，回车添加" autocomplete="off">';
    injectIcons(box);
    var ni = qs("[data-sub-kw-input]", box);
    if (ni && input && document.activeElement === input) ni.focus();
  }
  /* 数据源（P17 两段式：第一层摘要 chips + 「管理数据源」→ 第二层选择页弹窗）
   * 选择页：搜索 + 七分类可折叠分组；已接源可勾选；待接入源灰显禁勾 + 「待接入」徽标；
   * 需 key/收费源未配 key 时给「去 Key 管理配置」引导链接（链到平台管理 Key 页签） */
  var SUB_COST_LABELS = { free: "免费", free_key: "免费·需 Key", paid: "收费" };
  /* 七分类固定顺序（与后端 catalog.py 拍板顺序一致） */
  var SUB_CATEGORIES = ["综合索引", "生物医学", "理工", "社科人文", "中文国内", "商业收费", "开放期刊"];
  /* 选择页草稿态：draft 独立于 subState.sources，保存才写回；取消/关弹窗即丢弃 */
  var srcPickState = { draft: [], query: "", collapsed: {} };
  /* 第一层摘要：已选源紧凑 chips（最多展示前 3 个名）+ 数量；点「管理数据源」进选择页 */
  function renderSubSummary() {
    var box = qs("[data-sub-src-summary]");
    if (!box) return;
    if (!subState.loaded) {
      box.innerHTML = '<span class="muted" style="font-size:13px;">加载中…</span>';
      return;
    }
    if (!subState.sources.length) {
      box.innerHTML = '<span class="muted" style="font-size:13px;">未选择数据源</span>';
      return;
    }
    var byKey = {};
    subState.allSources.forEach(function (s) { byKey[s.key] = s; });
    var names = subState.sources.map(function (k) {
      var s = byKey[k];
      return s ? s.name : k;
    });
    var shown = names.slice(0, 3).map(function (n) {
      return '<span class="sub-src-chip">' + esc(n) + "</span>";
    }).join("");
    /* 超过 3 个：第 4 个起折叠为「等 N 个」（已含总数，不再重复计数徽标） */
    var tail = names.length > 3
      ? '<span class="muted" style="font-size:12.5px;">等 ' + names.length + " 个</span>"
      : '<span class="sub-src-chip sub-src-chip-count">共 ' + names.length + " 个</span>";
    box.innerHTML = shown + tail;
  }
  /* 第二层选择页：打开时以当前已选为草稿 */
  function openSrcPicker() {
    srcPickState.draft = subState.sources.slice();
    srcPickState.query = "";
    srcPickState.collapsed = {};
    var q = qs("[data-src-pick-q]");
    if (q) q.value = "";
    renderSrcPicker();
    openModal("#modal-papers-src");
  }
  /* 选择页渲染：搜索按名称过滤；七分类分组（可折叠，搜索时强制展开） */
  function renderSrcPicker() {
    var list = qs("[data-src-pick-list]");
    if (!list) return;
    var q = srcPickState.query.trim().toLowerCase();
    var srcs = subState.allSources.filter(function (s) {
      return !q || (s.name || "").toLowerCase().indexOf(q) !== -1;
    });
    if (!srcs.length) {
      list.innerHTML = '<div class="muted" style="padding:14px 2px;font-size:13px;">没有匹配的数据源</div>';
      renderSrcPickCount();
      return;
    }
    var groups = SUB_CATEGORIES.map(function (cat) {
      return { cat: cat, items: srcs.filter(function (s) { return s.category === cat; }) };
    }).filter(function (g) { return g.items.length; });
    /* 防御：后端新增未预知的分类，排在已知分类之后 */
    var known = {};
    SUB_CATEGORIES.forEach(function (c) { known[c] = true; });
    var others = srcs.filter(function (s) { return !known[s.category]; });
    if (others.length) groups.push({ cat: "其他", items: others });
    list.innerHTML = groups.map(function (g) {
      var collapsed = srcPickState.collapsed[g.cat] && !q;
      var onCount = g.items.filter(function (s) {
        return srcPickState.draft.indexOf(s.key) !== -1;
      }).length;
      var head = '<div class="src-cat-head' + (collapsed ? " is-collapsed" : "") +
        '" data-src-cat="' + esc(g.cat) + '" role="button" tabindex="0">' +
        '<i data-ic="down" class="src-cat-caret"></i>' +
        '<span class="src-cat-name">' + esc(g.cat) + "</span>" +
        '<span class="muted src-cat-num">' + onCount + "/" + g.items.length + "</span>" +
        "</div>";
      var body = collapsed ? "" : g.items.map(function (s) {
        var on = srcPickState.draft.indexOf(s.key) !== -1;
        var pending = !s.implemented;
        var needKey = !!(s.key_service && !s.key_configured);
        var badges = '<span class="sub-src-badge">' + esc(s.category) + "</span>" +
          '<span class="sub-src-badge' + (s.cost === "paid" ? " is-paid" : "") + '">' +
            esc(SUB_COST_LABELS[s.cost] || s.cost) + "</span>" +
          (pending ? '<span class="sub-src-badge is-pending-badge">待接入</span>' : "");
        var keyRow = needKey
          ? '<span class="sub-src-keyrow"><a href="#/admin" data-sub-keycfg="' + esc(s.key) +
            '" class="sub-src-keylink">去 Key 管理配置</a></span>'
          : "";
        return '<label class="sub-src-item' + (pending ? " is-pending" : "") + '">' +
          '<input type="checkbox" data-src-pick="' + esc(s.key) + '"' + (on ? " checked" : "") +
            (pending ? " disabled" : "") + "> " +
          '<span class="sub-src-main">' +
            '<span class="sub-src-name">' + esc(s.name) + badges + "</span>" +
            '<span class="sub-src-desc muted">' + esc(s.description || "") + "</span>" +
            keyRow +
          "</span></label>";
      }).join("");
      return '<div class="src-cat">' + head + body + "</div>";
    }).join("");
    injectIcons(list);
    renderSrcPickCount();
  }
  function renderSrcPickCount() {
    var el = qs("[data-src-pick-count]");
    if (el) el.textContent = "已选 " + srcPickState.draft.length + " 个";
  }
  /* P21 检索条件区回显 */
  function renderSubP21() {
    var yf = qs("[data-sub-yfrom]"), yt = qs("[data-sub-yto]");
    var au = qs("[data-sub-authors]"), ifm = qs("[data-sub-ifmin]");
    if (yf) yf.value = subState.p21.year_from != null ? String(subState.p21.year_from) : "";
    if (yt) yt.value = subState.p21.year_to != null ? String(subState.p21.year_to) : "";
    if (au) au.value = (subState.p21.authors || []).join(", ");
    if (ifm) ifm.value = subState.p21.if_min != null ? String(subState.p21.if_min) : "";
  }
  function renderSubAiPicked() {
    /* AI 生成区：已加入订阅词的词置灰（is-added），其余可点选追加 */
    qsa("[data-sub-ai-kw]").forEach(function (chip) {
      var on = subState.keywords.indexOf(chip.getAttribute("data-sub-ai-kw")) !== -1;
      chip.classList.toggle("is-added", on);
    });
  }
  function openSubscribeModal() {
    openModal("#modal-papers-sub");
    var out = qs("[data-sub-ai-out]");
    if (out) out.classList.add("hide");
    var desc = qs("[data-sub-ai-desc]");
    if (desc) desc.value = "";
    Promise.all([API.get("/me"), API.get("/papers/sources")]).then(function (rs) {
      var settings = (rs[0] && rs[0].settings) || {};
      var kws = ((settings.subscribe_keywords || {}).keywords) || [];
      /* 后端契约：value 必须是对象，subscribe_sources 存 {sources: [...]}（SettingUpsert.value: dict） */
      var srcObj = settings.subscribe_sources;
      var srcs = (srcObj && Array.isArray(srcObj.sources)) ? srcObj.sources : null;
      subState.keywords = kws.slice();
      subState.sources = (srcs && srcs.length) ? srcs.slice() : SUB_DEFAULT_SOURCES.slice();
      subState.allSources = rs[1] || [];
      /* P21 检索条件：与论文页同一份 papers_prefs（展示项以论文页已加载值为准） */
      var pp = settings.papers_prefs;
      if (pp && typeof pp === "object") {
        var yf = parseInt(pp.year_from, 10);
        subState.p21.year_from = (pp.year_from != null && !isNaN(yf)) ? yf : null;
        var yt = parseInt(pp.year_to, 10);
        subState.p21.year_to = (pp.year_to != null && !isNaN(yt)) ? yt : null;
        subState.p21.authors = (Array.isArray(pp.authors)
          ? pp.authors.map(String).map(function (a) { return a.trim(); }).filter(Boolean)
          : []);
        var ifm = parseFloat(pp.if_min);
        subState.p21.if_min = (pp.if_min != null && !isNaN(ifm) && ifm >= 0) ? ifm : null;
      } else {
        subState.p21 = { year_from: null, year_to: null, authors: [], if_min: null };
      }
      subState.loaded = true;
      subState.baseline = subSnapshot();
      renderSubKeywords();
      renderSubSummary();
      renderSubP21();
      subRefreshSaveBtn();
    }).catch(function (e) { toast(e.detail || "订阅设置加载失败"); });
  }
  function saveSubscribe() {
    var btn = qs("[data-sub-save]");
    if (btn) btn.disabled = true;
    /* papers_prefs = 论文页展示偏好 + P21 检索条件合并写回（同一份，拍板 P21） */
    var prefs = Object.assign({}, paperState.prefs, subState.p21);
    paperState.prefs = prefs;
    Promise.all([
      API.put("/me/settings", { key: "subscribe_keywords", value: { keywords: subState.keywords } }),
      API.put("/me/settings", { key: "subscribe_sources", value: { sources: subState.sources } }),
      API.put("/me/settings", { key: "papers_prefs", value: prefs })
    ]).then(function () {
      subState.baseline = subSnapshot();
      toast("订阅设置已保存");
      var dlg = qs("#modal-papers-sub");
      if (dlg && dlg.close) dlg.close();
    }).catch(function (e) {
      if (btn) btn.disabled = false;
      var msg = e && typeof e.detail === "string" ? e.detail : "保存失败";
      toast(msg);
    });
  }

  /* ================= 页面初始化 ================= */
  var INITS = {
    workspace: function (view) {
      /* Homarr 式拖拽排序（持久化到 localStorage） */
      var grid = qs(".bento-grid", view);
      if (!grid) return;
      var dragged = null;
      qsa(".bcard", grid).forEach(function (card) {
        card.addEventListener("dragstart", function (e) {
          dragged = card;
          card.classList.add("dragging");
          e.dataTransfer.effectAllowed = "move";
        });
        card.addEventListener("dragend", function () {
          card.classList.remove("dragging");
          var order = qsa(".bcard", grid).map(function (c) { return c.getAttribute("data-bcard"); });
          try { localStorage.setItem("lc_home_order", JSON.stringify(order)); } catch (err) {}
        });
        card.addEventListener("dragover", function (e) {
          e.preventDefault();
          if (!dragged || dragged === card) return;
          var rect = card.getBoundingClientRect();
          var before = (e.clientX - rect.left) < rect.width / 2;
          grid.insertBefore(dragged, before ? card : card.nextSibling);
        });
      });
      /* 活数据填充（卡片渲染后异步填充，不干扰拖拽绑定） */
      fillWorkspace(view);
    },

    apps: function (view) {
      renderAppsPage(view);
    },

    chat: function (view) {
      /* 活数据：模型池 + 会话列表（异步填充） */
      API.get("/chat/models").then(function (models) {
        liveModels = models || [];
        var def = liveModels.filter(function (m) { return m.is_default; })[0] || liveModels[0];
        chatState.modelId = def ? def.id : null;
        chatState.thinkingLevel = defaultThinkingOf(chatState.modelId);
        renderMpPop();
        var lbl = qs("[data-mp-label]", view);
        if (lbl) lbl.textContent = def ? def.name : "无可用模型";
        syncMpCheck();
        syncUploadBtn();
      }).catch(function (e) { toast(e.detail || "模型池加载失败"); });
      refreshConversations(true);
      syncPolishBtn();

      var sc = qs(".chat-scroll", view);
      if (sc) sc.scrollTop = sc.scrollHeight;
      /* 手机端会话抽屉开关 */
      var toggle = qs("#conv-toggle", view);
      var mq = window.matchMedia("(max-width: 900px)");
      function sync() { if (toggle) toggle.style.display = mq.matches ? "inline-flex" : "none"; }
      if (mq.addEventListener) mq.addEventListener("change", sync);
      sync();
    },

    money: function (view) {
      loadMoneyPage(view);
    },

    papers: function (view) {
      paperState.nav = "digest";
      paperState.items = [];
      paperState.digest = null;
      /* P18：偏好先就位再拉列表（未加载过则先 GET /me 读 papers_prefs） */
      if (paperState.prefsLoaded) loadPapersNav();
      else loadPapersPrefs().then(loadPapersNav);
      /* 轮①：拉一次我的文献在库态（卡片/详情「＋ 我的文献」按钮 ✓ 已在库） */
      ensureLibMap();
      /* P13：语义检索框回车即检索（与按钮同一入口，防抖 + loading 在 nlSearch 内） */
      var nlInput = qs("[data-pp-nlinput]", view);
      if (nlInput) {
        nlInput.addEventListener("keydown", function (e) {
          if (e.key === "Enter") {
            e.preventDefault();
            nlSearch(qs("[data-pp-nlsearch]"));
          }
        });
      }
    },

    /* 轮① P22：我的文献一级页（三栏；阅读器挂载态，批注交互与 P8 完全一致） */
    library: function () {
      /* 轮③ P27：设置小项回显依赖 papers_prefs（未加载则补拉） */
      if (!paperState.prefsLoaded) loadPapersPrefs();
      loadLibrary();
    },


    admin: function (view) {
      /* 权限：非管理员给出提示（服务端同样 403 兜底） */
      if (!LC_USER || (LC_USER.roles || []).indexOf("admin") === -1) {
        view.innerHTML = '<div class="page-head"><div><h1 class="page-title">平台管理</h1>' +
          '<div class="page-desc">需要管理员权限（admin:users / admin:models）</div></div></div>';
        return;
      }
      adminState.pvDetail = null;
      loadAdminTabData();
    },

    me: function () {},

    login: function (view) {
      var form = qs("#login-form", view);
      if (!form) return;
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var err = qs("[data-login-err]", view);
        if (err) err.classList.add("hide");
        var username = qs("#login-user", form).value.trim();
        var password = qs("#login-pass", form).value;
        var btn = form.querySelector("button[type=submit]");
        btn.disabled = true;
        API.post("/auth/login", { username: username, password: password }).then(function (d) {
          API.setToken(d.token);
          LC_USER = d.user;
          applyUserChrome();
          go("workspace");
        }).catch(function (ex) {
          if (err) { err.textContent = (ex && ex.detail) || "登录失败"; err.classList.remove("hide"); }
        }).then(function () { btn.disabled = false; });
      });
    }
  };

  /* ================= ⌘K 命令面板 ================= */
  var paletteItems = [
    { icon: "home", label: "工作台", hint: "页面", run: function () { go("workspace"); } },
    { icon: "chat", label: "AI 对话", hint: "页面", run: function () { go("chat"); } },
    { icon: "money", label: "记账本", hint: "页面", run: function () { go("money"); } },
    { icon: "edit", label: "我的文献", hint: "页面", run: function () { go("library"); } },
    { icon: "grid", label: "应用中心", hint: "页面", run: function () { go("apps"); } },
    { icon: "gear", label: "平台管理", hint: "页面", run: function () { go("admin"); } },
    { icon: "user", label: "我的", hint: "页面", run: function () { go("me"); } },
    { icon: "plus", label: "记一笔", hint: "动作", run: function () { go("money"); afterRender(function () { openModal("#modal-tx"); }); } },
    { icon: "spark", label: "AI 记一笔", hint: "动作", run: function () { go("money"); afterRender(function () { openModal("#modal-ai"); }); } },
    { icon: "chat", label: "新建对话", hint: "动作", run: function () { go("chat"); afterRender(function () { var b = qs("[data-new-conv]"); if (b) b.click(); }); } },
    { icon: "gear", label: "通用设置", hint: "设置", run: function () { openModal("#modal-set-general"); } },
    { icon: "grid", label: "应用设置", hint: "设置", run: function () { openModal("#modal-set-apps"); } },
    { icon: "shield", label: "管理设置", hint: "设置", run: function () { go("admin"); } },
    { icon: "logout", label: "退出登录", hint: "动作", run: function () { API.clearToken(); LC_USER = null; go("login"); } }
  ];
  var paletteOpen = false;
  var paletteFiltered = paletteItems;
  var paletteIndex = 0;

  function openModal(sel) {
    var m = qs(sel);
    if (!m) return;
    if (m.showModal) { if (!m.open) m.showModal(); }
    else m.classList.add("open");
  }
  function closeModal(el) {
    var m = el.closest("dialog.modal-mask") || el.closest(".modal-mask");
    if (!m) return;
    if (m.close) { if (m.open) m.close(); }
    else m.classList.remove("open");
  }

  function openPalette() {
    paletteOpen = true;
    var p = qs("#palette");
    p.classList.add("open");
    var input = qs("#palette-input");
    input.value = "";
    paletteIndex = 0;
    filterPalette("");
    setTimeout(function () { input.focus(); }, 30);
  }
  function closePalette() {
    paletteOpen = false;
    qs("#palette").classList.remove("open");
  }
  function filterPalette(q) {
    q = q.trim().toLowerCase();
    paletteFiltered = paletteItems.filter(function (it) {
      return !q || it.label.toLowerCase().indexOf(q) !== -1 || it.hint.toLowerCase().indexOf(q) !== -1;
    });
    paletteIndex = 0;
    renderPaletteList();
  }
  function renderPaletteList() {
    var list = qs("#palette-list");
    if (!paletteFiltered.length) {
      list.innerHTML = '<div class="palette-empty">没有匹配的命令</div>';
      return;
    }
    list.innerHTML = paletteFiltered.map(function (it, i) {
      return '<div class="palette-item' + (i === paletteIndex ? " active" : "") + '" data-pi="' + i + '">' +
        '<i data-ic="' + it.icon + '"></i><span class="pi-label">' + it.label + '</span>' +
        '<span class="pi-hint">' + it.hint + "</span></div>";
    }).join("");
    injectIcons(list);
  }
  function paletteExec(i) {
    var it = paletteFiltered[i];
    if (!it) return;
    closePalette();
    it.run();
  }

  /* ================= 全局事件委托 ================= */
  /* 轮③ P27：自动翻译开关（change 只触发一次，避免 label 文本点击的合成双击） */
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t && t.closest && t.closest("[data-lib-autotranslate]")) {
      saveAutoTranslate(t);
    }
  });
  document.addEventListener("click", function (e) {
    var el = e.target;

    var palItem = el.closest("[data-pi]");
    if (palItem) { paletteExec(parseInt(palItem.getAttribute("data-pi"), 10)); return; }
    if (el.closest("[data-open-palette]")) { openPalette(); return; }
    /* 点击面板外部遮罩关闭 */
    if (paletteOpen && el.closest && el.closest("#palette") && !el.closest(".palette-panel")) {
      closePalette();
      return;
    }
    /* 模型选择器：点击外部收起 */
    var mpPopEl = qs("[data-mp-pop]");
    if (mpPopEl && !mpPopEl.classList.contains("hide") && el.closest && !el.closest(".mp-wrap")) {
      mpPopEl.classList.add("hide");
    }
    /* 角色下拉：点击外部收起 */
    if (el.closest) {
      qsa(".role-pop:not(.hide)").forEach(function (p) {
        if (!el.closest(".role-cell")) rolePopCloseAll();
      });
    }
    /* 通用自定义下拉 xselect：点击外部收起（与角色下拉同一风格） */
    if (el.closest) {
      qsa(".xselect-pop:not(.hide)").forEach(function (p) {
        if (!el.closest("[data-xselect]")) xselectClosePop(p.closest("[data-xselect]"));
      });
      /* 模型指派「添加模型」的临时 xselect 锚点：弹层已收起且点击落在锚点外 → 清理 */
      qsa(".chain-addpop").forEach(function (w) {
        if (el.closest(".chain-addpop")) return;
        var r = qs("[data-xselect]", w);
        var p = r ? qs("[data-xselect-pop]", r) : null;
        if (p && p.classList.contains("hide") && w.parentNode) w.parentNode.removeChild(w);
      });
    }
    /* 通用自定义下拉 xselect：触发器开关 / 选项选中（模型指派的「添加模型」选中即追加） */
    var xsT = el.closest("[data-xselect-trigger]");
    if (xsT) { xselectToggle(xsT.closest("[data-xselect]")); return; }
    var xsO = el.closest("[data-xselect-opt]");
    if (xsO) {
      var xsRootEl = xsO.closest("[data-xselect]");
      xselectPick(xsRootEl, xsO);
      if (xsRootEl.hasAttribute("data-asg-add-sel")) asgPickAdd(xsRootEl);
      return;
    }

    var opener = el.closest("[data-modal-open]");
    if (opener) {
      var targetSel = opener.getAttribute("data-modal-open");
      openModal(targetSel);
      /* 打开新建密钥弹窗时恢复创建场景的标题与一次性明文文案（重新生成场景会改写它们） */
      if (targetSel === "#modal-token") {
        var tTitle = qs("#modal-token-title");
        if (tTitle) tTitle.textContent = "新建网关密钥";
        var tOnceLabel = qs("#token-once-label");
        if (tOnceLabel) tOnceLabel.textContent = "密钥已创建，只完整显示这一次，请立即复制";
        var tOnceBox = qs("#token-once");
        if (tOnceBox) tOnceBox.classList.add("hide");
      }
      if (targetSel === "#modal-set-general") { refreshAvatarPanel(); applyTheme(); } /* applyTheme 同步主题段高亮 */
      /* 我的技能：打开弹窗/应用设置时刷新已安装列表（含条数徽标） */
      if (targetSel === "#modal-set-apps") loadMySkills();
      if (targetSel === "#modal-skillhub") loadMySkills();
      return;
    }
    /* 头像设置（#modal-set-general 内，data-* 事件委托） */
    var avatarDot = el.closest("[data-avatar-color]");
    if (avatarDot) {
      saveAvatar({ type: "initial", color: avatarDot.getAttribute("data-avatar-color") });
      return;
    }
    if (el.closest("[data-avatar-upload]")) {
      var fileInput = qs("[data-avatar-file]");
      if (fileInput) fileInput.click();
      return;
    }
    if (el.closest("[data-avatar-reset]")) {
      localStorage.removeItem("lc_avatar");
      applyUserAvatar();
      toast("已恢复默认头像");
      return;
    }
    /* 主题切换（通用设置 · 跟随系统/浅色/深色 → user_settings.theme.mode） */
    var themeBtn = el.closest("[data-theme-mode]");
    if (themeBtn) {
      var mode = themeBtn.getAttribute("data-theme-mode");
      if (mode !== themeState.mode) {
        themeState.mode = mode;
        applyTheme();
        API.put("/me/settings", { key: "theme", value: { mode: mode } }).catch(function (e) {
          toast(e.detail || "主题偏好保存失败");
        });
      }
      return;
    }
    /* 订阅设置弹窗：关键词标签 × 移除 */
    var subKwDel = el.closest("[data-sub-kw-del]");
    if (subKwDel) {
      subState.keywords.splice(parseInt(subKwDel.getAttribute("data-sub-kw-del"), 10), 1);
      renderSubKeywords();
      renderSubAiPicked();
      subRefreshSaveBtn();
      return;
    }
    /* 订阅设置弹窗：点输入框区域任意处 → 聚焦输入框 */
    if (el.closest("[data-sub-kw-box]")) {
      var subInput = qs("[data-sub-kw-input]");
      if (subInput) subInput.focus();
      return;
    }
    /* 订阅设置弹窗：AI 生成关键词（大白话 → suggest-keywords → 可点选标签） */
    if (el.closest("[data-sub-ai-gen]")) {
      var descEl = qs("[data-sub-ai-desc]");
      var desc = descEl ? descEl.value.trim() : "";
      if (!desc) { toast("先用一句话描述你的研究方向"); return; }
      var genBtn = el.closest("[data-sub-ai-gen]");
      genBtn.disabled = true;
      var outEl = qs("[data-sub-ai-out]");
      if (outEl) {
        outEl.classList.remove("hide");
        outEl.innerHTML = '<span class="muted" style="font-size:13px;">AI 生成中…</span>';
      }
      API.post("/papers/suggest-keywords", { description: desc }).then(function (r) {
        genBtn.disabled = false;
        var kws = (r && r.keywords) || [];
        if (!kws.length) { if (outEl) outEl.innerHTML = '<span class="muted" style="font-size:13px;">未生成关键词，换个说法试试</span>'; return; }
        if (outEl) {
          outEl.innerHTML = kws.map(function (k) {
            return '<button class="sub-ai-chip" type="button" data-sub-ai-kw="' + esc(k) + '">' + esc(k) + "</button>";
          }).join("");
        }
        renderSubAiPicked();
      }).catch(function (e) {
        genBtn.disabled = false;
        if (outEl) outEl.classList.add("hide");
        toast(e.detail || "AI 生成失败");
      });
      return;
    }
    /* 订阅设置弹窗：点选 AI 生成的词 → 追加到订阅关键词（重复置灰不可再点） */
    var subAiKw = el.closest("[data-sub-ai-kw]");
    if (subAiKw && !subAiKw.classList.contains("is-added")) {
      var kw = subAiKw.getAttribute("data-sub-ai-kw");
      if (subState.keywords.indexOf(kw) === -1) {
        subState.keywords.push(kw);
        renderSubKeywords();
        renderSubAiPicked();
        subRefreshSaveBtn();
      }
      return;
    }
    /* 订阅设置弹窗：保存（脏状态亮起，写 subscribe_keywords + subscribe_sources） */
    if (el.closest("[data-sub-save]")) { saveSubscribe(); return; }
    /* 订阅设置弹窗：「管理数据源」→ 第二层选择页（第一层保持打开在其下） */
    if (el.closest("[data-sub-src-manage]")) { openSrcPicker(); return; }
    /* 数据源选择页：分类分组折叠/展开 */
    var catHead = el.closest("[data-src-cat]");
    if (catHead) {
      var cat = catHead.getAttribute("data-src-cat");
      srcPickState.collapsed[cat] = !srcPickState.collapsed[cat];
      renderSrcPicker();
      return;
    }
    /* 数据源选择页：保存 = 草稿写回并刷新第一层摘要（点亮保存按钮）；取消 = 丢弃草稿 */
    if (el.closest("[data-src-pick-save]")) {
      subState.sources = srcPickState.draft.slice();
      var pickDlg = qs("#modal-papers-src");
      if (pickDlg && pickDlg.close) { if (pickDlg.open) pickDlg.close(); }
      renderSubSummary();
      subRefreshSaveBtn();
      return;
    }
    if (el.closest("[data-src-pick-cancel]")) {
      var pickDlg2 = qs("#modal-papers-src");
      if (pickDlg2 && pickDlg2.close) { if (pickDlg2.open) pickDlg2.close(); }
      return;
    }
    /* 我的技能：「上传技能」按钮 → 触发隐藏 file input */
    if (el.closest("[data-skill-upload]")) {
      var skillFile = qs("[data-skill-file]");
      if (skillFile) skillFile.click();
      return;
    }
    /* 弹层间切换：关掉当前，打开目标 */
    var switcher = el.closest("[data-modal-switch]");
    if (switcher) {
      var cur = switcher.closest(".modal-mask");
      if (cur && cur.close) { if (cur.open) cur.close(); } else if (cur) cur.classList.remove("open");
      var switchTarget = switcher.getAttribute("data-modal-switch");
      openModal(switchTarget);
      if (switchTarget === "#modal-skillhub") loadMySkills();
      return;
    }
    var closer = el.closest("[data-modal-close]");
    if (closer) { closeModal(closer); return; }
    if (el.classList && el.classList.contains("modal-mask")) {
      if (el.close) { if (el.open) el.close(); } else el.classList.remove("open");
      return;
    }

    if (el.closest("[data-open-sider]")) {
      qs("#sider").classList.add("open");
      qs("[data-drawer-mask]").classList.add("open");
      return;
    }
    if (el.closest("[data-open-conv]")) {
      var panel = qs(".conv-panel"), cmask = qs("[data-conv-mask]");
      if (panel) panel.classList.add("open");
      if (cmask) cmask.classList.add("open");
      return;
    }
    if (el.closest("[data-drawer-mask]")) { closeDrawers(); return; }
    if (el.closest("[data-conv-mask]")) {
      var p2 = qs(".conv-panel"), m2 = qs("[data-conv-mask]");
      if (p2) p2.classList.remove("open");
      if (m2) m2.classList.remove("open");
      return;
    }

    if (el.closest("[data-logout]")) {
      API.clearToken();
      LC_USER = null;
      chatState.convId = null;
      chatState.newConv = false;
      go("login");
      return;
    }

    /* 看板论文卡空态「去设置」：打开应用设置（订阅关键词），阻止整卡 <a> 默认跳转 */
    if (el.closest("[data-ws-paper-settings]")) {
      e.preventDefault();
      openModal("#modal-set-apps");
      loadMySkills();
      return;
    }
    /* 对话卡「新建对话」按钮 */
    if (el.closest("[data-new-conv-link]")) {
      e.preventDefault();
      go("chat");
      afterRender(function () {
        var b = qs("[data-new-conv]");
        if (b) b.click();
      });
      return;
    }

    var toastEl = el.closest("[data-toast]");
    if (toastEl) { toast(toastEl.getAttribute("data-toast")); return; }

    /* 分段控件（记一笔弹层的收支切换会联动分类 chips） */
    var segBtn = el.closest(".seg button");
    if (segBtn) {
      qsa("button", segBtn.closest(".seg")).forEach(function (b) { b.classList.remove("active"); });
      segBtn.classList.add("active");
      if (segBtn.closest("#modal-tx")) renderTxCatChips();
      return;
    }
    /* chips 单选 */
    var chip = el.closest("[data-chips] .chip");
    if (chip) {
      qsa(".chip", chip.closest("[data-chips]")).forEach(function (c) { c.classList.remove("active"); });
      chip.classList.add("active");
      return;
    }
    /* 代码块复制 */
    var copyBtn = el.closest("[data-copy]");
    if (copyBtn) {
      var code = copyBtn.closest(".codeblock").querySelector("code");
      if (code && navigator.clipboard) {
        navigator.clipboard.writeText(code.textContent).then(
          function () { toast("已复制到剪贴板"); },
          function () { toast("复制失败，请手动选择"); }
        );
      }
      return;
    }
    /* 入账提交（记一笔 / AI 记一笔共用；幂等键前端生成 UUID） */
    if (el.closest("[data-submit-tx]")) {
      var mm = el.closest(".modal-mask");
      var isAi = mm && mm.id === "modal-ai";
      var payload = null;
      if (isAi) {
        if (!aiDraft) { toast("先输入一句话并解析，确认草稿后再入账"); return; }
        var sugCat = moneyCats.filter(function (c) { return c.name === aiDraft.category_suggestion; })[0];
        if (!sugCat) sugCat = moneyCats.filter(function (c) { return c.kind === aiDraft.type || c.kind === "both"; })[0];
        if (!sugCat) { toast("没有可用分类，请先在分类管理里创建"); return; }
        payload = {
          request_id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()),
          amount: aiDraft.amount,
          type: aiDraft.type,
          category_id: sugCat.id,
          note: aiDraft.note || "",
          date: aiDraft.date
        };
      } else {
        var amountInput = mm.querySelector("[data-amount-input]");
        var fenV = Math.round(parseFloat((amountInput && amountInput.value) || "0") * 100);
        var segActive = mm.querySelector(".seg button.active");
        var type = segActive && segActive.textContent.trim() === "收入" ? "income" : "expense";
        var chipActive = mm.querySelector("[data-tx-cats] .chip.active");
        var noteInput = mm.querySelector("[data-tx-note]");
        var dateInput = mm.querySelector("[data-tx-date]");
        if (!fenV || fenV <= 0) { toast("先填金额"); return; }
        if (!chipActive || !chipActive.getAttribute("data-cid")) { toast("先选择分类"); return; }
        payload = {
          request_id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()),
          amount: fenV,
          type: type,
          category_id: parseInt(chipActive.getAttribute("data-cid"), 10),
          note: (noteInput && noteInput.value.trim()) || "",
          date: (dateInput && dateInput.value) || localToday()
        };
      }
      var btn = el.closest("[data-submit-tx]");
      btn.disabled = true;
      API.post("/money/transactions", payload).then(function () {
        if (mm && mm.close) mm.close(); else if (mm) mm.classList.remove("open");
        aiDraft = null;
        toast("已入账");
        loadMoneyPage();
      }).catch(function (ex) {
        toast(ex.detail || "入账失败");
      }).then(function () { btn.disabled = false; });
      return;
    }
    /* AI 记一笔解析（POST /money/parse，草稿不落库） */
    var parseBtn = el.closest("[data-ai-parse]");
    if (parseBtn) {
      var bodyEl = parseBtn.closest(".modal-body");
      var input = bodyEl.querySelector("textarea");
      var preview = bodyEl.querySelector("[data-parse-preview]");
      var loading = bodyEl.querySelector("[data-parse-loading]");
      if (!input.value.trim()) { toast("先输入一句话，比如：昨晚和朋友吃火锅花了 128"); return; }
      if (loading) loading.classList.remove("hide");
      if (preview) preview.classList.add("hide");
      parseBtn.disabled = true;
      API.post("/money/parse", { text: input.value.trim() }).then(function (d) {
        aiDraft = d;
        if (loading) loading.classList.add("hide");
        if (preview) {
          preview.classList.remove("hide");
          var amt = preview.querySelector("[data-pv-amount]");
          amt.textContent = fen(d.amount);
          amt.className = "v " + (d.type === "expense" ? "expense" : "income");
          preview.querySelector("[data-pv-type]").textContent = d.type === "expense" ? "支出" : "收入";
          preview.querySelector("[data-pv-cat]").textContent = d.category_suggestion;
          preview.querySelector("[data-pv-note]").textContent = d.note || "—";
          preview.querySelector("[data-pv-date]").textContent = d.date;
          var conf = preview.querySelector("[data-pv-confidence]");
          if (conf) conf.textContent = (d.confidence != null ? "置信度 " + d.confidence + " · " : "") + "可修改后确认入账";
        }
      }).catch(function (ex) {
        if (loading) loading.classList.add("hide");
        toast(ex.detail || "解析失败，请手动记一笔");
      }).then(function () { parseBtn.disabled = false; });
      return;
    }
    /* 成员行 → 详情抽屉（Supabase 侧栏模式）：拉详情后渲染 */
    var urow = el.closest("[data-user-row]");
    if (urow && !el.closest(".switch") && !el.closest(".role-cell") && !el.closest("button")) {
      var uid = urow.getAttribute("data-user-row");
      API.get("/admin/users/" + uid).then(function (uu) {
        var dr = qs("[data-udrawer]"), mk = qs("[data-ud-mask]");
        if (uu && dr) { dr.innerHTML = udrawerHtml(uu); injectIcons(dr); dr.classList.remove("hide"); }
        if (mk) mk.classList.remove("hide");
      }).catch(function (e) { toast(e.detail || "详情加载失败"); });
      return;
    }
    if (el.closest("[data-ud-close]") || el.closest("[data-ud-mask]")) {
      var dr2 = qs("[data-udrawer]"), mk2 = qs("[data-ud-mask]");
      if (dr2) dr2.classList.add("hide");
      if (mk2) mk2.classList.add("hide");
      return;
    }
    /* 角色下拉（Zeda 模式：选项带权限说明）→ 整体重设角色 */
    if (el.closest("[data-role-picker]")) {
      var rpCell = el.closest(".role-cell");
      var rpPop = qs(".role-pop", rpCell);
      if (rpPop) {
        if (rpPop.classList.contains("hide")) rolePopOpen(rpCell);
        else { rpPop.classList.add("hide"); rolePopBindViewport(false); }
      }
      return;
    }
    var roleOpt = el.closest("[data-role-opt]");
    if (roleOpt) {
      var rid2 = parseInt(roleOpt.getAttribute("data-role-opt"), 10);
      var uid2 = roleOpt.getAttribute("data-uid");
      rolePopCloseAll();
      API.put("/admin/users/" + uid2 + "/roles", { role_ids: [rid2] }).then(function () {
        return API.get("/admin/users?page_size=100");
      }).then(function (p) {
        adminState.users = (p && p.items) || [];
        renderUsersTab();
        toast("角色已更新");
      }).catch(function (e) { toast(e.detail || "角色更新失败"); });
      return;
    }
    /* 抽屉权限开关：应用到该用户的全部角色（整体重设） */
    var permSwEl = el.closest("[data-perm-switch]");
    if (permSwEl && el.closest("[data-udrawer]")) {
      setSwitch(permSwEl, !permSwEl.classList.contains("on"));
      var drawer = el.closest("[data-udrawer]");
      var codes = qsa("[data-perm-switch].on", drawer).map(function (s) { return s.getAttribute("data-perm-switch"); });
      var head = drawer.querySelector(".ud-sub");
      var username = head ? (head.textContent.match(/@([^\s·]+)/) || [])[1] : null;
      var target = adminState.users.filter(function (u) { return u.username === username; })[0];
      if (!target) return;
      var roleIds = (target.roles || []).map(function (r) { return r.id; });
      Promise.all(roleIds.map(function (rid3) {
        return API.put("/admin/roles/" + rid3 + "/permissions", { permissions: codes });
      })).then(function () {
        toast("权限已应用到角色");
        return API.get("/admin/roles");
      }).then(function (r) {
        adminState.roles = r || [];
        renderRoleMatrix();
      }).catch(function (e) { toast(e.detail || "权限更新失败"); });
      return;
    }
    /* 提供商启用开关 */
    var pvToggle = el.closest("[data-provider-toggle]");
    if (pvToggle) {
      var tpid = pvToggle.getAttribute("data-provider-toggle");
      var cur = adminState.pvDetail;
      API.put("/admin/models/providers/" + tpid, { enabled: !(cur && cur.enabled) }).then(function () {
        toast("提供商状态已更新");
        selectProvider(tpid);
      }).catch(function (e) { toast(e.detail || "更新失败"); });
      return;
    }
    /* 模型启用开关 */
    var mEnable = el.closest("[data-model-enable]");
    if (mEnable) {
      var mid3 = mEnable.getAttribute("data-model-enable");
      var rowEl = mEnable.closest(".mm-model");
      var nowOn = mEnable.classList.contains("on");
      API.put("/admin/models/providers/" + adminState.pvDetail.id + "/models/" + mid3, { enabled: !nowOn }).then(function () {
        setSwitch(mEnable, !nowOn);
        toast(!nowOn ? "模型已启用" : "模型已停用");
      }).catch(function (e) { toast(e.detail || "更新失败"); });
      return;
    }
    /* 我的技能：开关（关闭即停止注入）/ 卸载（功能列 Skill / 应用设置 · 对话 · 已安装技能） */
    var myToggle = el.closest("[data-myskill-toggle]");
    if (myToggle) {
      var myId = myToggle.getAttribute("data-myskill-toggle");
      var nowOn = myToggle.getAttribute("data-enabled") === "1";
      API.skills.setEnabled(myId, !nowOn).then(function () {
        toast(!nowOn ? "已开启，下次对话生效" : "已关闭，停止注入");
        loadMySkills();
      }).catch(function (e) { toast(e.detail || "操作失败"); });
      return;
    }
    var myDel = el.closest("[data-myskill-del]");
    if (myDel) {
      var delId2 = myDel.getAttribute("data-myskill-del");
      if (!window.confirm("卸载该技能？将同时删除本地技能目录，其提示词不再注入对话。")) return;
      API.skills.uninstall(delId2).then(function () {
        toast("已卸载");
        loadMySkills();
      }).catch(function (e) { toast(e.detail || "卸载失败"); });
      return;
    }
    /* 思维面板：标题行展开/收起（仅最后一条记忆折叠态，N-增3） */
    var thinkToggle = el.closest("[data-think-toggle]");
    if (thinkToggle) {
      var box = thinkToggle.closest(".think-box");
      if (box) {
        var willOpen = !box.classList.contains("open");
        box.classList.toggle("open", willOpen);
        var tb = box.querySelector(".think-body");
        if (tb) tb.classList.toggle("hide", !willOpen);
        if (box.hasAttribute && box.hasAttribute("data-think-last")) saveThinkOpenPref(willOpen);
      }
      return;
    }
    /* 润色按钮（P0-3） */
    var polishBtn = el.closest("[data-polish]");
    if (polishBtn) {
      if (polishBtn.classList.contains("is-disabled")) { toast("输入非空且不超过 4000 字时可润色"); return; }
      doPolish(polishBtn);
      return;
    }
    /* 管理端 · 编辑模型：打开 meta 配置弹窗（P1-1 思考档位子表单） */
    var editMeta = el.closest("[data-edit-meta]");
    if (editMeta) { openModelMetaModal(parseInt(editMeta.getAttribute("data-edit-meta"), 10)); return; }
    /* 思考模式开关（弹窗子表单显隐；须先于通用 switch 兜底） */
    var mmReasonSw = el.closest("[data-mm-reasoning-enabled]");
    if (mmReasonSw) {
      setSwitch(mmReasonSw, !mmReasonSw.classList.contains("on"));
      var mmBox = qs("[data-mm-reasoning-box]");
      if (mmBox) mmBox.classList.toggle("hide", !mmReasonSw.classList.contains("on"));
      return;
    }
    /* 档位行：增删 */
    if (el.closest("[data-mm-lv-add]")) {
      var rowsBox = qs("[data-mm-lv-rows]");
      if (rowsBox) {
        rowsBox.insertAdjacentHTML("beforeend", lvRowHtml("", ""));
        injectIcons(rowsBox);
        refreshMmDefaultOptions();
      }
      return;
    }
    var lvDel = el.closest("[data-lv-del]");
    if (lvDel) {
      var lvRow = lvDel.closest("[data-lv-row]");
      if (lvRow) { lvRow.remove(); refreshMmDefaultOptions(); }
      return;
    }
    /* 模型 meta 保存（思考档位整体提交，服务端 Pydantic 校验） */
    if (el.closest("[data-mm-save]")) { saveModelMeta(); return; }
    /* 其他场景的通用滑动开关（演示页兜底；管理页模型指派开关走 data-asg-toggle 专属逻辑） */
    var sw = el.closest(".switch");
    if (sw && !el.closest("[data-udrawer]") && !el.closest("[data-asg-toggle]")) { setSwitch(sw, !sw.classList.contains("on")); toast("已更新（演示）"); return; }

    /* 模型管理：切换提供商条目 */
    var mmItem = el.closest("[data-pv]");
    if (mmItem && !el.closest(".btn")) {
      selectProvider(mmItem.getAttribute("data-pv"));
      return;
    }
    /* 添加提供商：表单弹窗 #modal-add-pv 提交 */
    if (el.closest("[data-confirm-add-pv]")) {
      var pvName = qs("#modal-add-pv [data-pv-name]");
      var pvVendor = qs("#modal-add-pv [data-pv-vendor]");
      var pvUrl = qs("#modal-add-pv [data-pv-url]");
      var pvKey = qs("#modal-add-pv [data-pv-key]");
      var npv = pvName ? pvName.value.trim() : "";
      if (!npv) { toast("先填提供商名称"); return; }
      API.post("/admin/models/providers", {
        name: npv,
        vendor: pvVendor ? pvVendor.value : "custom",
        base_url: pvUrl ? pvUrl.value.trim() : "",
        api_key: pvKey ? pvKey.value.trim() : ""
      }).then(function () {
        toast("提供商已创建");
        var pvMask = qs("#modal-add-pv");
        if (pvMask && pvMask.close) pvMask.close(); else if (pvMask) pvMask.classList.remove("open");
        if (pvName) pvName.value = "";
        if (pvVendor) pvVendor.value = "custom";
        if (pvUrl) pvUrl.value = "";
        if (pvKey) pvKey.value = "";
        loadAdminTabData();
      }).catch(function (e) { toast(e.detail || "创建失败"); });
      return;
    }
    /* 设为默认模型（默认路由两标记切换） */
    var setDef = el.closest("[data-set-default]");
    if (setDef) {
      var mid4 = parseInt(setDef.getAttribute("data-set-default"), 10);
      API.put("/admin/models/default-route", { provider_id: adminState.pvDetail.id, model_id: mid4 }).then(function () {
        toast("默认路由已切换");
        selectProvider(adminState.pvDetail.id);
      }).catch(function (e) { toast(e.detail || "切换失败"); });
      return;
    }
    /* 删除自定义模型 */
    var delModel = el.closest("[data-del-model]");
    if (delModel) {
      var mid5 = delModel.getAttribute("data-del-model");
      if (!window.confirm("删除该自定义模型？（若被默认路由引用会先报错）")) return;
      API.del("/admin/models/providers/" + adminState.pvDetail.id + "/models/" + mid5).then(function () {
        toast("模型已删除");
        selectProvider(adminState.pvDetail.id);
      }).catch(function (e) { toast(e.detail || "删除失败"); });
      return;
    }
    /* 添加自定义模型：先展开输入行 */
    if (el.closest("[data-add-model]")) {
      var addRow = qs("[data-mm-add]");
      if (addRow) addRow.classList.toggle("hide");
      return;
    }
    var confirmAdd = el.closest("[data-confirm-add]");
    if (confirmAdd) {
      var nameInput = qs("[data-am-name]");
      var mname = nameInput ? nameInput.value.trim() : "";
      if (!mname) { toast("先填模型名"); return; }
      API.post("/admin/models/providers/" + adminState.pvDetail.id + "/models", { name: mname }).then(function () {
        toast("自定义模型已添加");
        selectProvider(adminState.pvDetail.id);
      }).catch(function (e) { toast(e.detail || "添加失败"); });
      return;
    }
    /* 拉取模型（官方 API 平铺入库） */
    var fetchBtn = el.closest("[data-fetch]");
    if (fetchBtn) {
      var fpid = fetchBtn.getAttribute("data-fetch");
      var bl = fetchBtn.querySelector(".bl");
      fetchBtn.disabled = true;
      if (bl) bl.textContent = "拉取中…";
      API.post("/admin/models/providers/" + fpid + "/fetch-models", {}).then(function (arr) {
        toast("已入库 " + (arr ? arr.length : 0) + " 个模型");
        selectProvider(fpid);
      }).catch(function (e) {
        toast(e.detail || "拉取失败");
        fetchBtn.disabled = false;
        if (bl) bl.textContent = "拉取模型";
      });
      return;
    }
    /* 测试连通性 */
    var testBtn = el.closest("[data-test-pv]");
    if (testBtn) {
      var tpid2 = testBtn.getAttribute("data-test-pv");
      var bl2 = testBtn.querySelector(".bl");
      testBtn.disabled = true;
      if (bl2) bl2.textContent = "测试中…";
      API.post("/admin/models/providers/" + tpid2 + "/test", {}).then(function (r) {
        toast(r.ok ? "连通正常 · 延迟 " + r.latency_ms + "ms" : "连接失败：" + (r.error || "未知错误"));
      }).catch(function (e) { toast(e.detail || "测试失败"); })
        .then(function () {
          testBtn.disabled = false;
          if (bl2) bl2.textContent = "测试连通性";
        });
      return;
    }
    /* 保存提供商配置（Key 留空不修改） */
    var savePv = el.closest("[data-save-pv]");
    if (savePv) {
      var spid = savePv.getAttribute("data-save-pv");
      var baseEl = qs("#mm-detail [data-pv-base]");
      var keyEl = qs("#mm-detail [data-pv-key]");
      var body = { base_url: baseEl ? baseEl.value.trim() : "" };
      if (keyEl && keyEl.value.trim()) body.api_key = keyEl.value.trim();
      API.put("/admin/models/providers/" + spid, body).then(function () {
        toast("配置已保存");
        selectProvider(spid);
      }).catch(function (e) { toast(e.detail || "保存失败"); });
      return;
    }
    /* 抽屉：重置密码 / 停用账号 */
    var resetBtn = el.closest("[data-reset-pass]");
    if (resetBtn && !resetBtn.disabled) {
      var ruid = resetBtn.getAttribute("data-reset-pass");
      API.post("/admin/users/" + ruid + "/reset-password", {}).then(function (r) {
        var kv = qs("[data-reset-result]");
        if (kv) {
          kv.style.display = "";
          kv.querySelector("span:last-child").textContent = r.new_password + "（仅显示一次）";
        }
        toast("已生成一次性新密码");
      }).catch(function (e) { toast(e.detail || "重置失败"); });
      return;
    }
    var disableBtn = el.closest("[data-disable-account]");
    if (disableBtn && !disableBtn.disabled) {
      var duid = disableBtn.getAttribute("data-disable-account");
      if (!window.confirm("停用该账号？其将立即无法登录。")) return;
      API.put("/admin/users/" + duid, { is_active: false }).then(function () {
        toast("账号已停用");
        var dr3 = qs("[data-udrawer]"), mk3 = qs("[data-ud-mask]");
        if (dr3) dr3.classList.add("hide");
        if (mk3) mk3.classList.add("hide");
        return API.get("/admin/users?page_size=100");
      }).then(function (p) {
        adminState.users = (p && p.items) || [];
        renderUsersTab();
      }).catch(function (e) { toast(e.detail || "操作失败"); });
      return;
    }
    /* 网关密钥：重新生成 / 删除 / 复制接入地址 */
    var rotate = el.closest("[data-rotate-token]");
    if (rotate) {
      var rotId = rotate.getAttribute("data-rotate-token");
      var oldTok = null;
      adminState.tokens.forEach(function (x) { if (String(x.id) === String(rotId)) oldTok = x; });
      if (!oldTok) { toast("密钥不存在或已删除"); return; }
      if (!window.confirm("重新生成将立即删除旧密钥并生成同名新密钥，调用方需更换密钥。继续？")) return;
      rotate.disabled = true;
      var rotName = oldTok.name;
      var rotScope = oldTok.model_scope === undefined ? null : oldTok.model_scope;
      /* 组合 DELETE（立即删除旧）+ POST（同名同模型范围新建），后端零改动 */
      API.del("/admin/models/gateway-tokens/" + rotId).then(function () {
        return API.post("/admin/models/gateway-tokens", { name: rotName, model_scope: rotScope });
      }).then(function (r) {
        var onceEl = qs("#token-once");
        if (onceEl) {
          onceEl.classList.remove("hide");
          var codeEl2 = onceEl.querySelector("code");
          if (codeEl2) codeEl2.textContent = r.token;
          var lblEl = onceEl.querySelector("#token-once-label");
          if (lblEl) lblEl.textContent = "密钥已重新生成，旧密钥已失效，只完整显示这一次，请立即复制";
        }
        var ttlEl = qs("#modal-token-title");
        if (ttlEl) ttlEl.textContent = "重新生成密钥";
        toast("已重新生成，旧密钥已失效");
        openModal("#modal-token");
        return API.get("/admin/models/gateway-tokens");
      }).then(function (t) {
        adminState.tokens = (t || []).filter(function (x) { return x.active; });
        renderTokenRows();
      }).catch(function (e) {
        /* DELETE 已成功但 POST 失败：旧密钥已不可逆删除，提示手动补建 */
        toast("旧密钥已删除，新建失败，请手动新建" + (e && e.detail ? "（" + e.detail + "）" : ""));
        API.get("/admin/models/gateway-tokens").then(function (t) {
          adminState.tokens = (t || []).filter(function (x) { return x.active; });
          renderTokenRows();
        }).catch(function () {});
      }).then(function () { rotate.disabled = false; });
      return;
    }
    var revoke = el.closest("[data-revoke-token]");
    if (revoke) {
      var tid = revoke.getAttribute("data-revoke-token");
      if (!window.confirm("删除该密钥？调用方将立即失效。")) return;
      API.del("/admin/models/gateway-tokens/" + tid).then(function () {
        toast("密钥已删除，调用方立即失效");
        return API.get("/admin/models/gateway-tokens");
      }).then(function (t) {
        /* 已删除行直接从列表移除，不再显示「已删除」残留 */
        adminState.tokens = (t || []).filter(function (x) { return x.active; });
        renderTokenRows();
      }).catch(function (e) { toast(e.detail || "删除失败"); });
      return;
    }
    var copyText = el.closest("[data-copy-text]");
    if (copyText) {
      var target = qs(copyText.getAttribute("data-copy-text"));
      if (target && navigator.clipboard) {
        navigator.clipboard.writeText(target.textContent).then(function () { toast("已复制"); }, function () { toast("复制失败"); });
      }
      return;
    }
    /* 新建网关密钥（完整密钥仅显示一次） */
    var createToken = el.closest("[data-create-token]");
    if (createToken) {
      var tname = qs("#token-name");
      var scopeChip = qs('[data-token-scope] .chip.active');
      var once = qs("#token-once");
      if (!tname || !tname.value.trim()) { toast("先给密钥起个名字，比如 n8n"); return; }
      var scope = null;
      if (scopeChip && scopeChip.textContent.trim() === "仅默认模型") {
        scope = adminState.defaultRoute && adminState.defaultRoute.model ? [adminState.defaultRoute.model.name] : [];
      }
      createToken.disabled = true;
      API.post("/admin/models/gateway-tokens", { name: tname.value.trim(), model_scope: scope }).then(function (r) {
        if (once) {
          once.classList.remove("hide");
          var code = once.querySelector("code");
          if (code) code.textContent = r.token;
        }
        toast("密钥已创建，只完整显示这一次");
        return API.get("/admin/models/gateway-tokens");
      }).then(function (t) {
        adminState.tokens = (t || []).filter(function (x) { return x.active; });
        renderTokenRows();
      }).catch(function (e) { toast(e.detail || "创建失败"); })
        .then(function () { createToken.disabled = false; });
      return;
    }
    /* 密钥一次性明文复制 */
    var copyOnce = el.closest("[data-copy-once]");
    if (copyOnce) {
      var codeEl = copyOnce.closest(".token-once-row").querySelector("code");
      if (codeEl && navigator.clipboard) {
        navigator.clipboard.writeText(codeEl.textContent).then(function () { toast("已复制"); }, function () { toast("复制失败"); });
      }
      return;
    }
    /* 模型选择器 */
    if (el.closest("[data-model-picker]")) {
      var pop = qs("[data-mp-pop]");
      if (pop) pop.classList.toggle("hide");
      return;
    }
    /* 模型选择器：思考档位按钮（P0-2，只换档位不换模型，弹层不收起） */
    var mpLevel = el.closest("[data-mp-level]");
    if (mpLevel) {
      chatState.thinkingLevel = mpLevel.getAttribute("data-mp-level");
      renderMpPop();
      syncMpCheck();
      return;
    }
    var mpItem = el.closest("[data-mp-item]");
    if (mpItem) {
      chatState.modelId = parseInt(mpItem.getAttribute("data-mp-item"), 10);
      /* 切模型 → 思考档位回落该模型默认档（P0-2 ⑤；无思考能力 → 清空） */
      chatState.thinkingLevel = defaultThinkingOf(chatState.modelId);
      var mName = "";
      liveModels.forEach(function (m) { if (m.id === chatState.modelId) mName = m.name; });
      var lbl = qs("[data-mp-label]");
      if (lbl) lbl.textContent = mName || "default";
      renderMpPop();
      syncMpCheck();
      var pop2 = qs("[data-mp-pop]");
      if (pop2) pop2.classList.add("hide");
      syncUploadBtn();
      toast("已切换模型：" + (mName || "默认路由"));
      return;
    }
    /* 文件上传 */
    var up = el.closest("[data-upload]");
    if (up) {
      if (up.classList.contains("is-disabled")) { toast("当前模型不支持文件，请切换到支持文件上传的模型"); return; }
      toast("文件上传演示：正式版经 POST /files 入库后随消息发送");
      return;
    }
    /* 我的：文献订阅关键词编辑（PUT /me/settings subscribe_keywords） */
    if (el.closest("[data-goto-me]")) { go("me"); return; }
    /* 修改密码（POST /auth/change-password） */
    if (el.closest("[data-pass-submit]")) {
      var oldEl = qs("[data-pass-old]"), newEl = qs("[data-pass-new]");
      var oldPass = oldEl ? oldEl.value : "";
      var newPass = newEl ? newEl.value : "";
      if (!oldPass || !newPass) { toast("请填写原密码与新密码"); return; }
      if (newPass.length < 6) { toast("新密码至少 6 位"); return; }
      var passBtn = el.closest("[data-pass-submit]");
      passBtn.disabled = true;
      API.post("/auth/change-password", { old_password: oldPass, new_password: newPass }).then(function () {
        var mm = qs("#modal-pass");
        if (mm && mm.close) mm.close(); else if (mm) mm.classList.remove("open");
        if (oldEl) oldEl.value = "";
        if (newEl) newEl.value = "";
        toast("密码已修改，下次登录请用新密码");
      }).catch(function (e) { toast(e.detail || "修改失败"); })
        .then(function () { passBtn.disabled = false; });
      return;
    }
    /* 分类管理：新建自定义分类 */
    if (el.closest("[data-create-cat]")) {
      var nameInput = qs("[data-new-cat-name]");
      var catName = nameInput ? nameInput.value.trim() : "";
      if (!catName) { toast("先填分类名称"); return; }
      var createBtn = el.closest("[data-create-cat]");
      createBtn.disabled = true;
      API.post("/money/categories", { name: catName, kind: "both" }).then(function () {
        if (nameInput) nameInput.value = "";
        toast("分类已创建");
        return API.get("/money/categories");
      }).then(function (cats) {
        moneyCats = cats || [];
        renderMoneyChips();
        renderTxCatChips();
        renderCatsModal();
      }).catch(function (e) { toast(e.detail || "创建失败"); })
        .then(function () { createBtn.disabled = false; });
      return;
    }
    /* 分类管理：删除自定义分类 */
    var delCat = el.closest("[data-del-cat]");
    if (delCat) {
      var delCid = delCat.getAttribute("data-del-cat");
      if (!window.confirm("删除该分类？名下有账目时会失败。")) return;
      API.del("/money/categories/" + delCid).then(function () {
        toast("分类已删除");
        return API.get("/money/categories");
      }).then(function (cats) {
        moneyCats = cats || [];
        renderMoneyChips();
        renderTxCatChips();
        renderCatsModal();
        loadMoneyPage();
      }).catch(function (e) { toast(e.detail || "删除失败"); });
      return;
    }
    /* 订阅设置统一走文献页齿轮入口（P5 拍板）：「我的 → 应用设置」不再重复放编辑入口 */
    if (el.closest("[data-kw-edit]")) { toast("请前往文献页，点右上角 ⚙ 订阅设置"); return; }
    /* 轮① P22：文献页左导航「我的文献」→ 一级页 #/library */
    if (el.closest("[data-pp-libnav]")) { go("library"); return; }
    /* 轮① P22：卡片/详情「＋ 我的文献」→ 幂等加入（已在库点击跳 #/library） */
    var pLibBtn = el.closest("[data-paper-lib]");
    if (pLibBtn) { addToLibrary(pLibBtn); return; }
    /* ── 轮① P22：我的文献页（# /library）交互 ── */
    /* 轮② P25：导入文献弹窗（打开/关闭/切路/提交/点遮罩取消） */
    if (el.closest("[data-lib-import]")) { openImportModal(); return; }
    /* 轮③ P27：我的文献设置小项（齿轮开弹层；开关用 change 委托见下） */
    if (el.closest("[data-lib-settings]")) { toggleLibSettings(); return; }
    if (el.closest("[data-lib-importclose]")) { closeImportModal(); return; }
    /* P30：上传/替换全文弹窗 */
    if (el.closest("[data-lib-ftclose]")) { closeFulltextModal(); return; }
    var ftSubmit = el.closest("[data-lib-ftsubmit]");
    if (ftSubmit) { submitFulltext(ftSubmit); return; }
    if (el.hasAttribute && el.hasAttribute("data-lib-ftmask")) { closeFulltextModal(); return; }
    var impMode = el.closest("[data-import-mode]");
    if (impMode) { switchImportMode(impMode.getAttribute("data-import-mode")); return; }
    var impSubmit = el.closest("[data-import-submit]");
    if (impSubmit) { submitImport(impSubmit); return; }
    if (el.hasAttribute && el.hasAttribute("data-lib-importmask")) { closeImportModal(); return; }
    /* 轮② P26：检索进度弹层手动关闭 */
    if (el.closest("[data-crawl-close]")) { closeCrawlProgress(); return; }
    var libTab = el.closest("[data-lib-tab]");
    if (libTab) {
      libraryState.tab = libTab.getAttribute("data-lib-tab");
      qsa("[data-lib-tab]").forEach(function (b) { b.classList.toggle("active", b === libTab); });
      renderLibraryList();
      if (libraryState.tab === "parsing") refreshParsingTab();
      else scheduleParsingPoll(0);
      return;
    }
    var libDelBtn = el.closest("[data-lib-del]");
    if (libDelBtn) {
      var delPid = parseInt(libDelBtn.getAttribute("data-lib-del"), 10);
      var delItem = null;
      libraryState.items.forEach(function (p) { if (p.id === delPid) delItem = p; });
      openLibDeleteConfirm(delPid, delItem ? delItem.title : "");
      return;
    }
    if (el.closest("[data-lib-delcancel]")) { closeLibDeleteConfirm(); return; }
    var libDelConfirm = el.closest("[data-lib-delconfirm]");
    if (libDelConfirm) {
      libConfirmDelete(parseInt(libDelConfirm.getAttribute("data-lib-delconfirm"), 10));
      return;
    }
    /* P29→P30：行尾「解析/重新解析」按钮 → collect-parse 发起并跳「解析中」tab */
    var libParse = el.closest("[data-lib-parse]");
    if (libParse) {
      var parsePid = parseInt(libParse.getAttribute("data-lib-parse"), 10);
      libParse.disabled = true;
      API.post("/papers/" + parsePid + "/collect-parse", {}).then(function (r) {
        toast("已发起解析：" + ((r && r.parse_status) === "done"
          ? "已完成，回到「全部」点行进入阅读"
          : "可在「解析中」看五段进度"));
        libraryState.tab = "parsing";
        loadLibrary().then(function () {
          qsa("[data-lib-tab]").forEach(function (b) {
            b.classList.toggle("active", b.getAttribute("data-lib-tab") === "parsing");
          });
          refreshParsingTab();
        });
      }).catch(function (e2) {
        libParse.disabled = false;
        loadLibrary();  // P30：409「请先获取或上传全文」等态刷新可见
        toast((e2 && e2.detail) || "发起解析失败");
      });
      return;
    }
    /* P30 独立动作一：行尾「获取全文/重试获取」→ fetch-fulltext（失败原因落库可见） */
    var libFetch = el.closest("[data-lib-fetch]");
    if (libFetch) {
      var fetchPid = parseInt(libFetch.getAttribute("data-lib-fetch"), 10);
      libFetch.disabled = true;
      API.post("/papers/" + fetchPid + "/fetch-fulltext", {}).then(function (r) {
        if (r && r.ok) {
          toast(r.already ? "全文已存在，无需重复获取" : "全文获取成功，可发起解析");
        } else {
          toast("获取全文失败：" + ((r && r.reason) || "未知原因"));
        }
        loadLibrary();
      }).catch(function (e2) {
        toast((e2 && e2.detail) || "获取全文失败");
        loadLibrary();
      });
      return;
    }
    /* P30 独立动作二：行尾「上传/替换文件」→ 统一文件选择弹窗 */
    var libUpload = el.closest("[data-lib-upload]");
    if (libUpload) {
      openFulltextModal(parseInt(libUpload.getAttribute("data-lib-upload"), 10));
      return;
    }
    /* P29：整页阅读视图「← 返回」→ 回列表并恢复滚动位置 */
    if (el.closest("[data-lib-back]")) { libBackToList(); return; }
    /* 我的文献：点列表项打开阅读视图（点在行尾动作钮/删除钮上时不触发） */
    var libOpen = el.closest("[data-lib-open]");
    if (libOpen && !el.closest(".lib-del") && !el.closest(".lib-act")) {
      var openPid = parseInt(libOpen.getAttribute("data-lib-open"), 10);
      var openItem = null;
      _libVisibleItems().forEach(function (p) { if (p.id === openPid) openItem = p; });
      if (openItem && openItem.parse_status !== "done") {
        toast("解析完成后才能阅读（行尾可发起解析）");
        return;
      }
      libOpenReader(openPid);
      return;
    }
    /* 我的文献：删除弹窗点遮罩空白处 = 取消 */
    if (el.hasAttribute && el.hasAttribute("data-lib-delmask")) { closeLibDeleteConfirm(); return; }
    /* 文献页：左导航切换（今日推送 / 我的收藏 / 全部论文） */
    var pNav = el.closest("[data-pp-nav]");
    if (pNav && !pNav.classList.contains("is-disabled")) {
      qsa("[data-pp-nav]").forEach(function (b) { b.classList.remove("active"); });
      pNav.classList.add("active");
      paperState.nav = pNav.getAttribute("data-pp-nav");
      loadPapersNav();
      return;
    }
    /* 文献页：立即检索（loading → crawl-now → 刷新 digest） */
    var pCrawl = el.closest("[data-pp-crawl]");
    if (pCrawl) { crawlNow(pCrawl); return; }
    /* 文献页：语义检索（P13：一句话 → AI 扩词 → 临时聚合抓取） */
    var pNl = el.closest("[data-pp-nlsearch]");
    if (pNl) { nlSearch(pNl); return; }
    /* 订阅弹窗/选择页：需 key/收费源「去 Key 管理配置」→ 关两层弹窗 → 平台管理·Key 管理页签
     * （preventDefault 阻止 label 内点击连带切换复选框） */
    var keyCfg = el.closest("[data-sub-keycfg]");
    if (keyCfg) {
      e.preventDefault();
      var pickDlg3 = qs("#modal-papers-src");
      if (pickDlg3 && pickDlg3.close) { if (pickDlg3.open) pickDlg3.close(); }
      var subDlg = qs("#modal-papers-sub");
      if (subDlg && subDlg.close) { if (subDlg.open) subDlg.close(); }
      else if (subDlg) subDlg.classList.remove("open");
      go("admin");
      afterRender(function () {
        var tab = qs('[data-admin-tab="#pane-keys"]');
        if (tab) tab.click();
      });
      return;
    }
    /* 文献页：订阅设置齿轮 → 中央弹窗（P5 拍板单入口） */
    if (el.closest("[data-pp-subscribe]")) { openSubscribeModal(); return; }
    /* 文献页：下载占位（下批开放） */
    if (el.closest("[data-pp-dl]")) { toast("全文下载下批开放"); return; }
    /* 文献页：关闭详情面板 */
    if (el.closest("[data-pp-close]")) { closePaperDetail(); return; }
    /* 文献页：点卡片展开右侧详情（点在操作行上时不展开） */
    var pCard = el.closest("[data-pp-card]");
    if (pCard && !el.closest(".pp-card-ops")) {
      openPaperDetail(parseInt(pCard.getAttribute("data-pp-card"), 10));
      return;
    }
    /* 文献页：收藏 toggle（P19：状态提升 savedMap，今日推送/我的收藏双列表即时同步） */
    var pSave = el.closest("[data-paper-save]");
    if (pSave) {
      var pid5 = parseInt(pSave.getAttribute("data-paper-save"), 10);
      API.post("/papers/" + pid5 + "/save", {}).then(function (r) {
        paperState.saved[pid5] = r.saved;  // 双列表共享态：切 nav 不重拉也一致
        paperState.items.forEach(function (it) { if (it.id === pid5) it.saved = r.saved; });
        /* 卡片操作行与详情面板内可能各有一个收藏按钮，同步刷新 */
        qsa('[data-paper-save="' + pid5 + '"]').forEach(function (b) {
          b.classList.toggle("is-on", r.saved);
          var lbl = b.childNodes[b.childNodes.length - 1];
          if (lbl && lbl.nodeType === 3) lbl.textContent = r.saved ? "已收藏" : "收藏";
        });
        /* 收藏列表里取消收藏 → 卡片即时移除（无需刷新）；其余列表原地更新状态 */
        if (paperState.nav === "favorites" && !r.saved) {
          paperState.items = paperState.items.filter(function (it) { return it.id !== pid5; });
          renderPaperCards();
        }
        toast(r.saved ? "已收藏" : "已取消收藏");
      }).catch(function (e) { toast(e.detail || "操作失败"); });
      return;
    }
    /* 文献页：生成 AI 解读（按钮在详情面板内） */
    var pExplain = el.closest("[data-paper-explain]");
    if (pExplain) {
      var pid6 = pExplain.getAttribute("data-paper-explain");
      pExplain.disabled = true;
      pExplain.innerHTML = '<span class="thinking" style="display:inline-flex;"><i></i><i></i><i></i></span> 生成中…';
      API.post("/papers/" + pid6 + "/explain", {}).then(function (r) {
        var body = qs("[data-explain-body]");
        if (body) { body.textContent = r.content; body.classList.remove("hide"); }
        pExplain.remove();
      }).catch(function (e) {
        pExplain.disabled = false;
        pExplain.innerHTML = '<i data-ic="spark"></i>生成 AI 解读';
        injectIcons(pExplain.parentElement);
        toast(e.detail || "解读生成失败");
      });
      return;
    }
    /* 轮② P28：解析入口收紧——详情面板不再触发解析（原「收藏并解析」按钮已移除，
     * 解析只在 #/library 内发起）；此处保留兜底：万一有旧 DOM 也引导去我的文献 */
    var pParse = el.closest("[data-pp-collectparse]");
    if (pParse) {
      toast("解析入口已收紧：请先到「我的文献」加入后，在库内发起解析");
      return;
    }
    /* 我的笔记：进入笔记 → 打开批注阅读器（P8 批注式笔记转正） */
    var pNoteEntry = el.closest("[data-pp-noteentry]");
    if (pNoteEntry) {
      openReader(parseInt(pNoteEntry.getAttribute("data-pp-noteentry"), 10));
      return;
    }
    /* ── P8 阅读器内交互（事件委托；阅读器在 body 直属层，#view 外）── */
    /* P29：库内挂载态下「关闭」= 返回列表（与「← 返回」同一语义）；遮罩态照旧关闭 */
    if (el.closest("[data-pp-rclose]")) {
      if (readerState.inline) libBackToList(); else closeReader();
      return;
    }
    if (el.closest("[data-pp-rexport]")) { exportReaderMd(); return; }
    /* 轮③ P27：翻译/重新翻译按钮（翻译中禁用，点击触发分批翻译） */
    if (el.closest("[data-pp-translate]")) { startTranslate(); return; }
    if (el.closest("[data-pp-railtoggle]")) {
      var rdBody = qs(".pp-reader-body");
      if (rdBody) rdBody.classList.toggle("showrail");
      return;
    }
    var selMark = el.closest("[data-pp-selmark]");
    if (selMark) { createAnnotationFromSel(""); return; }
    var selComment = el.closest("[data-pp-selcomment]");
    if (selComment) { selPopComposer(); return; }
    if (el.closest("[data-pp-selsave]")) {
      var ta = qs("[data-pp-seltext]");
      createAnnotationFromSel(ta ? ta.value.trim() : "");
      return;
    }
    if (el.closest("[data-pp-selcancel]")) { hideSelPop(); return; }
    var raEdit = el.closest("[data-pp-raedit]");
    if (raEdit) {
      readerState.editingId = parseInt(raEdit.getAttribute("data-pp-raedit"), 10);
      renderReaderRail();
      return;
    }
    var raCancel = el.closest("[data-pp-racancel]");
    if (raCancel) {
      readerState.editingId = null;
      renderReaderRail();
      return;
    }
    var raSave = el.closest("[data-pp-rasave]");
    if (raSave) {
      var aid4 = parseInt(raSave.getAttribute("data-pp-rasave"), 10);
      var ta4 = qs('[data-pp-ratext="' + aid4 + '"]');
      API.put("/papers/annotations/" + aid4, { body: ta4 ? ta4.value.trim() : "" }).then(function () {
        readerState.editingId = null;
        toast("已保存");
        reloadReaderAnns();
      }).catch(function (e) { toast((e && e.detail) || "保存失败"); });
      return;
    }
    var raDel = el.closest("[data-pp-radel]");
    if (raDel) {
      var aid5 = parseInt(raDel.getAttribute("data-pp-radel"), 10);
      API.del("/papers/annotations/" + aid5).then(function () {
        toast("批注已删除");
        reloadReaderAnns();
      }).catch(function (e) { toast((e && e.detail) || "删除失败"); });
      return;
    }
    var raLink = el.closest("[data-pp-ralink]");
    if (raLink) {
      openLinkPicker(parseInt(raLink.getAttribute("data-pp-ralink"), 10));
      return;
    }
    /* 互链选择器：选中目标 → PUT 出链（数组整体替换，后端保序去重） */
    var raPick = el.closest("[data-pp-ralinkpick]");
    if (raPick) {
      var pickParts = raPick.getAttribute("data-pp-ralinkpick").split("|");
      var fromId = parseInt(pickParts[0], 10);
      var toId = parseInt(pickParts[1], 10);
      var curLinks = [];
      (readerState.annotations || []).forEach(function (a) {
        if (a.id === fromId) curLinks = (a.links || []).slice();
      });
      if (curLinks.indexOf(toId) === -1) curLinks.push(toId);
      API.put("/papers/annotations/" + fromId, { links: curLinks }).then(function () {
        var dlgEl = raPick.closest("dialog");
        if (dlgEl && dlgEl.close) dlgEl.close();
        toast("已建立链接");
        reloadReaderAnns();
      }).catch(function (e) { toast((e && e.detail) || "建链失败"); });
      return;
    }
    var linkClose = el.closest("[data-pp-linkclose]");
    if (linkClose) {
      var dlgEl2 = linkClose.closest("dialog");
      if (dlgEl2 && dlgEl2.close) dlgEl2.close();
      return;
    }
    /* 点引用块 → 跳回原文段落（Zotero Show on Page） */
    var annJump = el.closest("[data-pp-annjump]");
    if (annJump) { flashBlock(annJump.getAttribute("data-pp-annjump")); return; }
    /* 点段落旗标 → 跳到该段第一条批注卡片 */
    var blockJump = el.closest("[data-pp-blockjump]");
    if (blockJump) {
      var bid = blockJump.getAttribute("data-pp-blockjump");
      var firstAnn = null;
      (readerState.annotations || []).forEach(function (a) {
        if (!firstAnn && a.anchor_block_id === bid) firstAnn = a;
      });
      if (firstAnn) flashCard(firstAnn.id);
      return;
    }
    /* 点出链 chip → 跳目标批注（同篇高亮 / 跨篇切阅读器） */
    var raJump = el.closest("[data-pp-rajump]");
    if (raJump) { jumpToAnnotation(parseInt(raJump.getAttribute("data-pp-rajump"), 10)); return; }
    /* 应用中心：打开应用 */
    var appRow = el.closest("[data-app-open]");
    if (appRow) {
      var appId = appRow.getAttribute("data-app-open");
      go(appId === "money" ? "money" : appId);
      return;
    }
    /* 管理页标签 */
    var tab = el.closest("[data-admin-tab]");
    if (tab) {
      qsa("[data-admin-tab]").forEach(function (t) { t.classList.remove("active"); });
      qsa(".admin-pane").forEach(function (pn) { pn.classList.remove("active"); });
      tab.classList.add("active");
      var pane = qs(tab.getAttribute("data-admin-tab"));
      if (pane) pane.classList.add("active");
      return;
    }
    /* 步 3 · 模型指派：模型链编辑（状态存 DOM，全局「保存全部」时按行收集） */
    var asgRow = el.closest("[data-asg-row]");
    if (asgRow) {
      var appKey = asgRow.getAttribute("data-asg-row");
      var chainBox = qs('[data-asg-chain="' + appKey + '"]', asgRow);
      var delChip = el.closest("[data-chain-del]");
      if (delChip && chainBox) {
        var chipEl = delChip.closest("[data-chain-item]");
        if (chipEl) {
          chainBox.removeChild(chipEl);
          chainReindex(chainBox);
          refreshAsgSaveBtn();
        }
        return;
      }
      if (el.closest("[data-asg-add]")) { asgOpenAddPop(el.closest("[data-asg-add]"), appKey); return; }
      if (el.closest("[data-asg-toggle]")) {
        var sw2 = el.closest("[data-asg-toggle]");
        sw2.classList.toggle("on");
        sw2.setAttribute("aria-checked", sw2.classList.contains("on") ? "true" : "false");
        refreshAsgSaveBtn();
        return;
      }
    }
    if (el.closest("[data-asg-save-all]")) { saveAllAssignments(); return; }
    if (el.closest("[data-asg-reload]")) {
      loadAssignments();
      return;
    }
    if (el.closest("[data-cb-reset]")) {
      var cbMid = el.closest("[data-cb-reset]").getAttribute("data-cb-reset");
      API.post("/admin/models/circuit-states/" + cbMid + "/reset").then(function () {
        toast("已恢复，路由立即重新采纳该模型");
        loadAssignments();
      }).catch(function (e2) { toast(e2.detail || "恢复失败"); });
      return;
    }
    /* 步 3 · 用量统计：时间筛选与分页 */
    if (el.closest("[data-usage-query]")) {
      adminState.usage.start = (qs("[data-usage-start]") || {}).value || "";
      adminState.usage.end = (qs("[data-usage-end]") || {}).value || "";
      loadUsage(1);
      return;
    }
    var upg = el.closest("[data-usage-page]");
    if (upg) {
      var delta = upg.getAttribute("data-usage-page") === "next" ? 1 : -1;
      var pages2 = adminState.usage.logs
        ? Math.max(1, Math.ceil(adminState.usage.logs.total / adminState.usage.logs.page_size)) : 1;
      var next2 = Math.min(pages2, Math.max(1, adminState.usage.page + delta));
      if (next2 !== adminState.usage.page) loadUsage(next2);
      return;
    }
    /* 服务 Key：新增 / 编辑 / 删除 / 启用开关 / 弹窗保存 */
    if (el.closest("[data-sk-add]")) { openSkeyModal(null); return; }
    var skEdit = el.closest("[data-sk-edit]");
    if (skEdit) {
      var skRow = null;
      adminState.serviceKeys.forEach(function (x) { if (String(x.id) === String(skEdit.getAttribute("data-sk-edit"))) skRow = x; });
      if (skRow) openSkeyModal(skRow); else toast("该行已不存在，请刷新");
      return;
    }
    var skDel = el.closest("[data-sk-del]");
    if (skDel) {
      var skDelId = skDel.getAttribute("data-sk-del");
      var skDelRow = null;
      adminState.serviceKeys.forEach(function (x) { if (String(x.id) === String(skDelId)) skDelRow = x; });
      if (!window.confirm("删除服务「" + (skDelRow ? skDelRow.service_key : skDelId) + "」的钥匙？删除后该服务将无法取到钥匙。")) return;
      API.del("/admin/service-keys/" + skDelId).then(function () {
        toast("钥匙已删除");
        loadServiceKeys();
      }).catch(function (e) { toast(e.detail || "删除失败"); });
      return;
    }
    var skToggle = el.closest("[data-sk-toggle]");
    if (skToggle) {
      var skTid = skToggle.getAttribute("data-sk-toggle");
      var skTRow = null;
      adminState.serviceKeys.forEach(function (x) { if (String(x.id) === String(skTid)) skTRow = x; });
      if (!skTRow) return;
      API.put("/admin/service-keys/" + skTid, { enabled: !skTRow.enabled }).then(function () {
        toast(skTRow.enabled ? "已停用" : "已启用");
        loadServiceKeys();
      }).catch(function (e) { toast(e.detail || "操作失败"); });
      return;
    }
    if (el.closest("[data-sk-save]")) { saveSkey(); return; }
    /* 会话：删除（真删，级联消息） */
    if (el.closest("[data-conv-del]")) {
      var delItem = el.closest(".conv-item");
      var delId = delItem ? parseInt(delItem.getAttribute("data-cid"), 10) : null;
      if (delId) {
        API.del("/chat/conversations/" + delId + "?app_id=chat").then(function () {
          toast("会话已删除");
          if (chatState.convId === delId) {
            chatState.convId = null;
            chatState.newConv = true; /* 删除当前会话后进入空态，禁止列表刷新时自动选中首个 */
            var innerEl = qs("[data-chat-inner]");
            if (innerEl) innerEl.innerHTML = '<div class="chat-empty muted" data-chat-empty>开始一段新对话吧</div>';
            var tEl = qs("[data-chat-title]");
            if (tEl) tEl.textContent = "通用对话";
          }
          refreshConversations(true);
        }).catch(function (ex) { toast(ex.detail || "删除失败"); });
      }
      return;
    }
    /* 会话：切换（加载历史） */
    var convItem = el.closest(".conv-item");
    if (convItem) {
      var cid = parseInt(convItem.getAttribute("data-cid"), 10);
      if (cid) selectConversation(cid, convItem.querySelector(".ct").textContent);
      var cp = qs(".conv-panel"), cm = qs("[data-conv-mask]");
      if (cp) cp.classList.remove("open");
      if (cm) cm.classList.remove("open");
      return;
    }
    /* 新建会话（本地状态；首条消息发送后由后端建会话） */
    if (el.closest("[data-new-conv]")) {
      chatState.convId = null;
      chatState.newConv = true; /* 标记主动空态：后续列表刷新不得自动选中首个会话 */
      qsa(".conv-item").forEach(function (i) { i.classList.remove("active"); });
      var inner2 = qs("[data-chat-inner]");
      if (inner2) inner2.innerHTML = '<div class="chat-empty muted" data-chat-empty>开始一段新对话吧</div>';
      var tEl2 = qs("[data-chat-title]");
      if (tEl2) tEl2.textContent = "通用对话";
      var cp2 = qs(".conv-panel"), cm2 = qs("[data-conv-mask]");
      if (cp2) cp2.classList.remove("open");
      if (cm2) cm2.classList.remove("open");
      toast("已新建会话");
      return;
    }
    /* 发送 */
    if (el.closest("[data-send]")) { sendMessage(); return; }
  });

  /* 输入事件委托：金额预览 / 应用搜索 */
  document.addEventListener("input", function (e) {
    /* 数据源选择页：搜索框按名称过滤（即时重渲染，搜索时分组强制展开） */
    var pickQ = e.target.closest ? e.target.closest("[data-src-pick-q]") : null;
    if (pickQ) {
      srcPickState.query = pickQ.value;
      renderSrcPicker();
      return;
    }
    var amt = e.target.closest ? e.target.closest("[data-amount-input]") : null;
    if (amt) {
      var out = qs(amt.getAttribute("data-amount-input"));
      var v = Math.round(parseFloat(amt.value || "0") * 100);
      if (out) out.textContent = isNaN(v) ? "¥0.00" : fen(v);
      return;
    }
    var search = e.target.closest ? e.target.closest("[data-app-search]") : null;
    if (search) {
      var q = search.value.trim().toLowerCase();
      qsa(".app-row").forEach(function (row) {
        row.classList.toggle("hide", !!(q && row.textContent.toLowerCase().indexOf(q) === -1));
      });
      qsa(".app-group").forEach(function (g) {
        var any = qsa(".app-row", g).some(function (r) { return !r.classList.contains("hide"); });
        g.classList.toggle("hide", !any);
      });
      var empty = qs("[data-app-empty]");
      if (empty) empty.classList.toggle("hide", qsa(".app-row:not(.hide)").length !== 0);
    }
  });

  /* 键盘：⌘K / Ctrl+K 面板，Esc 关闭，Enter 发送 */
  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      paletteOpen ? closePalette() : openPalette();
      return;
    }
    /* role="button" 的 div 块：Enter/空格触发点击（原生 button 之外的键盘可达性补齐） */
    if ((e.key === "Enter" || e.key === " ") && !e.isComposing && !imeComposing &&
        e.target.matches && e.target.matches('[role="button"]')) {
      e.preventDefault();
      e.target.click();
      return;
    }
    /* 通用自定义下拉 xselect：↑↓ 移动高亮（未开则打开）、Enter 确认、Esc 关闭（对齐原生 select 键盘语义） */
    var xsRoot = e.target.closest ? e.target.closest("[data-xselect]") : null;
    if (xsRoot && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === "Escape")) {
      var xsPop = qs("[data-xselect-pop]", xsRoot);
      var xsOpen = xsPop && !xsPop.classList.contains("hide");
      if (e.key === "Escape") {
        if (xsOpen) { e.preventDefault(); xselectClosePop(xsRoot); }
      } else if (e.key === "Enter") {
        /* IME 选词回车不算确认；收起态不拦截，交给 button 原生 click 打开 */
        if (xsOpen && !e.isComposing && !imeComposing) {
          e.preventDefault();
          var xsAct = qs(".xselect-opt.active", xsPop);
          if (xsAct) xselectPick(xsRoot, xsAct);
        }
      } else {
        e.preventDefault();
        if (!xsOpen) xselectOpenPop(xsRoot);
        else xselectMove(xsRoot, e.key === "ArrowDown" ? 1 : -1);
      }
      return;
    }
    if (paletteOpen) {
      if (e.key === "Escape") { closePalette(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); paletteIndex = Math.min(paletteIndex + 1, paletteFiltered.length - 1); renderPaletteList(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); paletteIndex = Math.max(paletteIndex - 1, 0); renderPaletteList(); return; }
      if (e.key === "Enter") {
        /* IME 选词回车不算确认（isComposing + composition 事件双保险） */
        if (e.isComposing || imeComposing) return;
        e.preventDefault();
        paletteExec(paletteIndex);
        return;
      }
      return;
    }
    if (e.key === "Escape") {
      /* 原生 <dialog> 的 Esc 由浏览器自行处理（cancel → close），这里兜底非 dialog 弹层 */
      if (readerState.open && !readerState.inline) { closeReader(); return; } /* P8：先收批注阅读器（挂载态不收：中栏是页面主体） */
      qsa("dialog.modal-mask[open]").forEach(function (m) { m.close(); });
      qsa(".udrawer:not(.hide), .ud-mask:not(.hide)").forEach(function (m) { m.classList.add("hide"); });
      rolePopCloseAll();
      qsa(".xselect-pop:not(.hide)").forEach(function (p) { xselectClosePop(p.closest("[data-xselect]")); });
      closeDrawers();
      return;
    }
    /* 润色撤销：Ctrl+Z / Cmd+Z 恢复原文（P0-3 ③，可撤销一次） */
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z" &&
        e.target.matches && e.target.matches(".composer textarea") && polishBackup) {
      e.preventDefault();
      var ta2 = e.target;
      ta2.value = polishBackup.text;
      try { ta2.selectionStart = ta2.selectionEnd = polishBackup.sel; } catch (err) {}
      polishBackup = null;
      autoGrowComposer(ta2);
      syncPolishBtn();
      return;
    }
    /* 订阅设置弹窗：关键词输入框回车 = 添加标签（IME 选词回车不算） */
    if (e.key === "Enter" && e.target.matches && e.target.matches("[data-sub-kw-input]")) {
      if (e.isComposing || imeComposing) return;
      e.preventDefault();
      var v = e.target.value.trim();
      if (!v) return;
      if (subState.keywords.indexOf(v) !== -1) { toast("关键词已在列表中"); e.target.value = ""; return; }
      subState.keywords.push(v);
      renderSubKeywords();
      renderSubAiPicked();
      subRefreshSaveBtn();
      var ni = qs("[data-sub-kw-input]");
      if (ni) ni.focus();
      return;
    }
    if (e.key === "Enter" && e.target.matches && e.target.matches(".composer textarea") && !e.shiftKey) {
      /* IME 选词回车不发送（isComposing + composition 事件双保险，拼音用户必踩） */
      if (e.isComposing || imeComposing) return;
      e.preventDefault();
      sendMessage();
    }
  });
  qs("#palette-input").addEventListener("input", function (e) { filterPalette(e.target.value); });

  /* 头像设置：上传文件（change 事件委托） */
  document.addEventListener("change", function (e) {
    var f = e.target.closest ? e.target.closest("[data-avatar-file]") : null;
    if (!f) return;
    handleAvatarFile(f);
    f.value = ""; /* 清空，允许再次选择同一文件 */
  });

  /* 我的技能：上传 SKILL.md（change 事件委托，input.value 在 handleSkillFile 内清空） */
  document.addEventListener("change", function (e) {
    var f = e.target.closest ? e.target.closest("[data-skill-file]") : null;
    if (!f) return;
    handleSkillFile(f);
  });

  /* 订阅设置弹窗：数据源选择页（第二层弹窗）勾选 → 改草稿并刷新计数 */
  document.addEventListener("change", function (e) {
    var c = e.target.closest ? e.target.closest("[data-src-pick]") : null;
    if (c) {
      var key = c.getAttribute("data-src-pick");
      var idx = srcPickState.draft.indexOf(key);
      if (c.checked && idx === -1) srcPickState.draft.push(key);
      if (!c.checked && idx !== -1) srcPickState.draft.splice(idx, 1);
      renderSrcPicker();
      return;
    }
    /* P21 检索条件（订阅弹窗）：年份起/止、作者、IF 下限 → 脏状态亮起保存按钮 */
    var t = e.target;
    function _p21Num(sel, attr, minOk) {
      var el2 = t.closest ? t.closest(sel) : null;
      if (!el2) return false;
      var v = parseFloat(el2.value);
      subState.p21[attr] = (el2.value === "" || isNaN(v) || !minOk(v)) ? null : v;
      subRefreshSaveBtn();
      return true;
    }
    if (_p21Num("[data-sub-yfrom]", "year_from", function (v) { return v >= 1500 && v <= 2100; })) return;
    if (_p21Num("[data-sub-yto]", "year_to", function (v) { return v >= 1500 && v <= 2100; })) return;
    if (_p21Num("[data-sub-ifmin]", "if_min", function (v) { return v >= 0; })) return;
    var au = t.closest ? t.closest("[data-sub-authors]") : null;
    if (au) {
      subState.p21.authors = au.value.split(/[,，]/).map(function (a) { return a.trim(); }).filter(Boolean);
      subRefreshSaveBtn();
    }
  });

  /* 文献页展示设置（P18）：排序 xselect / IF 下限 / 展示条数——改动即时生效并保存偏好 */
  document.addEventListener("xselect:change", function (e) {
    var root = e.target.closest ? e.target.closest("[data-pp-sort]") : null;
    if (!root || !e.detail) return;
    paperState.prefs.sort = e.detail.value;
    savePapersPrefs();
    loadPapersNav();
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.closest && t.closest("[data-pp-ifmin]")) {
      var v = parseFloat(t.value);
      paperState.prefs.if_min = (t.value === "" || isNaN(v) || v < 0) ? null : v;
      savePapersPrefs();
      loadPapersNav();
      return;
    }
    if (t.closest && t.closest("[data-pp-limit]")) {
      var n = parseInt(t.value, 10);
      if (!isNaN(n) && n >= 1) {
        paperState.prefs.display_limit = Math.min(n, 500);
        savePapersPrefs();
        loadPapersNav();
      }
    }
  });

  /* 对话发送：POST /chat SSE 双流渲染（reasoning_delta → 思维面板「思考中…」计时态；
   * delta → 正文；done → 面板定型可展开；error 语义不变） */
  function sendMessage() {
    var composer = qs(".composer textarea");
    var inner = qs("[data-chat-inner]");
    if (!composer || !inner || chatState.sending) return;
    var text = composer.value.trim();
    if (!text) return;
    var emptyEl = qs("[data-chat-empty]");
    if (emptyEl) emptyEl.remove();
    var userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.innerHTML = '<span class="avatar">' + avatarInnerHtml() + '</span><div class="msg-body"><div class="msg-text"><p></p></div></div>';
    userMsg.querySelector("p").textContent = text;
    inner.appendChild(userMsg);
    composer.value = "";
    autoGrowComposer(composer);
    syncPolishBtn();

    var reply = document.createElement("div");
    reply.className = "msg ai cursor";
    /* 思维面板：流式期间仅「思考中…」+计时（P0-1 ②，不逐字渲染思维，降感知延迟） */
    reply.innerHTML = '<span class="avatar"><i data-ic="bot"></i></span><div class="msg-body">' +
      '<div class="think-box thinking" data-think-box data-think-last>' +
        '<div class="think-head" data-think-toggle role="button" tabindex="0">' +
        '<i data-ic="spark"></i><span class="think-title">思考中…</span>' +
        '<i data-ic="down" class="think-caret"></i></div>' +
        '<div class="think-body hide"><p></p></div></div>' +
      '<div class="msg-text"><span class="think-dots"><i></i><i></i><i></i></span><span class="stream-text"></span></div></div>';
    injectIcons(reply);
    inner.appendChild(reply);
    var node = reply.querySelector(".stream-text");
    var thinkBox = reply.querySelector("[data-think-box]");
    var thinkTitle = thinkBox ? thinkBox.querySelector(".think-title") : null;
    var thinkBodyP = thinkBox ? thinkBox.querySelector(".think-body p") : null;
    var sc = qs(".chat-scroll");
    function scrollBottom() { if (sc) sc.scrollTop = sc.scrollHeight; }
    scrollBottom();

    /* 思维计时：从请求发起算，完成/失败后定格 */
    var t0 = Date.now();
    var thinkTimer = setInterval(function () {
      if (thinkTitle && thinkBox && thinkBox.classList.contains("thinking")) {
        thinkTitle.textContent = "思考中…（" + ((Date.now() - t0) / 1000).toFixed(0) + "s）";
      }
    }, 200);
    var reasoningBuf = "";
    var thinkFinalized = false;
    function finalizeThink() {
      /* 思维流定型：无思维流 → 移除面板（P0-4 ② 前端自然隐藏）；有 → 默认折叠可展开 */
      if (thinkFinalized) return;
      thinkFinalized = true;
      clearInterval(thinkTimer);
      if (!thinkBox) return;
      thinkBox.classList.remove("thinking");
      if (!reasoningBuf) { thinkBox.remove(); thinkBox = null; return; }
      var secs = ((Date.now() - t0) / 1000).toFixed(0);
      if (thinkTitle) thinkTitle.textContent = "已深度思考（耗时 " + secs + "s）";
      if (thinkBodyP) thinkBodyP.textContent = reasoningBuf;
      if (thinkOpenPref()) thinkBox.classList.add("open");
      var body = thinkBox.querySelector(".think-body");
      if (body) body.classList.toggle("hide", !thinkOpenPref());
    }

    /* 实际发送：组装请求体（conversation_id 由调用方保证已挂上）并消费 SSE 流 */
    function dispatchSend() {
      var body = { app_id: "chat", message: text };
      if (chatState.convId) body.conversation_id = chatState.convId;
      if (chatState.modelId) body.model_id = chatState.modelId;
      /* P0-2 ⑤：选择绑定会话快照（默认档在切模型时已回填）；不传 = 厂商默认 */
      if (chatState.thinkingLevel) body.thinking_level = chatState.thinkingLevel;
      chatState.sending = true;

      API.stream("/chat", body, function (ev) {
        var dots = reply.querySelector(".think-dots");
        if (ev.done) {
          if (dots) dots.remove();
          finalizeThink();
          reply.classList.remove("cursor");
          chatState.sending = false;
          refreshConversations(true);
          return;
        }
        if (dots) dots.remove();
        if (ev.reasoning_delta) {
          /* 流式期间只累计 + 保持计时态，不逐字渲染 */
          reasoningBuf += ev.reasoning_delta;
          return;
        }
        finalizeThink();
        if (ev.delta) { node.textContent += ev.delta; scrollBottom(); }
        if (ev.error) {
          node.textContent += (node.textContent ? "\n" : "") + "⚠️ " + ev.error;
          reply.classList.remove("cursor");
          chatState.sending = false;
          scrollBottom();
        }
      }).catch(function (ex) {
        var dots2 = reply.querySelector(".think-dots");
        if (dots2) dots2.remove();
        finalizeThink();
        node.textContent = "发送失败：" + (ex && ex.detail ? ex.detail : "网络错误");
        reply.classList.remove("cursor");
        chatState.sending = false;
        scrollBottom();
      });
    }

    if (chatState.convId) {
      dispatchSend();
    } else {
      /* 新建会话首条消息：先显式建会话、挂上 id 再发送。后端在缺省 conversation_id 时
         会「复用最近更新的会话」，不先建会话消息会串进旧会话（本次 bug 根因之一） */
      API.post("/chat/conversations", { app_id: "chat", title: text.slice(0, 16) }).then(function (c) {
        if (!c || !c.id) throw { detail: "创建会话失败" };
        chatState.convId = c.id;
        chatState.newConv = false;
        var tEl = qs("[data-chat-title]");
        if (tEl) tEl.textContent = c.title || "通用对话";
        qsa(".conv-item").forEach(function (i) {
          i.classList.toggle("active", parseInt(i.getAttribute("data-cid"), 10) === c.id);
        });
        dispatchSend();
      }).catch(function (ex) {
        finalizeThink();
        node.textContent = "发送失败：" + (ex && ex.detail ? ex.detail : "网络错误");
        reply.classList.remove("cursor");
        scrollBottom();
      });
    }
  }

  /* P8 阅读器选中：mouseup 后 selection 落定再弹「划线/批注」；
   * 弹层内点按钮时 mousedown 阻止默认（保正文选中态），textarea 不拦（要聚焦输入） */
  document.addEventListener("mousedown", function (e) {
    var selPop = qs("[data-pp-selpop]");
    if (selPop && !selPop.classList.contains("hide") && selPop.contains(e.target) &&
        e.target.closest && e.target.closest("button")) {
      e.preventDefault();
    }
  }, true);
  document.addEventListener("mouseup", function () {
    if (!readerState.open) return;
    setTimeout(updateSelPop, 0);
  });

  /* 会话面板输入框自适应（委托 input 已覆盖文本域，此处针对 composer 高度 + 润色按钮态） */
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches(".composer textarea")) {
      e.target.style.height = "auto";
      e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
      syncPolishBtn();
      return;
    }
    /* 我的技能搜索（即时过滤已安装列表，本地缓存匹配） */
    if (e.target.matches && e.target.matches("[data-skill-search]")) {
      skillFilterQ = e.target.value.trim();
      renderMySkills();
      return;
    }
    /* 管理端档位子表单：value 变化 → 刷新默认档下拉候选 */
    if (e.target.matches && e.target.matches("[data-lv-value]")) {
      refreshMmDefaultOptions();
    }
  });

  /* ================= 启动 ================= */
  function applyUserChrome() {
    if (!LC_USER) return;
    applyUserAvatar();
    var siderUser = qs(".sider-user");
    if (siderUser) {
      var name = siderUser.querySelector(".u-name");
      if (name) name.textContent = LC_USER.username;
      var role = siderUser.querySelector(".u-role");
      if (role) role.textContent = (LC_USER.roles || []).indexOf("admin") !== -1 ? "管理员" : "成员";
    }
  }

  renderSider();
  injectIcons(document);
  /* 已有 token 先校验（401 自动跳登录），再渲染首屏 */
  if (isLoggedIn()) {
    API.get("/auth/me").then(function (u) {
      LC_USER = u;
      loadThemeFromSettings(u.settings); /* 主题权威值在 user_settings（默认跟随系统） */
      applyUserChrome();
      render();
    }).catch(function () { render(); });
  } else {
    render();
  }
})();
