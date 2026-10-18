/* 流光咖啡馆 v2 · SPA 运行时
 * 参考：midday（外壳+⌘K）、gethomepage（玻璃 Bento）、Homarr（卡片即入口）、
 *       Open WebUI（多板块单外壳）、macOS 系统设置（子应用统一骨架）
 * 联调状态：登录 / 对话 / 记账 已接真实 API（assets/js/api.js → localhost:8000）；
 *          工作台 / 应用中心 / 平台管理 仍为本地演示数据（D.*）。
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
    token: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M7 8V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v2"/><circle cx="12" cy="14" r="1.6"/>'
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

  /* ================= 路由 ================= */
  var ROUTES = ["workspace", "chat", "money", "apps", "admin", "me", "login"];
  var NAV = [
    { group: "主面板", items: [
      { route: "workspace", icon: "home", label: "工作台" },
      { route: "chat", icon: "chat", label: "对话" },
      { route: "money", icon: "money", label: "记账" }
    ] },
    { group: "系统", items: [
      { route: "apps", icon: "grid", label: "应用中心" },
      { route: "admin", icon: "gear", label: "平台管理" },
      { route: "me", icon: "user", label: "我的" }
    ] }
  ];
  var TITLES = { workspace: "工作台", chat: "AI 对话", money: "记账本", apps: "应用中心", admin: "平台管理", me: "我的", login: "登录" };

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
  function statusDot(ok) {
    return '<span class="status-dot' + (ok ? " on" : "") + '"></span>';
  }

  function sparkline(values, cls) {
    var max = Math.max.apply(null, values);
    return '<span class="sparkline">' + values.map(function (v) {
      return '<i class="' + cls + '" style="height:' + Math.max(8, Math.round((v / max) * 100)) + '%"></i>';
    }).join("") + "</span>";
  }

  /* 模型池：对话选择器用「活数据」（GET /chat/models），管理页仍用演示数据 */
  var liveModels = []; /* [{id, name, provider, capabilities, is_default}] */
  function modelPool() {
    var groups = {};
    liveModels.forEach(function (m) {
      (groups[m.provider] = groups[m.provider] || []).push(m);
    });
    return Object.keys(groups).map(function (k) {
      return { provider: k, items: groups[k].map(function (m) {
        return { id: m.id, name: m.name, context: (m.capabilities && m.capabilities.context) || "", files: !!(m.capabilities && m.capabilities.files), vision: !!(m.capabilities && m.capabilities.vision), is_default: !!m.is_default };
      }) };
    });
  }
  function defaultModel() {
    var d = liveModels.filter(function (m) { return m.is_default; })[0];
    return d ? d.name : (liveModels[0] ? liveModels[0].name : "default");
  }
  /* 对话会话状态（活数据：conversation_id / 模型 id） */
  var chatState = { convId: null, modelId: null, sending: false };
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

  /* 提供商详情面板（管理页右侧，选中切换时局部重绘） */
  function modelRowHtml(m) {
    return '<div class="mm-model">' +
      '<button class="switch on" type="button" data-model-enable aria-label="启用该模型"></button>' +
      '<span class="mname">' + m.name + (m.custom ? '<span class="badge-soon">自定义</span>' : "") + "</span>" +
      '<span class="mm-meta">' + (m.context || "") + "</span>" +
      '<span class="mm-caps">' +
        (m.vision ? '<i class="ic" data-ic="eye" title="支持图片理解"></i>' : "") +
        (m.files ? '<i class="ic" data-ic="doc" title="支持文件上传"></i>' : "") +
      "</span>" +
      '<span class="flex-spacer"></span>' +
      (m.is_default
        ? '<span class="pill pill-ok">默认</span>'
        : '<button class="btn btn-ghost btn-sm" type="button" data-set-default="' + m.name + '">设为默认</button>') +
      (m.custom ? '<button class="btn btn-danger-ghost btn-sm" type="button" data-del-model>删除</button>' : "") +
    "</div>";
  }
  function pvDetailHtml(pid) {
    var p = (D.providers || []).filter(function (x) { return String(x.id) === String(pid); })[0];
    if (!p) return "";
    var models = p.models || [];
    return '' +
      '<div class="mm-detail-head"><div><div class="mm-name">' + esc(p.name) +
        ' <span class="pill ' + (p.enabled ? "pill-ok" : "pill-mute") + '">' + (p.enabled ? "已启用" : "已停用") + "</span></div>" +
        '<div class="mm-url">' + p.base_url + "</div></div>" +
        '<button class="switch' + (p.enabled ? " on" : "") + '" type="button" data-provider-toggle aria-label="启用该提供商"></button></div>' +
      '<div class="mm-grid">' +
        '<div class="field" style="margin-bottom:0;"><label>Base URL</label><input type="text" value="' + p.base_url + '"></div>' +
        '<div class="field" style="margin-bottom:0;"><label>API Key</label><input type="text" value="" autocomplete="off" placeholder="已配置 ' + p.key_mask + "（留空不修改）\"></div>" +
      "</div>" +
      '<div class="mm-ops">' +
        '<button class="btn btn-ghost btn-sm" type="button" data-fetch="' + p.id + '"><i data-ic="spark"></i><span class="bl">拉取模型</span></button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-toast="连通性测试通过 · 延迟 412ms">测试连通性</button>' +
        '<button class="btn btn-ghost btn-sm" type="button" data-toast="配置已保存（演示）">保存</button>' +
      "</div>" +
      '<div class="mm-models"><div class="mm-models-head"><span>模型（' + models.length + "）</span>" +
        '<button class="btn btn-ghost btn-sm" type="button" data-add-model><i data-ic="plus"></i>添加模型</button></div>' +
        '<div class="mm-model-list">' + models.map(modelRowHtml).join("") + "</div></div>";
  }
  function renderPvDetail(pid) {
    var box = qs("#mm-detail");
    if (!box) return;
    box.innerHTML = pvDetailHtml(pid);
    injectIcons(box);
  }
  function pvListHtml(activeId) {
    return (D.providers || []).map(function (p) {
      var def = (p.models || []).filter(function (m) { return m.is_default; })[0];
      return '<div class="mm-item' + (String(p.id) === String(activeId) ? " active" : "") + '" data-pv="' + p.id + '" role="button" tabindex="0">' +
        '<span class="ico-box" style="background:' + (p.custom ? "#f2f3f5" : "#f0f6ff") + ";color:" + (p.custom ? "#4e5969" : "#1664ff") + ';"><i data-ic="plug"></i></span>' +
        '<div class="grow"><div class="name">' + esc(p.name) + "</div>" +
        '<div class="sub">' + (p.models || []).length + " 模型" + (def ? " · 默认 " + def.name : "") + "</div></div>" +
        '<span class="pill ' + (p.enabled ? "pill-ok" : "pill-mute") + '">' + (p.enabled ? "启用" : "停用") + "</span></div>";
    }).join("") +
    '<button class="btn btn-ghost btn-sm" type="button" data-toast="添加自定义提供商（名称 + base_url + Key）"><i data-ic="plus"></i>添加提供商</button>';
  }
  function permSw(on) {
    return '<button class="switch' + (on ? " on" : "") + '" type="button" data-perm-switch aria-label="切换权限"></button>';
  }
  function tokenRowHtml(t) {
    return "<tr><td>" + esc(t.name) + "</td>" +
      '<td><code class="mono-mask">' + t.mask + "</code></td>" +
      "<td>" + t.scope + "</td><td>" + t.created + "</td>" +
      "<td>" + (t.active ? '<span class="pill pill-ok">生效中</span>' : '<span class="pill pill-mute">已吊销</span>') + "</td>" +
      "<td>" + (t.active
        ? '<button class="link-op danger" type="button" data-revoke-token="' + t.id + '">吊销</button>'
        : '<span class="muted" style="font-size:12.5px;">—</span>') + "</td></tr>";
  }
  /* 成员详情抽屉（Supabase 侧栏模式） */
  function udrawerHtml(u) {
    var isAdmin = u.roles === "admin";
    function swRow(label, on) {
      return '<div class="ud-sw"><span>' + label + "</span>" + permSw(on) + "</div>";
    }
    return '' +
      '<div class="ud-head"><span class="avatar">' + (u.avatar || u.nickname.slice(0, 1)) + "</span>" +
      "<div style=\"flex:1;min-width:0;\"><div class=\"ud-name\">" + u.nickname + "</div>" +
      '<div class="ud-sub">@' + u.username + " · " + (isAdmin ? "管理员" : "成员") + "</div></div>" +
      '<button class="icon-btn" type="button" data-ud-close aria-label="关闭"><i data-ic="close"></i></button></div>' +
      '<div class="ud-body">' +
      '<div class="ud-sec">权限</div>' +
      swRow("使用对话", u.perms && u.perms.chat) +
      swRow("使用记账", u.perms && u.perms.money) +
      (isAdmin ? swRow("管理用户与角色", u.perms && u.perms.users) + swRow("管理模型与网关", u.perms && u.perms.models) : "") +
      '<div class="ud-sec">账号</div>' +
      '<div class="ud-kv"><span>状态</span><span>启用</span></div>' +
      '<div class="ud-kv"><span>最后活跃</span><span>' + (u.lastActive || "—") + "</span></div>" +
      '<div class="ud-kv"><span>注册时间</span><span>' + (u.joined || "—") + "</span></div>" +
      "</div>" +
      '<div class="ud-foot">' +
      '<button class="btn btn-ghost btn-sm" type="button" data-toast="已生成一次性新密码（演示）"><i data-ic="key"></i>重置密码</button>' +
      '<button class="btn btn-danger-ghost btn-sm" type="button" data-toast="账号已禁用（演示）">禁用账号</button></div>';
  }

  var PAGES = {
    /* ---------- 工作台：gethomepage 式玻璃 Bento ----------
     * 卡片解剖：头部(图标+名称+状态灯+右侧胶囊/操作) / 内容区(活数据) / 页脚(微型数据 + 一个主操作) */
    workspace: function () {
      var m = D.monthly, trend = D.trend || [];
      var expTrend = trend.map(function (t) { return t.expense; });
      var lastConv = (D.conversations || [])[0];
      var defModel = defaultModel();
      var cards = [
        /* AI 对话：通知式预览最近一次对话 */
        '<a class="bcard span-6" href="#/chat" draggable="true" data-bcard="chat">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="chat"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">AI 对话 ' + statusDot(true) + "</span></div>" +
          '<div class="bcard-tools"><span class="bcard-pill">' + esc(defModel) + "</span>" +
          '<button class="icon-btn xs" type="button" data-new-conv-link aria-label="新建对话"><i data-ic="edit"></i></button></div></div>' +
          '<div class="bcard-body">' +
            (lastConv
              ? '<div class="bcard-preview"><span class="bp-text">' + esc(lastConv.title) + '</span><span class="bp-time">' + lastConv.updated + "</span></div>"
              : '<div class="bcard-preview"><span class="bp-text muted">还没有对话，点击卡片开始聊聊</span></div>') +
          "</div>" +
          '<div class="bcard-foot"><span class="bcard-micro">本月 12 次对话</span><span class="bcard-go">继续聊<i data-ic="arrow"></i></span></div>' +
        "</a>",
        /* 记账：迷你趋势（收支数字在顶部指标带） */
        '<a class="bcard span-6" href="#/money" draggable="true" data-bcard="money">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="money"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">记账本 ' + statusDot(true) + "</span></div></div>" +
          '<div class="bcard-body" style="flex-direction:row;align-items:flex-end;">' +
            '<div class="spark-wrap" style="margin-left:0;">' + sparkline(expTrend, "ex") + "<small>近 6 月支出</small></div>" +
          "</div>" +
          '<div class="bcard-foot"><span class="bcard-micro">本月 23 笔 · 餐饮占比最高</span><span class="bcard-go">记一笔<i data-ic="arrow"></i></span></div>' +
        "</a>",
        /* 文献：第二批（灰态，只留一句短语） */
        '<a class="bcard span-4 is-disabled" href="#/apps" draggable="true" data-bcard="papers">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;"><i data-ic="book"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">文献 ' + statusDot(false) + ' <span class="badge-soon">第二批</span></span></div></div>' +
          '<div class="bcard-body"><span class="bcard-muted">PubMed 每日新文献跟踪</span></div>' +
        "</a>",
        /* 平台管理：结构化微数据 */
        '<a class="bcard span-4" href="#/admin" draggable="true" data-bcard="admin">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f2f3f5;color:#4e5969;"><i data-ic="gear"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">平台管理 ' + statusDot(true) + "</span></div></div>" +
          '<div class="bcard-foot"><span class="bcard-micro">2 用户 · 2 Provider</span><span class="bcard-go">进入管理<i data-ic="arrow"></i></span></div>' +
        "</a>",
        /* 应用中心 */
        '<a class="bcard span-4" href="#/apps" draggable="true" data-bcard="apps">' +
          '<span class="grip" data-ic="grip" title="拖拽排序"></span>' +
          '<div class="bcard-head"><span class="ico-box" style="background:#f0f6ff;color:#1664ff;"><i data-ic="grid"></i></span>' +
          '<div class="bcard-title"><span class="bcard-name">应用中心 ' + statusDot(true) + "</span></div></div>" +
          '<div class="bcard-foot"><span class="bcard-go">浏览全部<i data-ic="arrow"></i></span></div>' +
        "</a>"
      ];
      /* 读取拖拽排序缓存 */
      var order = [];
      try { order = JSON.parse(localStorage.getItem("lc_home_order") || "[]"); } catch (e) { order = []; }
      cards.sort(function (a, b) {
        var ia = order.indexOf(a.match(/data-bcard="(\w+)"/)[1]);
        var ib = order.indexOf(b.match(/data-bcard="(\w+)"/)[1]);
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      });
      /* 概览指标带（火山方舟 overview 模式：大数字 + 小标题） */
      var stats =
        '<div class="stat-cell"><small>今日对话</small><b>6<span class="stat-unit">轮</span></b></div>' +
        '<div class="stat-cell"><small>本月支出</small><b class="ex">' + fenShort(m.expenseTotal) + "</b></div>" +
        '<div class="stat-cell"><small>本月收入</small><b class="inc">' + fenShort(m.incomeTotal) + "</b></div>" +
        '<div class="stat-cell"><small>结余</small><b>' + fenShort(m.balance) + "</b></div>";
      return '' +
        '<div class="page-head" style="margin-bottom:16px;"><div><h1 class="page-title">工作台</h1></div>' +
        '<span class="date">10月18日 星期日</span></div>' +
        '<div class="stat-strip">' + stats + "</div>" +
        '<div class="sec-head" style="margin-top:22px;"><span class="sec-title">应用</span>' +
        '<span class="muted" style="font-size:12.5px;">拖拽调整顺序</span></div>' +
        '<div class="bento-grid">' + cards.join("") + "</div>";
    },

    /* ---------- 对话：ChatApp（模型选择器 + 文件上传入口；已联调真实 /chat SSE） ---------- */
    chat: function () {
      return '' +
        '<div class="chat-layout">' +
          '<aside class="conv-panel">' +
            '<div class="conv-head"><span class="t">AI 对话</span>' +
            '<button class="icon-btn" type="button" data-new-conv aria-label="新建会话"><i data-ic="plus"></i></button></div>' +
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
            /* 输入框：参考 WorkBuddy——圆角白卡 + 底部工具条（附件左、模型与发送右） */
            '<div class="composer-wrap">' +
              '<div class="composer">' +
                '<textarea rows="1" placeholder="问点什么…（Enter 发送，Shift+Enter 换行）"></textarea>' +
                '<div class="composer-bar">' +
                  '<button class="icon-btn xs" type="button" data-upload aria-label="上传文件"><i data-ic="clip"></i></button>' +
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

    /* ---------- 应用中心 ---------- */
    apps: function () {
      function rows(list) {
        return list.map(function (a) {
          var dis = a.disabled ? " is-disabled" : "";
          var ops;
          if (a.disabled) ops = '<button class="btn btn-ghost btn-sm" type="button" data-toast="文献应用第二批上线后开放">敬请期待</button>';
          else ops = '<button class="btn btn-ghost btn-sm" type="button" data-toast="已打开「' + esc(a.name) + '」（演示）">打开</button>';
          return '<div class="app-row' + dis + '">' +
            '<span class="ico-box" style="background:' + a.color + ";color:" + a.ink + ';"><i data-ic="' + a.icon + '"></i></span>' +
            '<div class="grow"><div class="name">' + esc(a.name) + (a.disabled ? '<span class="badge-soon">第二批上线</span>' : "") + "</div>" +
            '<div class="desc">' + esc(a.desc) + "</div></div>" +
            '<div class="ops">' + ops + "</div></div>";
        }).join("");
      }
      var byCat = {};
      (D.apps || []).forEach(function (a) {
        if (a.internal) return; /* 应用中心自身不列入列表 */
        (byCat[a.category] = byCat[a.category] || []).push(a);
      });
      var catName = { ai: "AI 应用", life: "生活工具", platform: "平台" };
      var groups = Object.keys(byCat).map(function (cid) {
        return '<div class="app-group"><div class="app-group-title">' + (catName[cid] || cid) + "</div>" + rows(byCat[cid]) + "</div>";
      }).join("");
      return '' +
        '<div class="page-head"><div><h1 class="page-title">应用中心</h1>' +
        '<div class="page-desc">全部应用按分类分组，可搜索</div></div></div>' +
        '<div class="search-bar"><i data-ic="search"></i>' +
        '<input type="search" placeholder="搜索应用名称或描述" data-app-search></div>' +
        groups +
        '<div class="empty-state hide" data-app-empty>没有匹配的应用</div>';
    },

    /* ---------- 平台管理：用户与角色（Supabase 式表格 + 角色矩阵 + 详情抽屉）/ 模型管理（LobeChat 式双栏）/ 网关令牌 ---------- */
    admin: function () {
      /* 成员表（参考 Supabase Auth Users）：权限不铺列（应用多了会拥挤），点击行在抽屉里设置 */
      var users = (D.users || []).map(function (u) {
        var isAdmin = u.roles === "admin";
        var permCount = u.perms ? Object.keys(u.perms).filter(function (k) { return u.perms[k]; }).length : 0;
        return '<tr class="u-row" data-user-row="' + u.id + '">' +
          '<td><span class="u-cell"><span class="avatar">' + (u.avatar || u.nickname.slice(0, 1)) + '</span>' +
            '<span><span class="u-name">' + u.nickname + '</span><span class="u-sub">' + u.username + "</span></span></span></td>" +
          '<td><span class="role-cell">' +
            '<button class="role-pill ' + (isAdmin ? "is-admin" : "") + '" type="button" data-role-picker>' +
              (isAdmin ? "管理员" : "成员") + '<i data-ic="down"></i></button>' +
            '<span class="role-pop hide">' +
              '<span class="role-opt" data-role-opt="管理员"><b>管理员</b><small>全部权限，含平台管理</small></span>' +
              '<span class="role-opt" data-role-opt="成员"><b>成员</b><small>仅应用使用权限</small></span>' +
            "</span></span></td>" +
          '<td><span class="muted" style="font-size:13px;">' + permCount + ' 项权限</span></td>' +
          '<td><span class="st"><i></i>启用</span></td>' +
          '<td><span class="muted" style="font-size:13px;">' + (u.lastActive || "—") + "</span></td>" +
          '<td class="t-right"><button class="icon-btn xs" type="button" data-toast="已生成一次性新密码（演示）" aria-label="重置密码" title="重置密码"><i data-ic="key"></i></button></td>' +
        "</tr>";
      }).join("");
      /* 角色权限矩阵（thefrontkit 模式：行=权限点，列=角色） */
      var roleCols = (D.roles || []);
      function hasPerm(r, code) { return (r.permissions || []).indexOf(code) !== -1; }
      var mxRows = [
        ["使用对话", "app:chat"], ["使用记账", "app:money"], ["使用文献（第二批）", "app:papers"],
        ["管理用户与角色", "admin:users"], ["管理模型与网关", "admin:models"]
      ].map(function (row) {
        var cells = roleCols.map(function (r) {
          return "<td>" + (hasPerm(r, row[1])
            ? '<span class="mx-yes"><i data-ic="check"></i></span>'
            : '<span class="mx-none">—</span>') + "</td>";
        }).join("");
        return "<tr><td>" + row[0] + "</td>" + cells + "</tr>";
      }).join("");
      var mxHead = roleCols.map(function (r) { return "<th>" + r.label + "</th>"; }).join("");
      var tokens = (D.gatewayTokens || []).map(tokenRowHtml).join("");
      return '' +
        '<div class="page-head"><div><h1 class="page-title">平台管理</h1>' +
        '<div class="page-desc">成员、模型与网关</div></div></div>' +
        '<div class="admin-tabs">' +
          '<button class="admin-tab active" type="button" data-admin-tab="#pane-users"><i data-ic="users" style="vertical-align:-3px;"></i> 用户与角色</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-models"><i data-ic="plug" style="vertical-align:-3px;"></i> 模型管理</button>' +
          '<button class="admin-tab" type="button" data-admin-tab="#pane-tokens"><i data-ic="token" style="vertical-align:-3px;"></i> 网关令牌</button>' +
        "</div>" +
        /* 用户与角色 */
        '<div class="admin-pane active" id="pane-users">' +
          '<div class="sec-head"><span class="sec-title">成员</span>' +
            '<button class="btn btn-sm" type="button" data-toast="注册开关关闭时暂不可邀请（演示）"><i data-ic="plus"></i>邀请成员</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table u-table"><thead>' +
          "<tr><th>成员</th><th>角色</th><th>权限</th><th>状态</th><th>最后活跃</th><th></th></tr></thead><tbody>" + users +
          '</tbody></table></div>' +
          '<div style="font-size:12.5px;color:var(--ink-3);margin-top:10px;">点击成员行设置应用与管理权限</div>' +
          '<div class="sec-head" style="margin-top:24px;"><span class="sec-title">角色权限</span></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table mx-table"><thead>' +
          "<tr><th>权限</th>" + mxHead + "</tr></thead><tbody>" + mxRows +
          '</tbody></table></div>' +
          /* 成员详情抽屉（Supabase 侧栏模式） */
          '<div class="ud-mask hide" data-ud-mask></div>' +
          '<aside class="udrawer hide" data-udrawer></aside>' +
        "</div>" +
        /* 模型管理（方案 1：左列表 + 右详情） */
        '<div class="admin-pane" id="pane-models">' +
          '<div class="mm-layout">' +
            '<div class="mm-list" id="mm-list">' + pvListHtml(1) + "</div>" +
            '<div class="card mm-detail" id="mm-detail">' + pvDetailHtml(1) + "</div>" +
          "</div>" +
        "</div>" +
        /* 网关令牌 */
        '<div class="admin-pane" id="pane-tokens">' +
          '<div class="gw-endpoint"><span class="gw-endpoint-label">接入地址</span>' +
            '<code class="mono-mask" id="gw-url">https://api.lumenhub.online/gw/v1</code>' +
            '<button class="btn btn-ghost btn-sm" type="button" data-copy-text="#gw-url">复制</button></div>' +
          '<div class="card" style="padding:8px 6px;overflow-x:auto;"><table class="table"><thead>' +
          "<tr><th>名称</th><th>令牌</th><th>模型范围</th><th>创建时间</th><th>状态</th><th>操作</th></tr></thead>" +
          '<tbody id="gw-token-rows">' + tokens + "</tbody></table></div>" +
          '<button class="btn btn-sm mt8" type="button" data-modal-open="#modal-token"><i data-ic="plus"></i>新建令牌</button>' +
        "</div>";
    },

    /* ---------- 我的：三域设置统一入口（通用 / 应用 / 管理） ---------- */
    me: function () {
      var u = LC_USER || { username: "…", nickname: "…", roles: [] };
      var isAdmin = (u.roles || []).indexOf("admin") !== -1;
      return '' +
        '<div class="page-head"><div><h1 class="page-title">我的</h1>' +
        '<div class="page-desc">账号信息、设置与关于</div></div></div>' +
        '<div class="card me-card"><span class="avatar">' + esc((u.nickname || u.username || "?").slice(0, 1)) + "</span>" +
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
  function renderMpPop() {
    var pop = qs("[data-mp-pop]");
    if (!pop) return;
    pop.innerHTML = modelPool().map(function (g) {
      return '<div class="mp-group"><div class="mp-group-label">' + esc(g.provider) + "</div>" +
        g.items.map(function (it) {
          return '<div class="mp-item" data-mp-item="' + it.id + '" role="button" tabindex="0">' +
            '<span class="mp-name">' + esc(it.name) + (it.is_default ? '<span class="pill pill-ok">默认</span>' : "") + "</span>" +
            '<span class="mp-meta">' + (it.context || "") + "</span>" +
            (it.files ? '<i class="ic" data-ic="doc" title="支持文件上传"></i>' : "") +
            (it.vision ? '<i class="ic" data-ic="eye" title="支持图片理解"></i>' : "") +
            '<i class="ic mp-check" data-ic="check" style="visibility:hidden;"></i></div>';
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
  function renderChatMessages(messages) {
    var inner = qs("[data-chat-inner]");
    if (!inner) return;
    var who = LC_USER ? LC_USER.nickname : "我";
    inner.innerHTML = messages.map(function (m) {
      var isAi = m.role === "assistant";
      return '<div class="msg ' + (isAi ? "ai" : "user") + '"><span class="avatar">' + (isAi ? "馆" : esc(who)) + "</span>" +
        '<div class="msg-body"><div class="msg-text"><p>' + esc(m.content) + "</p></div></div></div>";
    }).join("");
    var sc = qs(".chat-scroll");
    if (sc) sc.scrollTop = sc.scrollHeight;
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
    },

    chat: function (view) {
      /* 活数据：模型池 + 会话列表（异步填充） */
      API.get("/chat/models").then(function (models) {
        liveModels = models || [];
        var def = liveModels.filter(function (m) { return m.is_default; })[0] || liveModels[0];
        chatState.modelId = def ? def.id : null;
        renderMpPop();
        var lbl = qs("[data-mp-label]", view);
        if (lbl) lbl.textContent = def ? def.name : "无可用模型";
        syncMpCheck();
        syncUploadBtn();
      }).catch(function (e) { toast(e.detail || "模型池加载失败"); });
      refreshConversations(true);

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

    apps: function () {},

    admin: function () {},

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
    if (opener) { openModal(opener.getAttribute("data-modal-open")); return; }
    /* 弹层间切换：关掉当前，打开目标 */
    var switcher = el.closest("[data-modal-switch]");
    if (switcher) {
      var cur = switcher.closest(".modal-mask");
      if (cur) cur.classList.remove("open");
      openModal(switcher.getAttribute("data-modal-switch"));
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
    /* 成员行 → 详情抽屉（Supabase 侧栏模式） */
    var urow = el.closest("[data-user-row]");
    if (urow && !el.closest(".switch") && !el.closest(".role-cell") && !el.closest("button")) {
      var uu = (D.users || []).filter(function (x) { return String(x.id) === urow.getAttribute("data-user-row"); })[0];
      var dr = qs("[data-udrawer]"), mk = qs("[data-ud-mask]");
      if (uu && dr) { dr.innerHTML = udrawerHtml(uu); injectIcons(dr); dr.classList.remove("hide"); }
      if (mk) mk.classList.remove("hide");
      return;
    }
    if (el.closest("[data-ud-close]") || el.closest("[data-ud-mask]")) {
      var dr2 = qs("[data-udrawer]"), mk2 = qs("[data-ud-mask]");
      if (dr2) dr2.classList.add("hide");
      if (mk2) mk2.classList.add("hide");
      return;
    }
    /* 角色下拉（Zeda 模式：选项带权限说明） */
    if (el.closest("[data-role-picker]")) {
      var rpPop = el.closest(".role-cell").querySelector(".role-pop");
      if (rpPop) rpPop.classList.toggle("hide");
      return;
    }
    var roleOpt = el.closest("[data-role-opt]");
    if (roleOpt) {
      var cellEl = roleOpt.closest(".role-cell");
      var pill = cellEl.querySelector(".role-pill");
      var txt = roleOpt.getAttribute("data-role-opt");
      if (pill && pill.firstChild) pill.firstChild.textContent = txt + " ";
      pill.classList.toggle("is-admin", txt === "管理员");
      cellEl.querySelector(".role-pop").classList.add("hide");
      toast("角色已切换为 " + txt + "（演示）");
      return;
    }
    /* 通用滑动开关（提供商启用 / 模型启用 / 权限开关） */
    var sw = el.closest(".switch");
    if (sw) { sw.classList.toggle("on"); toast("已更新（演示）"); return; }

    /* 模型管理：切换提供商条目 */
    var mmItem = el.closest("[data-pv]");
    if (mmItem && !el.closest(".btn")) {
      var pid = mmItem.getAttribute("data-pv");
      qsa("#mm-list .mm-item").forEach(function (i) { i.classList.toggle("active", i === mmItem); });
      renderPvDetail(pid);
      return;
    }
    /* 设为默认模型 */
    var setDef = el.closest("[data-set-default]");
    if (setDef) {
      var name = setDef.getAttribute("data-set-default");
      (D.providers || []).forEach(function (p) {
        (p.models || []).forEach(function (m) { m.is_default = (m.name === name); });
      });
      var activePv = qs("#mm-list .mm-item.active");
      renderPvDetail(activePv ? activePv.getAttribute("data-pv") : 1);
      var listBox = qs("#mm-list");
      if (listBox) { listBox.innerHTML = pvListHtml(activePv ? activePv.getAttribute("data-pv") : 1); injectIcons(listBox); }
      toast("默认模型已切换为 " + name);
      return;
    }
    /* 删除自定义模型 */
    if (el.closest("[data-del-model]")) {
      var row = el.closest(".mm-model");
      if (row) { row.remove(); toast("自定义模型已删除"); }
      return;
    }
    /* 添加自定义模型 */
    if (el.closest("[data-add-model]")) {
      var mlist = qs("#mm-detail .mm-model-list");
      if (mlist) {
        var n = mlist.children.length + 1;
        mlist.insertAdjacentHTML("beforeend", modelRowHtml({ name: "custom-model-" + n, context: "—", custom: true }));
        injectIcons(mlist);
        toast("已添加自定义模型（演示）");
      }
      return;
    }
    /* 拉取模型（平铺列表） */
    var fetchBtn = el.closest("[data-fetch]");
    if (fetchBtn) {
      var fpid = fetchBtn.getAttribute("data-fetch");
      var prov = (D.providers || []).filter(function (pp) { return String(pp.id) === fpid; })[0];
      var mlist2 = qs("#mm-detail .mm-model-list");
      if (!prov || !mlist2) return;
      var bl = fetchBtn.querySelector(".bl");
      fetchBtn.disabled = true;
      if (bl) bl.textContent = "拉取中…";
      setTimeout(function () {
        fetchBtn.disabled = false;
        if (bl) bl.textContent = "重新拉取";
        var arr = prov.remoteModels || [];
        mlist2.innerHTML = arr.length
          ? arr.map(modelRowHtml).join("")
          : '<div class="muted" style="padding:10px 0;font-size:13px;">该端点未暴露模型列表，请手动添加模型</div>';
        injectIcons(mlist2);
        toast(arr.length ? "已从官方 API 拉取 " + arr.length + " 个模型" : "未获取到模型列表，请手动添加");
      }, 1100);
      return;
    }
    /* 网关令牌：吊销 / 复制 */
    var revoke = el.closest("[data-revoke-token]");
    if (revoke) {
      var tid = revoke.getAttribute("data-revoke-token");
      (D.gatewayTokens || []).forEach(function (t) { if (String(t.id) === tid) t.active = false; });
      var tb = qs("#gw-token-rows");
      if (tb) tb.innerHTML = (D.gatewayTokens || []).map(tokenRowHtml).join("");
      toast("令牌已吊销，调用方立即失效");
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
    /* 新建网关令牌 */
    var createToken = el.closest("[data-create-token]");
    if (createToken) {
      var tname = qs("#token-name");
      var scopeChip = qs('[data-token-scope] .chip.active');
      var once = qs("#token-once");
      if (!tname || !tname.value.trim()) { toast("先给令牌起个名字，比如 n8n"); return; }
      var fullKey = "sk-lumen" + Math.random().toString(36).slice(2, 10);
      var mask = "sk-••••" + fullKey.slice(-4);
      D.gatewayTokens = D.gatewayTokens || [];
      D.gatewayTokens.push({ id: Date.now(), name: tname.value.trim(), mask: mask, scope: scopeChip ? scopeChip.textContent.trim() : "全部模型", created: "2026-10-18", active: true });
      var tb2 = qs("#gw-token-rows");
      if (tb2) tb2.innerHTML = D.gatewayTokens.map(tokenRowHtml).join("");
      if (once) {
        once.classList.remove("hide");
        var code = once.querySelector("code");
        if (code) code.textContent = fullKey;
      }
      toast("令牌已创建，只完整显示这一次");
      return;
    }
    /* 模型选择器 */
    if (el.closest("[data-model-picker]")) {
      var pop = qs("[data-mp-pop]");
      if (pop) pop.classList.toggle("hide");
      return;
    }
    var mpItem = el.closest("[data-mp-item]");
    if (mpItem) {
      chatState.modelId = parseInt(mpItem.getAttribute("data-mp-item"), 10);
      var mName = "";
      liveModels.forEach(function (m) { if (m.id === chatState.modelId) mName = m.name; });
      var lbl = qs("[data-mp-label]");
      if (lbl) lbl.textContent = mName || "default";
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
    if (e.key === "Enter" && e.target.matches && e.target.matches(".composer textarea") && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  qs("#palette-input").addEventListener("input", function (e) { filterPalette(e.target.value); });

  /* 对话发送：POST /chat SSE 流式渲染（delta 逐段 + [DONE]） */
  function sendMessage() {
    var composer = qs(".composer textarea");
    var inner = qs("[data-chat-inner]");
    if (!composer || !inner || chatState.sending) return;
    var text = composer.value.trim();
    if (!text) return;
    var who = LC_USER ? LC_USER.nickname : "我";
    var emptyEl = qs("[data-chat-empty]");
    if (emptyEl) emptyEl.remove();
    var userMsg = document.createElement("div");
    userMsg.className = "msg user";
    userMsg.innerHTML = '<span class="avatar">' + esc(who) + '</span><div class="msg-body"><div class="msg-text"><p></p></div></div>';
    userMsg.querySelector("p").textContent = text;
    inner.appendChild(userMsg);
    composer.value = "";
    composer.style.height = "auto";

    var reply = document.createElement("div");
    reply.className = "msg ai cursor";
    reply.innerHTML = '<span class="avatar">馆</span><div class="msg-body"><div class="msg-text"><span class="thinking"><i></i><i></i><i></i></span><span class="stream-text"></span></div></div>';
    inner.appendChild(reply);
    var node = reply.querySelector(".stream-text");
    var sc = qs(".chat-scroll");
    function scrollBottom() { if (sc) sc.scrollTop = sc.scrollHeight; }
    scrollBottom();

    var body = { app_id: "chat", message: text };
    if (chatState.convId) body.conversation_id = chatState.convId;
    if (chatState.modelId) body.model_id = chatState.modelId;
    chatState.sending = true;

    API.stream("/chat", body, function (ev) {
      var dots = reply.querySelector(".thinking");
      if (ev.done) {
        if (dots) dots.remove();
        reply.classList.remove("cursor");
        chatState.sending = false;
        refreshConversations(true);
        return;
      }
      if (dots) dots.remove();
      if (ev.delta) { node.textContent += ev.delta; scrollBottom(); }
      if (ev.error) {
        node.textContent += (node.textContent ? "\n" : "") + "⚠️ " + ev.error;
        reply.classList.remove("cursor");
        chatState.sending = false;
        scrollBottom();
      }
    }).catch(function (ex) {
      var dots2 = reply.querySelector(".thinking");
      if (dots2) dots2.remove();
      node.textContent = "发送失败：" + (ex && ex.detail ? ex.detail : "网络错误");
      reply.classList.remove("cursor");
      chatState.sending = false;
      scrollBottom();
    });
  }

  /* 会话面板输入框自适应（委托 input 已覆盖文本域，此处针对 composer 高度） */
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches(".composer textarea")) {
      e.target.style.height = "auto";
      e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
    }
  });

  /* ================= 启动 ================= */
  function applyUserChrome() {
    if (!LC_USER) return;
    var initial = esc((LC_USER.nickname || LC_USER.username || "?").slice(0, 1));
    var avatar = qs("#topbar-avatar");
    if (avatar) avatar.textContent = initial;
    var siderUser = qs(".sider-user");
    if (siderUser) {
      var a = siderUser.querySelector(".avatar");
      if (a) a.textContent = initial;
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
