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

  /* SSE 流式 POST（/chat）：返回 {response, onEvent, done} 手动消费 */
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

  window.LC_API = { BASE: BASE, getToken: getToken, setToken: setToken, clearToken: clearToken, request: request, get: get, post: post, put: put, del: del, stream: stream };
})();
