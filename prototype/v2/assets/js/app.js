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
    wand: '<path d="m15 4 5 5L7 22l-5-5z"/><path d="M14 3.5 16.5 6M19 8.5 21.5 11M5 3v3M3.5 4.5h3M20 15v3M18.5 16.5h3"/>'
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
    var t = qs("#toast");
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2200);
  }

  /* ================= 用户头像（localStorage: lc_avatar） =================
   * 形状约定：{"type":"img","data":"<dataURL>"} 或 {"type":"initial","color":"<hex>"}；
   * 未设置 / 解析失败 → 回退用户名首字 + 灰底（AGENTS.md：用户头像锚定身份、允许自定义） */
  var AVATAR_FALLBACK_BG = "#eef0f3";
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
  /* 头像内层：img 填充，或色底白字首字（未设置时灰底深字回退） */
  function avatarInnerHtml() {
    var s = avatarSetting();
    if (s && s.type === "img") return '<img class="avatar-img" src="' + esc(s.data) + '" alt="">';
    var color = (s && s.type === "initial" && s.color) ? s.color : AVATAR_FALLBACK_BG;
    var fg = color === AVATAR_FALLBACK_BG ? "var(--ink-2)" : "#ffffff";
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
  var ROUTES = ["workspace", "chat", "money", "papers", "apps", "admin", "me", "login"];
  var NAV = [
    { group: "主面板", items: [
      { route: "workspace", icon: "home", label: "工作台" },
      { route: "chat", icon: "chat", label: "对话" },
      { route: "money", icon: "money", label: "记账" },
      { route: "papers", icon: "book", label: "文献" }
    ] },
    { group: "系统", items: [
      { route: "apps", icon: "grid", label: "应用中心" },
      { route: "admin", icon: "gear", label: "平台管理" },
      { route: "me", icon: "user", label: "我的" }
    ] }
  ];
  var TITLES = { workspace: "工作台", chat: "AI 对话", money: "记账本", papers: "文献", apps: "应用中心", admin: "平台管理", me: "我的", login: "登录" };

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
  var chatState = { convId: null, modelId: null, thinkingLevel: null, sending: false };
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
    var swEl = qs("[data-mm-reasoning-enabled]");
    var box = qs("[data-mm-reasoning-box]");
    var enabled = !!(r && r.enabled);
    if (swEl) swEl.classList.toggle("on", enabled);
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
    var meta = {
      context: (qs("[data-mm-context]") || {}).value || "",
      vision: !!(qs("[data-mm-vision]") || {}).checked,
      files: !!(qs("[data-mm-files]") || {}).checked,
      reasoning: { enabled: enabled, levels: levels, default_level: defaultLevel },
      tools: !!(qs("[data-mm-tools]") || {}).checked,
      custom_protocol: !!(qs("[data-mm-custom]") || {}).checked
    };
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
    pvDetail: null, defaultRoute: null, addRowOpen: false
  };

  /* 提供商详情面板（管理页右侧，选中切换时局部重绘） */
  function modelRowHtml(m) {
    var meta = m.meta || {};
    return '<div class="mm-model" data-mid="' + m.id + '">' +
      '<button class="switch' + (m.enabled ? " on" : "") + '" type="button" data-model-enable="' + m.id + '" aria-label="启用该模型"></button>' +
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
        '<button class="switch' + (p.enabled ? " on" : "") + '" type="button" data-provider-toggle="' + p.id + '" aria-label="启用该提供商"></button></div>' +
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
    return '<button class="switch' + (on ? " on" : "") + '" type="button" data-perm-switch="' + code + '" aria-label="' + esc(label) + '"></button>';
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
  }

  var PAGES = {
    /* ---------- 每日看板 v2（2026-10-24 改版）：信息优先，卡片即跳板 ----------
     * 定位：按应用划分信息板块（板块注册表）；每板块只放「每天值得一眼的信息」（信息纪律）；
     * 整卡 <a> 即跳板，卡头右侧「应用名 →」；保留 grip 拖拽排序 lc_home_order（排序纪律）。
     * 结构：轻问候行（日期 + 时段问候 + 昵称，无全局指标带）+ bento 板块卡片区。
     * 桌面：论文 span-8 + 对话 span-4 第一行，记账 span-12 横条第二行；≤900px 单列堆叠（main.css）。 */
    workspace: function () {
      var skelLines = '<div class="ws-skel"><i></i><i></i><i></i></div>';
      var cards = [
        /* 论文板块（大卡 · 新闻流式「今日推送」）：本期 mock，点标题/整卡 → #/papers */
        '<a class="bcard span-8" href="#/papers" draggable="true" data-bcard="papers">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;"><i data-ic="book"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">今日推送</span></div>' +
          '<span class="bcard-app">文献<i data-ic="arrow"></i></span></div>' +
          '<div class="bcard-body" data-ws-papers>' + skelLines + "</div>" +
        "</a>",
        /* 对话板块（小卡）：昨日对话数（大数字）+ 最近一条会话摘要 */
        '<a class="bcard span-4" href="#/chat" draggable="true" data-bcard="chat">' +
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
        "</a>"
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

    /* ---------- 文献（PRD §4.8；PubMed 行式列表 + 点击行详情抽屉，参考 PubMed/RIMICIA pdigest） ---------- */
    papers: function () {
      var tagChips = ["全部", "AD", "PD", "ALS", "scale"].map(function (t, i) {
        return '<button class="chip' + (i === 0 ? " active" : "") + '" type="button" data-ptag="' + t + '">' + t + "</button>";
      }).join("");
      return '' +
        '<div class="page-head"><div><h1 class="page-title">文献</h1>' +
        '<div class="page-desc">PubMed 每日新文献 · AI 中译与解读</div></div></div>' +
        '<div class="seg" data-papers-seg style="max-width:260px;margin-bottom:14px;">' +
          '<button class="active" type="button" style="flex:1;">每日推送</button>' +
          '<button type="button" style="flex:1;">我的收藏</button>' +
        "</div>" +
        '<div class="chips" data-paper-tags style="margin-bottom:14px;">' + tagChips + "</div>" +
        '<div class="card" data-paper-list><div class="muted" style="padding:14px;">加载中…</div></div>' +
        /* 详情抽屉（题录 + 摘要/中译 + AI 解读 + 笔记） */
        '<div class="ud-mask hide" data-pp-mask></div>' +
        '<aside class="udrawer hide" data-pp-drawer></aside>';
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
      if (!keepCurrent || !chatState.convId) {
        var first = (convs || [])[0];
        if (first) selectConversation(first.id, first.title);
      }
    }).catch(function () {});
  }
  function selectConversation(id, title) {
    chatState.convId = id;
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
          : '<button class="switch' + (s.enabled ? " on" : "") + '" type="button" data-myskill-toggle="' + s.id + '" data-enabled="' + (s.enabled ? "1" : "0") + '" aria-label="启用该技能"></button>' +
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

  /* ================= 文献页活数据（/papers 联调） ================= */
  var paperState = { mode: "daily", tag: null, items: [] };

  function _paperAuthors(authors) {
    if (!authors || !authors.length) return "";
    var s = authors.slice(0, 3).join(", ");
    return authors.length > 3 ? s + " 等" : s;
  }
  function renderPaperRows(items) {
    paperState.items = items || [];
    var box = qs("[data-paper-list]");
    if (!box) return;
    box.innerHTML = paperState.items.length ? paperState.items.map(function (p) {
      var tags = (p.tags || []).map(function (t) {
        return '<span class="pill">' + esc(t) + "</span>";
      }).join("");
      if (p.abstract_zh) tags += '<span class="pill pill-ok">中译</span>';
      return '<div class="pp-row" data-paper="' + p.id + '" role="button" tabindex="0">' +
        '<div class="grow" style="min-width:0;">' +
          '<div class="pp-title">' + esc(p.title) + "</div>" +
          '<div class="pp-meta">' + esc(_paperAuthors(p.authors)) + (p.journal ? " · " + esc(p.journal) : "") +
            (p.pub_date ? " · " + esc(String(p.pub_date).slice(0, 4)) : "") + "</div>" +
          (tags ? '<div class="pp-tags">' + tags + "</div>" : "") +
        "</div>" +
        '<button class="btn btn-ghost btn-sm pp-save' + (p.saved ? " is-on" : "") + '" type="button" data-paper-save="' + p.id + '">' +
          (p.saved ? "已收藏" : "收藏") + "</button>" +
      "</div>";
    }).join("") : '<div class="muted" style="padding:16px 14px;font-size:13px;">' +
      (paperState.mode === "favorites" ? "还没有收藏文献" : "今日暂无推送：请在「我的 → 应用设置」配置订阅关键词，等待每日抓取") + "</div>";
  }
  function loadPapersList() {
    var path = paperState.mode === "favorites" ? "/papers/favorites" : "/papers/daily?limit=100";
    if (paperState.mode === "daily" && paperState.tag) path += "&tag=" + encodeURIComponent(paperState.tag);
    API.get(path).then(renderPaperRows).catch(function (e) { toast(e.detail || "文献加载失败"); });
  }
  function paperDrawerHtml(p) {
    var tags = (p.tags || []).map(function (t) { return '<span class="pill">' + esc(t) + "</span>"; }).join(" ");
    var explainBlock = p.explanation
      ? '<div class="ud-sec">AI 解读 <span class="muted" style="font-weight:400;font-size:12px;">（' + esc(p.explanation_model || "") + "）</span></div>" +
        '<div class="pp-abstract" data-explain-body>' + esc(p.explanation) + "</div>"
      : '<button class="btn btn-ghost btn-sm" type="button" data-paper-explain="' + p.id + '"><i data-ic="spark"></i>生成 AI 解读</button>' +
        '<div class="pp-abstract hide" data-explain-body></div>';
    return '' +
      '<div class="ud-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;flex:none;"><i data-ic="book"></i></span>' +
      '<div style="flex:1;min-width:0;"><div class="ud-name" style="white-space:normal;line-height:1.4;">' + esc(p.title) + "</div>" +
      '<div class="ud-sub">PMID ' + esc(p.pmid) + " · " + esc(p.journal || "—") + (p.pub_date ? " · " + esc(String(p.pub_date)) : "") + "</div></div>" +
      '<button class="icon-btn" type="button" data-pp-close aria-label="关闭"><i data-ic="close"></i></button></div>' +
      '<div class="ud-body">' +
        (tags ? '<div style="margin-bottom:10px;">' + tags + "</div>" : "") +
        '<div class="ud-sec">摘要</div>' +
        '<div class="pp-abstract">' + esc(p.abstract || "（无摘要）") + "</div>" +
        (p.abstract_zh
          ? '<div class="ud-sec">中文摘要</div><div class="pp-abstract">' + esc(p.abstract_zh) + "</div>"
          : "") +
        '<div class="ud-sec">AI 解读</div>' + explainBlock +
        '<div class="ud-sec">我的笔记</div>' +
        '<textarea class="pp-note" data-note-content rows="3" placeholder="记录你的想法，每人每篇一条">' + esc(p.note || "") + "</textarea>" +
        '<div style="margin-top:8px;text-align:right;"><button class="btn btn-ghost btn-sm" type="button" data-note-save="' + p.id + '">保存笔记</button></div>' +
      "</div>";
  }
  function openPaperDrawer(pid) {
    API.get("/papers/" + pid).then(function (p) {
      var dr = qs("[data-pp-drawer]"), mk = qs("[data-pp-mask]");
      if (dr) { dr.innerHTML = paperDrawerHtml(p); injectIcons(dr); dr.classList.remove("hide"); }
      if (mk) mk.classList.remove("hide");
    }).catch(function (e) { toast(e.detail || "详情加载失败"); });
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
      paperState.mode = "daily";
      paperState.tag = null;
      loadPapersList();
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

  function openModal(sel) { var m = qs(sel); if (m) m.classList.add("open"); }
  function closeModal(el) { var m = el.closest(".modal-mask"); if (m) m.classList.remove("open"); }

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
        if (!el.closest(".role-cell")) p.classList.add("hide");
      });
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
      if (targetSel === "#modal-set-general") refreshAvatarPanel();
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
      if (cur) cur.classList.remove("open");
      var switchTarget = switcher.getAttribute("data-modal-switch");
      openModal(switchTarget);
      if (switchTarget === "#modal-skillhub") loadMySkills();
      return;
    }
    var closer = el.closest("[data-modal-close]");
    if (closer) { closeModal(closer); return; }
    if (el.classList && el.classList.contains("modal-mask")) { el.classList.remove("open"); return; }

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
          date: (dateInput && dateInput.value) || new Date().toISOString().slice(0, 10)
        };
      }
      var btn = el.closest("[data-submit-tx]");
      btn.disabled = true;
      API.post("/money/transactions", payload).then(function () {
        if (mm) mm.classList.remove("open");
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
      var rpPop = el.closest(".role-cell").querySelector(".role-pop");
      if (rpPop) rpPop.classList.toggle("hide");
      return;
    }
    var roleOpt = el.closest("[data-role-opt]");
    if (roleOpt) {
      var rid2 = parseInt(roleOpt.getAttribute("data-role-opt"), 10);
      var uid2 = roleOpt.getAttribute("data-uid");
      var cellEl = roleOpt.closest(".role-cell");
      cellEl.querySelector(".role-pop").classList.add("hide");
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
      permSwEl.classList.toggle("on");
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
        mEnable.classList.toggle("on", !nowOn);
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
      mmReasonSw.classList.toggle("on");
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
    /* 其他场景的通用滑动开关（演示页兜底） */
    var sw = el.closest(".switch");
    if (sw && !el.closest("[data-udrawer]")) { sw.classList.toggle("on"); toast("已更新（演示）"); return; }

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
        if (pvMask) pvMask.classList.remove("open");
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
        if (mm) mm.classList.remove("open");
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
    if (el.closest('[data-modal-open="#modal-set-apps"]')) {
      API.get("/me").then(function (m) {
        var kws = ((m.settings || {}).subscribe_keywords || {}).keywords || [];
        var kwVal = qs("[data-kw-val]");
        if (kwVal) kwVal.textContent = kws.length ? kws.join("、") : "未配置";
      }).catch(function () {});
      /* 不 return：继续走弹层打开逻辑 */
    }
    if (el.closest("[data-kw-edit]")) {
      var kwVal = qs("[data-kw-val]");
      var current = kwVal && kwVal.textContent !== "未配置" ? kwVal.textContent : "";
      var input = window.prompt("订阅关键词（逗号分隔；每日据此抓取 PubMed 新文献）", current);
      if (input === null) return;
      var kws = input.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean);
      API.put("/me/settings", { key: "subscribe_keywords", value: { keywords: kws } }).then(function () {
        if (kwVal) kwVal.textContent = kws.length ? kws.join("、") : "未配置";
        toast(kws.length ? "订阅关键词已保存" : "已清空订阅关键词");
      }).catch(function (e) { toast(e.detail || "保存失败"); });
      return;
    }
    /* 文献页：收藏 toggle */
    var pSave = el.closest("[data-paper-save]");
    if (pSave) {
      var pid5 = parseInt(pSave.getAttribute("data-paper-save"), 10);
      API.post("/papers/" + pid5 + "/save", {}).then(function (r) {
        pSave.textContent = r.saved ? "已收藏" : "收藏";
        pSave.classList.toggle("is-on", r.saved);
        paperState.items.forEach(function (it) { if (it.id === pid5) it.saved = r.saved; });
        if (paperState.mode === "favorites") loadPapersList();
        toast(r.saved ? "已收藏" : "已取消收藏");
      }).catch(function (e) { toast(e.detail || "操作失败"); });
      return;
    }
    /* 文献页：生成 AI 解读 */
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
    /* 文献页：保存笔记 */
    var pNote = el.closest("[data-note-save]");
    if (pNote) {
      var pid7 = pNote.getAttribute("data-note-save");
      var ta = qs("[data-note-content]");
      var content = ta ? ta.value.trim() : "";
      if (!content) { toast("先写点内容"); return; }
      API.post("/papers/" + pid7 + "/note", { content: content }).then(function () {
        toast("笔记已保存");
      }).catch(function (e) { toast(e.detail || "保存失败"); });
      return;
    }
    /* 文献页：关闭抽屉 */
    if (el.closest("[data-pp-close]") || el.closest("[data-pp-mask]")) {
      var ppDr = qs("[data-pp-drawer]"), ppMk = qs("[data-pp-mask]");
      if (ppDr) ppDr.classList.add("hide");
      if (ppMk) ppMk.classList.add("hide");
      return;
    }
    /* 文献页：点击行打开详情 */
    var pRow = el.closest("[data-paper]");
    if (pRow) {
      openPaperDrawer(parseInt(pRow.getAttribute("data-paper"), 10));
      return;
    }
    /* 文献页：每日推送 / 我的收藏 切换 */
    if (el.closest("[data-papers-seg]")) {
      var segBtns = qsa("[data-papers-seg] button");
      segBtns.forEach(function (b) { b.classList.remove("active"); });
      el.closest("button").classList.add("active");
      paperState.mode = segBtns.indexOf(el.closest("button")) === 1 ? "favorites" : "daily";
      var tagBox = qs("[data-paper-tags]");
      if (tagBox) tagBox.style.display = paperState.mode === "daily" ? "" : "none";
      loadPapersList();
      return;
    }
    /* 文献页：标签筛选 */
    var pTag = el.closest("[data-ptag]");
    if (pTag) {
      qsa("[data-ptag]").forEach(function (c) { c.classList.remove("active"); });
      pTag.classList.add("active");
      var tv = pTag.getAttribute("data-ptag");
      paperState.tag = tv === "全部" ? null : tv;
      loadPapersList();
      return;
    }
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
    /* 会话：删除（真删，级联消息） */
    if (el.closest("[data-conv-del]")) {
      var delItem = el.closest(".conv-item");
      var delId = delItem ? parseInt(delItem.getAttribute("data-cid"), 10) : null;
      if (delId) {
        API.del("/chat/conversations/" + delId + "?app_id=chat").then(function () {
          toast("会话已删除");
          if (chatState.convId === delId) {
            chatState.convId = null;
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
    if (paletteOpen) {
      if (e.key === "Escape") { closePalette(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); paletteIndex = Math.min(paletteIndex + 1, paletteFiltered.length - 1); renderPaletteList(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); paletteIndex = Math.max(paletteIndex - 1, 0); renderPaletteList(); return; }
      if (e.key === "Enter") { e.preventDefault(); paletteExec(paletteIndex); return; }
      return;
    }
    if (e.key === "Escape") {
      qsa(".modal-mask.open").forEach(function (m) { m.classList.remove("open"); });
      qsa(".udrawer:not(.hide), .ud-mask:not(.hide)").forEach(function (m) { m.classList.add("hide"); });
      qsa(".role-pop:not(.hide)").forEach(function (m) { m.classList.add("hide"); });
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
    if (e.key === "Enter" && e.target.matches && e.target.matches(".composer textarea") && !e.shiftKey) {
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
      applyUserChrome();
      render();
    }).catch(function () { render(); });
  } else {
    render();
  }
})();
