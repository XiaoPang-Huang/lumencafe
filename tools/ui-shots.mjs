// UI 截图验证工具（开发用，不进运行时）：playwright-core + 系统 Edge（channel: msedge）
// 用法：node tools/ui-shots.mjs <输出目录> [--mobile] [--pages home,chat,...] [--modals]
// 页面：home/chat/money/papers/me/admin/login/reader（自动取首篇已解析论文）/chat-open（选中首个会话）
// --modals：额外截「我的-通用设置」「管理-添加用户」「记账-记一笔」三个中央弹窗
// 登录态：POST /api/auth/login 拿 chord-session cookie 注入 context（login 页用无 cookie 上下文）
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.LC_BASE ?? "http://127.0.0.1:8480";
const outDir = process.argv[2] ?? "shots";
const mobile = process.argv.includes("--mobile");
const withModals = process.argv.includes("--modals");
const pagesArg = (process.argv.find((a) => a.startsWith("--pages=")) ?? "").slice(8);
const PAGES = pagesArg ? pagesArg.split(",") : ["home", "chat", "money", "papers", "me", "admin"];

fs.mkdirSync(outDir, { recursive: true });

// 登录拿 cookie（账号见 .env 或默认引导号）
const user = process.env.LC_USER ?? "admin";
const pass = process.env.LC_PASS ?? "lumen2026";
const loginRes = await fetch(`${BASE}/api/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: user, password: pass }),
});
if (!loginRes.ok) { console.error("登录失败", loginRes.status); process.exit(1); }
const setCookie = loginRes.headers.getSetCookie().find((c) => c.startsWith("chord-session="));
const cookieValue = setCookie.split(";")[0].slice("chord-session=".length);
const authHeaders = { Cookie: `chord-session=${cookieValue}`, Accept: "application/json" };

// reader 路由需要真实论文 id：取首篇 phase=done 的条目
let readerHash = "#/papers";
try {
  const lib = await (await fetch(`${BASE}/api/papers/library`, { headers: authHeaders })).json();
  const done = (lib.items ?? []).find((i) => i.phase === "done");
  if (done) readerHash = `#/papers/${done.id}`;
} catch { /* 无论文则 reader 退化为库页 */ }

const browser = await chromium.launch({ channel: "msedge", headless: true });
const viewport = mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 };
const ctxOpts = { viewport, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile, locale: "zh-CN" };
const ctx = await browser.newContext(ctxOpts);
await ctx.addCookies([{ name: "chord-session", value: cookieValue, url: BASE }]);
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") errors.push(`console: ${m.text()}`); });

const routes = {
  home: "#/", chat: "#/chat", money: "#/money", papers: "#/papers",
  me: "#/me", admin: "#/admin", reader: readerHash, "chat-open": "#/chat",
};
const tag = mobile ? "m390" : "d1440";

// 溢出检测：文档宽度 vs 视口。排除两类「预期越界」：
// ① 关闭态抽屉（transform 移出屏外）② 横向滚动容器内的宽表格（容器滚、页面不滚）
async function checkOverflow(label) {
  const r = await page.evaluate(() => {
    const inScroller = (el) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox === "auto" || ox === "scroll" || ox === "hidden") return true;
      }
      return false;
    };
    const drawerClosed = (el) => {
      const side = el.closest(".chat-sidebar");
      return side && !side.classList.contains("open");
    };
    return {
      docW: document.documentElement.scrollWidth, winW: window.innerWidth,
      wide: [...document.querySelectorAll("*")].filter((el) => {
        const b = el.getBoundingClientRect();
        if (!(b.width > 0 && (b.right > window.innerWidth + 1 || b.left < -1))) return false;
        if (getComputedStyle(el).position === "fixed") return false;
        if (drawerClosed(el) || inScroller(el)) return false;
        return true;
      }).slice(0, 8).map((el) => `${el.tagName}.${el.className}`.slice(0, 80)),
    };
  });
  const bad = r.docW > r.winW || r.wide.length > 0;
  console.log(`${tag} ${label}: docW=${r.docW} winW=${r.winW}${r.docW > r.winW ? " ⚠️横向溢出" : ""}${bad ? " " + JSON.stringify(r.wide) : " ✅"}`);
  return r;
}

