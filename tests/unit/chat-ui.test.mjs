// 对话页真实浏览器交互测试：会话批量管理、模型面板三级浮出（详情卡 + 思考档位菜单）。
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
          { id: "a/chat", name: "模型甲", provider: "a", modelId: "chat", thinking: "low", thinkingLevels: ["low", "high"], reasoning: true, supportsImages: true, contextWindow: 131072, maxOutputTokens: 8192, inputPrice: 2, outputPrice: 8 },
          { id: "b/chat", name: "模型乙", provider: "b", modelId: "chat", thinking: null, thinkingLevels: ["medium", "max"], reasoning: false, supportsImages: false, contextWindow: 65536, maxOutputTokens: null, inputPrice: null, outputPrice: null },
          { id: "c/chat", name: "模型丙", provider: "c", modelId: "chat", thinking: null, thinkingLevels: [], reasoning: false, supportsImages: false, contextWindow: null, maxOutputTokens: null, inputPrice: null, outputPrice: null },
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
        async function mountC1() {
          location.hash = "#/chat/c1";
          LC.views.chat.mount(document.getElementById("view"));
          await tick();
          click("[data-model-menu]");
        }
        async function testModelSwitch() {
          await mountC1();
          click('[data-pick-model="b/chat"]');
          await tick();
          const patches = calls.filter((c) => c.method === "PATCH");
          check(patches.some((c) => c.body?.model === "b/chat"), "点击模型主列表没有保存新模型");
          check(document.querySelector(".model-btn").textContent.includes("模型乙"), "模型已保存但输入区按钮仍显示旧模型");
          check(document.querySelector(".mm-item.on")?.dataset.pickModel === "b/chat", "主列表选中态没有切到模型乙");
        }
        /* 三级浮出交互（学 WorkBuddy hover 预览 / Open WebUI 侧栏浮卡 / Arco Cascader hover 展开）：
           主列表常驻 + 悬停浮出详情卡（跟随切换）+ 思考强度行浮出档位菜单（严格 thinkingLevels）。
           hover-intent 延时：进入 180ms、收起 300ms；测试等待 260ms 越过进入延时。 */
        const hover = async (sel, pointerType = "mouse") => {
          const node = document.querySelector(sel);
          check(node, "找不到元素 " + sel);
          node.dispatchEvent(new PointerEvent("pointerover", { bubbles: true, pointerType }));
          await new Promise((resolve) => setTimeout(resolve, 260));
        };
        async function testModels() {
          await mountC1(); // c1: model=a/chat, thinking=null
          // ① 悬停模型行：详情卡浮出且主列表仍在（不替换）
          check(!document.querySelector(".mm-detail"), "面板打开时不应默认浮出详情卡");
          await hover('[data-hover-model="a/chat"]');
          const detail = document.querySelector(".mm-detail");
          check(detail, "悬停模型行没有浮出详情卡");
          check(detail.dataset.flyModel === "a/chat", "浮出卡不是悬停的模型");
          check(document.querySelectorAll(".mm-list [data-hover-model]").length === 3, "详情卡浮出后主列表模型行丢失（替换式二级页回归）");
          check(document.querySelector(".mm-detail-title b")?.textContent === "模型甲", "详情卡标题不是模型甲");
          check(!document.querySelector(".mm-back"), "浮出式详情卡不应有「返回」按钮");
          // 价格/上下文如实透传（模型甲 inputPrice=2 / contextWindow=131072→128K）
          check(detail.textContent.includes("128K"), "详情卡没有展示上下文窗口");
          check(detail.textContent.includes("¥2"), "详情卡没有展示输入价格");
          // ② 悬停另一模型行：详情卡跟随切换
          await hover('[data-hover-model="b/chat"]');
          check(document.querySelector(".mm-detail")?.dataset.flyModel === "b/chat", "悬停另一模型行后详情卡没有跟随切换");
          check(document.querySelector(".mm-detail-title b")?.textContent === "模型乙", "切换后详情卡标题不对");
          // 模型乙缺配置价格不得造假
          check(!document.querySelector(".mm-detail").textContent.includes("¥2 / ¥8"), "模型乙没有配置的价格被虚构展示");
          // ③ 悬停「思考强度」行：浮出第三级档位菜单（严格 b=medium|max + 关闭，不补默认档）
          await hover(".mm-think-row");
          let lvFly = document.querySelector(".mm-levels");
          check(lvFly, "悬停思考强度行没有浮出档位菜单");
          let levelValues = [...lvFly.querySelectorAll("[data-pick-thinking]")].map((n) => n.dataset.pickThinking);
          check(levelValues.join("|") === "medium|max|off", "模型乙档位不是严格来自 thinkingLevels+关闭：" + levelValues.join("|"));
          check(document.querySelector(".mm-think-row").textContent.includes("默认"), "思考行没有默认强度语义");
          // ④ 切回模型甲：档位严格 low|high + 关闭；会话未显式选档时模型默认强度 low 高亮
          await hover('[data-hover-model="a/chat"]');
          await hover(".mm-think-row");
          lvFly = document.querySelector(".mm-levels");
          levelValues = [...lvFly.querySelectorAll("[data-pick-thinking]")].map((n) => n.dataset.pickThinking);
          check(levelValues.join("|") === "low|high|off", "模型甲档位集合不对（严格 low/high+关闭，不补默认档）：" + levelValues.join("|"));
          check(document.querySelector('[data-pick-thinking="low"]')?.classList.contains("on"), "会话未显式选档时默认强度 low 应高亮");
          // 点选档位：PATCH thinking=high + 当前项 ✓ + 思考行文案跟随
          document.querySelector('[data-pick-thinking="high"]').click();
          await tick();
          let patches = calls.filter((c) => c.method === "PATCH");
          check(patches.some((c) => c.body?.thinking === "high"), "点选档位没有 PATCH conversations.thinking=high");
          check(document.querySelector('[data-pick-thinking="high"]')?.classList.contains("on"), "档位选中态没有更新");
          check(document.querySelector(".mm-think-row").textContent.includes("高"), "思考行文案没有跟随所选档位");
          // 点「关闭」：PATCH "off"
          document.querySelector('[data-pick-thinking="off"]').click();
          await tick();
          patches = calls.filter((c) => c.method === "PATCH");
          check(patches.some((c) => c.body?.thinking === "off"), "点关闭档位没有 PATCH thinking=off");
          check(document.querySelector('[data-pick-thinking="off"]')?.classList.contains("on"), "关闭后选中态没有更新");
          // 无 thinkingLevels 的模型（丙）：思考行不可用态、不浮档位菜单
          await hover('[data-hover-model="c/chat"]');
          check(document.querySelector(".mm-level-empty"), "未配置思考档位的模型没有不可用说明");
          check(!document.querySelector(".mm-think-row"), "未配置思考档位的模型不应出现可悬停档位入口");
          const saved = calls.length;
          document.querySelector(".mm-detail").dispatchEvent(new PointerEvent("pointerover", { bubbles: true, pointerType: "mouse" }));
          await tick();
          check(!document.querySelector(".mm-levels") && calls.length === saved, "悬停详情卡（无思考行）不应浮出档位菜单");
          // ⑤ 触屏（无 hover 设备）：pointerover 不浮卡，点箭头浮卡、点档位保存。
          //    经会话切换走真实路径（不重复 mount，防监听器叠加）。c2 未选模型 = 默认甲。
          click('[data-conv="c2"]');
          await tick();
          click("[data-model-menu]");
          await hover('[data-hover-model="a/chat"]', "touch");
          check(!document.querySelector(".mm-detail"), "触屏 pointerover 被误当成桌面 hover 浮出详情卡");
          document.querySelector('[data-exp-model="a/chat"]').click();
          await tick();
          check(document.querySelector(".mm-detail")?.dataset.flyModel === "a/chat", "触屏点击箭头没有浮出详情卡");
          document.querySelector(".mm-think-row").click();
          await tick();
          check(document.querySelector(".mm-levels"), "触屏点思考行没有浮出档位菜单");
          document.querySelector('[data-pick-thinking="high"]').click();
          await tick();
          const tp = calls.filter((c) => c.method === "PATCH" && c.url.includes("/c2"));
          check(tp.some((c) => c.body?.thinking === "high"), "触屏点档位没有保存 high");
          // ⑥ 主列表点选模型：会话/按钮/选中态同步 + 面板与详情卡一起收起（双端一致）
          click('[data-conv="c1"]');
          await tick();
          click("[data-model-menu]");
          await hover('[data-hover-model="b/chat"]');
          check(document.querySelector(".mm-detail"), "重开面板后悬停应浮出详情卡");
          click('[data-pick-model="b/chat"]');
          await tick();
          const sp = calls.filter((c) => c.method === "PATCH" && c.url.includes("/c1"));
          check(sp.some((c) => c.body?.model === "b/chat"), "主列表点选模型没有保存");
          check(document.querySelector(".model-btn").textContent.includes("模型乙"), "点选模型后输入区按钮仍显示旧模型");
          check(document.querySelector(".mm-item.on")?.dataset.pickModel === "b/chat", "主列表选中态没有同步");
          // 注：面板收起后 DOM 隐藏但仍在视图内，选中态断言先于关闭完成 renderModelMenu 已重绘；
          // 若面板重开则选中态可见——重开验证：
          check(document.querySelector(".model-menu").hidden, "点选模型后面板没有收起（下拉选择惯例：选完即关）");
          check(!document.body.querySelector(".mm-fly"), "面板收起后 body 残留详情卡浮层");
          click("[data-model-menu]");
          check(document.querySelector(".mm-item.on")?.dataset.pickModel === "b/chat", "重开面板后主列表选中态仍是旧模型");
          // ⑦ hover-intent：从主列表移入详情卡不意外关闭
          await hover('[data-hover-model="a/chat"]');
          document.querySelector(".mm-detail").dispatchEvent(new PointerEvent("pointerover", { bubbles: true, pointerType: "mouse" }));
          check(!document.querySelector(".model-menu").hidden && document.querySelector(".mm-detail"), "移入详情卡后面板意外关闭");
          // ⑧ 跨模型档位语义锁定：在另一模型浮卡里点档位 = 同时保存该模型（PATCH model+thinking）
          await hover(".mm-think-row"); // 打开模型甲档位菜单（当前会话模型已是乙 → 跨模型）
          document.querySelector('[data-pick-thinking="low"]').click();
          await tick();
          const xp = calls.filter((c) => c.method === "PATCH" && c.url.includes("/c1"));
          check(xp.some((c) => c.body?.model === "a/chat"), "跨模型浮卡点档位没有同时切换并保存模型");
          check(xp.some((c) => c.body?.thinking === "low"), "跨模型点档位没有保存所选思考档位");
        }
        (async () => {
          if (${JSON.stringify(caseName)} === "manage") await record("会话批量管理", testManage);
          else if (${JSON.stringify(caseName)} === "switch") await record("模型主列表切换", testModelSwitch);
          else await record("模型二级思考开关", testModels);
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

test("模型主列表切换会同步保存并更新输入区模型按钮", { skip: !browser && "未找到 Chrome/Edge" }, async () => {
  const results = await runBrowser("switch");
  assert.ok(results.every((r) => r.ok), results.filter((r) => !r.ok).map((r) => r.error).join("；"));
});

test("模型面板三级浮出支持桌面 hover 跟随切换、触屏点击与档位保存", { skip: !browser && "未找到 Chrome/Edge" }, async () => {
  const results = await runBrowser("models");
  assert.ok(results.every((r) => r.ok), results.filter((r) => !r.ok).map((r) => r.error).join("；"));
});
