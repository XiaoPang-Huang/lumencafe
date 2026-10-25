/* 流光咖啡馆 · API 客户端层
 * 职责：token 存取、统一 fetch 封装（JSON + Bearer + 401 跳登录）。
 * 联调目标：本地后端 http://localhost:8000（docker compose api）。
 */
(function () {
  "use strict";

  /* API 基址自动探测：
   * - 本地开发（localhost / 127.0.0.1 / file:// 直开）：直连本机后端 :8000；
   * - 服务器部署：Caddy 同域反代 /api/* → api:8000，走同源 /api（无 CORS、可 HTTPS）。
   */
  var BASE = (function () {
    if (location.protocol === "file:" || location.hostname === "localhost" || location.hostname === "127.0.0.1") {
      return "http://localhost:8000";
    }
    return "/api";
  })();
  var TOKEN_KEY = "lc_token";

  function getToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }
  function setToken(t) {
    try { localStorage.setItem(TOKEN_KEY, t); } catch (e) {}
  }
  function clearToken() {
    try { localStorage.removeItem(TOKEN_KEY); } catch (e) {}
  }

  /* 统一请求：自动带 token；401 清 token 跳登录；非 2xx 抛 {status, detail} */
  async function request(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    var token = getToken();
    if (token) opts.headers["Authorization"] = "Bearer " + token;
    var resp = await fetch(BASE + path, opts);
    if (resp.status === 401 && location.hash !== "#/login") {
      clearToken();
      location.hash = "#/login";
      throw { status: 401, detail: "登录已过期，请重新登录" };
    }
    var text = await resp.text();
    var data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
    if (!resp.ok) {
      throw { status: resp.status, detail: (data && data.detail) || ("请求失败（" + resp.status + "）") };
    }
    return data;
  }

  function get(path) { return request(path); }
  function post(path, body) {
    return request(path, { method: "POST", body: JSON.stringify(body || {}) });
  }
  function put(path, body) {
    return request(path, { method: "PUT", body: JSON.stringify(body || {}) });
  }
  function del(path) { return request(path, { method: "DELETE" }); }

  /* SSE 流式 POST（/chat）：返回 Promise 手动消费。
   * 事件帧按 JSON 键分发（增量 v1 R3 起含 reasoning_delta），调用方 onEvent 自行区分：
   * {delta} 正文 / {reasoning_delta} 思维 / {error} 失败 / {done:true} 结束。 */
  function stream(path, body, onEvent) {
    var token = getToken();
    return fetch(BASE + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: token ? "Bearer " + token : ""
      },
      body: JSON.stringify(body || {})
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) {
          var d = null;
          try { d = JSON.parse(t); } catch (e) {}
          throw { status: resp.status, detail: (d && d.detail) || ("请求失败（" + resp.status + "）") };
        });
      }
      var reader = resp.body.getReader();
      var dec = new TextDecoder();
      var buf = "";
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) return null;
          buf += dec.decode(r.value, { stream: true });
          var parts = buf.split("\n\n");
          buf = parts.pop();
          parts.forEach(function (block) {
            var line = block.trim();
            if (line.indexOf("data:") !== 0) return;
            var data = line.slice(5).trim();
            if (data === "[DONE]") { onEvent({ done: true }); return; }
            try { onEvent(JSON.parse(data)); } catch (e) {}
          });
          return pump();
        });
      }
      return pump();
    });
  }

  /* 增量 v1：AI 润色（P1-2，POST /chat/polish {text} → {polished}） */
  function polish(text) { return post("/chat/polish", { text: text }); }

  /* 步 5 · 底座：系统状态（工作台状态灯真实数据源；GET /status → {api, db, backup, version}） */
  function status() { return get("/status"); }

  /* 每日看板 v2（2026-10-24）：论文板块信息流。
   * 本期为 mock 演示——直接 resolve data.js 的 LC_DATA.PAPERS_FEED；
   * 【真接口·第二批】n8n 抓取接入后改为 GET /papers/daily?limit=N（返回结构对齐 PAPERS_FEED）。 */
  var papers = {
    feed: function (limit) {
      var items = ((window.LC_DATA || {}).PAPERS_FEED) || [];
      if (limit) items = items.slice(0, limit);
      return Promise.resolve(items);
    }
  };

  /* 增量 v1：SkillHub 代理 + 已安装技能 + 用户上传（安装位置固定 app_id=chat） */
  var skills = {
    catalog: function (q) { return get("/skills/catalog?q=" + encodeURIComponent(q || "")); },
    install: function (skillhubId) { return post("/skills/install", { skillhub_id: skillhubId }); },
    mine: function () { return get("/skills/mine?app_id=chat"); },
    setEnabled: function (id, enabled) { return put("/skills/" + id + "/enabled", { enabled: enabled }); },
    uninstall: function (id) { return del("/skills/" + id); }
  };

  /* 上传自制 SKILL.md（multipart，不走 JSON 封装：request() 固定 Content-Type）。
   * 单独 fetch + Bearer；401 处理与 request() 保持一致。 */
  function uploadSkill(file) {
    var form = new FormData();
    form.append("file", file);
    var headers = {};
    var token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    return fetch(BASE + "/skills/upload", { method: "POST", headers: headers, body: form }).then(function (resp) {
      if (resp.status === 401 && location.hash !== "#/login") {
        clearToken();
        location.hash = "#/login";
        throw { status: 401, detail: "登录已过期，请重新登录" };
      }
      return resp.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) {}
        if (!resp.ok) {
          throw { status: resp.status, detail: (data && data.detail) || ("请求失败（" + resp.status + "）") };
        }
        return data;
      });
    });
  }
  skills.upload = uploadSkill;

  window.LC_API = { BASE: BASE, getToken: getToken, setToken: setToken, clearToken: clearToken, request: request, get: get, post: post, put: put, del: del, stream: stream, polish: polish, status: status, papers: papers, skills: skills };
})();
