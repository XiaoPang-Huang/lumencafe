// 对话页真实浏览器交互测试：会话批量管理、模型二级思考配置页。
// 使用本机 Chrome/Edge headless，无新增 npm 依赖；无浏览器的环境自动跳过。
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import WebSocket from "ws";
const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const chatUrl = pathToFileURL(path.join(rootDir, "src/static/assets/js/chat.js")).href;
const browser = [
  process.env.CHROME_BIN,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find((p) => p && existsSync(p));

async function runBrowser(caseName) {
  const dir = await mkdtemp(path.join(tmpdir(), "lc-chat-ui-"));
  const proc = spawn(browser, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check",
    "--allow-file-access-from-files", "--remote-debugging-port=0", `--user-data-dir=${path.join(dir, "profile")}`,
  ], { stdio: "ignore", windowsHide: true });
  let ws;
  try {
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>
      <div id="view"></div><dialog id="modal"></dialog>
      <script>
        const calls = [];
        const conversations = [
          { id: "c1", title: "会话甲", model: "a/chat", thinking: null },
          { id: "c2", title: "会话乙", model: null, thinking: null },
          { id: "c3", title: "会话丙", model: null, thinking: null },
        ];
        const models = [
          { id: "a/chat", name: "模型甲", thinking: "low", thinkingLevels: ["low", "high"], reasoning: true, supportsImages: true },
          { id: "b/chat", name: "模型乙", thinking: null, thinkingLevels: ["medium", "max"], reasoning: false, supportsImages: false },
          { id: "c/chat", name: "模型丙", thinking: null, thinkingLevels: [], reasoning: false, supportsImages: false },
        ];
        const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
        const api = async (url, opts = {}) => {
          const method = opts.method || "GET";
          const body = opts.body ? JSON.parse(opts.body) : null;
          calls.push({ method, url, body });
          if (url === "/api/chat/models") return { models, default_model: "a/chat", real: true };
          if (url === "/api/chat/conversations" && method === "GET") return { conversations };
          if (url.endsWith("/messages")) return { messages: [] };
          const match = url.match(/\\/api\\/chat\\/conversations\\/([\\w-]+)/);
          if (match && method === "PATCH") {
            const conv = conversations.find((c) => c.id === match[1]);
            Object.assign(conv, body);
            return { conversation: conv };
          }
          if (match && method === "DELETE") {
            conversations.splice(conversations.findIndex((c) => c.id === match[1]), 1);
            return { ok: true };
          }
          throw new Error(method + " " + url);
        };
        window.LC = {
          api, apiStream: api, esc, getState: () => ({ principal: { id: "u1" } }),
          IC: { copy: "复制", refresh: "刷新", caret: "▾", chat: "+", grid: "☰", arrow: "↑" },
          openModal: (title, body, foot) => {
            const modal = document.getElementById("modal");
            modal.innerHTML = "<h2>" + esc(title) + "</h2><div>" + body + "</div><footer>" + foot + "</footer>";
            modal.setAttribute("open", "");
          },
          closeModal: () => document.getElementById("modal").removeAttribute("open"),
        };
        window.LCVendor = {
          MarkdownIt: class { render(text) { return text ? "<p>" + esc(text) + "</p>" : ""; } },
          hljs: { highlightElement() {} },
        };
      </script>
      <script src="${chatUrl}"></script>
      <script>
        const results = [];
        const check = (condition, message) => { if (!condition) throw new Error(message); };
        const record = async (name, fn) => {
          try { await fn(); results.push({ name, ok: true }); }
          catch (error) { results.push({ name, ok: false, error: error.message }); }
        };
        const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
        const click = (selector) => {
          const node = document.querySelector(selector);
          check(node, "找不到元素 " + selector);
          node.click();
        };
        async function testManage() {
          LC.views.chat.mount(document.getElementById("view"));
          await tick();
          check(document.querySelector('[data-conv-menu="c1"]').textContent === "⋮", "会话操作不是竖向三点");
          click('[data-conv-menu="c1"]');
          check(document.querySelector('[data-manage="c1"]'), "三点菜单没有管理入口");
          check(document.querySelector('[data-del="c1"]'), "三点菜单没有删除入口");
          click('[data-manage="c1"]');
          check(document.querySelectorAll("[data-pick-conv]").length === 3, "管理模式没有为每个会话显示勾选框");
          check(!document.querySelector(".conv-manage-bar").hidden, "管理模式没有显示底部操作条");
          click("[data-sel-all]");
          check(document.querySelectorAll("[data-pick-conv]:checked").length === 3, "全选没有勾选全部会话");
          check(!document.querySelector("[data-batch-del]").disabled, "全选后删除按钮仍不可用");
          click("[data-batch-del]");
          check(document.querySelector("#bdel-ok"), "批量删除没有弹出确认框");
          click("#bdel-ok");
          await tick();
          check(calls.filter((c) => c.method === "DELETE").length === 3, "没有逐个删除选中的三个会话");
          check(document.querySelector(".conv-manage-bar").hidden, "批量删除后没有退出管理模式");
        }
        async function testModels() {
          location.hash = "#/chat/c1";
          LC.views.chat.mount(document.getElementById("view"));
          await tick();
          click("[data-model-menu]");
          check(!document.querySelector(".mm-detail"), "模型主列表不应直接显示某个模型的配置页");
          click('[data-exp-model="b/chat"]');
          check(document.querySelector(".mm-detail"), "点击模型配置入口没有进入二级页面");
          check(document.querySelector("[data-model-back]"), "二级页面没有返回模型列表入口");
          let chips = [...document.querySelectorAll("[data-pick-thinking]")].map((n) => n.textContent);
          check(chips.join("|") === "跟随模型|中|极致", "模型乙没有严格使用自己的 medium/max 档位：" + chips.join("|"));
          click('[data-pick-thinking="medium"]');
          await tick();
          const patches = calls.filter((c) => c.method === "PATCH");
          check(patches.some((c) => c.body?.model === "b/chat"), "在其他模型下选档位没有同时切换模型");
          check(patches.some((c) => c.body?.thinking === "medium"), "思考档位没有保存到会话");
          click("[data-model-back]");
          click('[data-exp-model="a/chat"]');
          chips = [...document.querySelectorAll("[data-pick-thinking]")].map((n) => n.textContent);
          check(chips.join("|") === "跟随模型|关闭|低|高", "模型甲没有严格使用自己的 low/high 档位：" + chips.join("|"));
          click("[data-model-back]");
          click('[data-exp-model="c/chat"]');
          chips = [...document.querySelectorAll("[data-pick-thinking]")].map((n) => n.textContent);
          check(chips.join("|") === "跟随模型", "未配置档位的模型被错误补了默认档位：" + chips.join("|"));
          check(document.querySelector(".mm-level-empty"), "未配置档位时没有空态说明");
        }
        (async () => {
          if (${JSON.stringify(caseName)} === "manage") await record("会话批量管理", testManage);
          else await record("模型二级思考配置", testModels);
          const pre = document.createElement("pre");
          pre.id = "test-results";
          pre.textContent = JSON.stringify(results);
          document.body.appendChild(pre);
        })();
      </script>
    </body></html>`;
    const file = path.join(dir, "case.html");
    await writeFile(file, html, "utf8");
    const portFile = path.join(dir, "profile", "DevToolsActivePort");
    let portText = "";
    for (let i = 0; i < 200 && !portText; i++) {
      portText = await readFile(portFile, "utf8").catch(() => "");
      if (!portText) await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(portText, "浏览器调试端口启动超时");
    const [port, wsPath] = portText.trim().split("\n");
    ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
    await new Promise((resolve, reject) => { ws.once("open", resolve); ws.once("error", reject); });
    let seq = 0;
    const pending = new Map();
    ws.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (!message.id || !pending.has(message.id)) return;
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    });
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    await send("Runtime.enable", {}, sessionId);
    await send("Page.enable", {}, sessionId);
    await send("Page.navigate", { url: pathToFileURL(file).href }, sessionId);
    let text = "";
    for (let i = 0; i < 200 && !text; i++) {
      const result = await send("Runtime.evaluate", {
        expression: "document.getElementById('test-results')?.textContent || ''", returnByValue: true,
      }, sessionId);
      text = result.result.value || "";
      if (!text) await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(text, "浏览器没有返回测试结果");
    await send("Browser.close").catch(() => {});
    return JSON.parse(text);
  } finally {
    ws?.close();
    if (proc.exitCode === null) proc.kill();
    await rm(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

test("会话三点菜单、全选与批量删除可走完整流程", { skip: !browser && "未找到 Chrome/Edge" }, async () => {
  const results = await runBrowser("manage");
  assert.ok(results.every((r) => r.ok), results.filter((r) => !r.ok).map((r) => r.error).join("；"));
});

test("模型二级页只显示该模型在模型 & API 中配置的思考档位", { skip: !browser && "未找到 Chrome/Edge" }, async () => {
  const results = await runBrowser("models");
  assert.ok(results.every((r) => r.ok), results.filter((r) => !r.ok).map((r) => r.error).join("；"));
});