for (const name of PAGES) {
  if (name === "login") {
    // 登录页用无 cookie 上下文（有 cookie 会被后端重定向走）
    const anon = await browser.newContext(ctxOpts);
    const lp = await anon.newPage();
    lp.on("pageerror", (e) => errors.push(`pageerror(login): ${e.message}`));
    await lp.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await lp.waitForTimeout(900);
    await lp.screenshot({ path: path.join(outDir, `${tag}-login.png`) });
    const w = await lp.evaluate(() => ({ docW: document.documentElement.scrollWidth, winW: window.innerWidth }));
    console.log(`${tag} login: docW=${w.docW} winW=${w.winW}${w.docW > w.winW ? " ⚠️横向溢出" : " ✅"}`);
    await anon.close();
    continue;
  }
  await page.goto(`${BASE}/${routes[name] ?? "#/"}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700); // 等渲染与字体
  if (name === "chat-open") {
    // 移动端会话列表在抽屉里（屏外），先点菜单按钮打开抽屉再选会话
    if (mobile) { await page.locator("[data-menu]").click(); await page.waitForTimeout(400); }
    const first = page.locator(".chat-list [data-conv]").first();
    if (await first.count()) { await first.click(); await page.waitForTimeout(800); }
  }
  await page.screenshot({ path: path.join(outDir, `${tag}-${name}.png`) });
  await checkOverflow(name);
}

// 弹窗复验：三个代表性中央弹窗（概览式设置 / 长表单 / 表单+切换）
if (withModals) {
  const modalCases = [
    { page: "me", name: "modal-me-general", open: async () => { await page.locator('[data-domain="general"]').click(); } },
    { page: "admin", name: "modal-admin-adduser", open: async () => { await page.locator("[data-add-user]").click(); } },
    { page: "money", name: "modal-money-add", open: async () => { await page.locator("[data-add]").click(); } },
  ];
  for (const c of modalCases) {
    await page.goto(`${BASE}/${routes[c.page]}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(600);
    await c.open();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(outDir, `${tag}-${c.name}.png`) });
    const m = await page.evaluate(() => {
      const d = document.getElementById("modal");
      const b = d.getBoundingClientRect();
      const body = d.querySelector(".modal-body");
      return {
        open: d.open, w: Math.round(b.width), h: Math.round(b.height),
        inViewport: b.top >= 0 && b.bottom <= window.innerHeight + 1 && b.left >= 0 && b.right <= window.innerWidth + 1,
        bodyScrollable: body ? body.scrollHeight > body.clientHeight : false,
      };
    });
    console.log(`${tag} ${c.name}: open=${m.open} ${m.w}x${m.h} inViewport=${m.inViewport ? "✅" : "⚠️"} bodyScroll=${m.bodyScrollable}`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(250);
  }
}

// 侧栏固定验证（桌面）：滚动内容后侧栏位置不变
if (!mobile && PAGES.includes("money")) {
  await page.goto(`${BASE}/#/money`, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const before = await page.evaluate(() => document.getElementById("sideNav")?.getBoundingClientRect().top);
  await page.evaluate(() => { const sc = document.querySelector(".shell-col"); if (sc) sc.scrollTop = 400; else window.scrollTo(0, 400); });
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => document.getElementById("sideNav")?.getBoundingClientRect().top);
  console.log(`侧栏固定检查: before=${before} after=${after} ${before === after ? "✅" : "⚠️侧栏随滚动移动"}`);
}

console.log(errors.length ? `JS 错误:\n${errors.join("\n")}` : "无 JS 错误");
await browser.close();
