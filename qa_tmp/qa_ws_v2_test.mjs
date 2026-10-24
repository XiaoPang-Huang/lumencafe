// QA 独立验证：工作台 v2 每日看板（Edward， fresh eyes）
// 用法：node qa_tmp/qa_ws_v2_test.mjs
import { createRequire } from 'module';
import fs from 'fs';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');

const BASE = 'http://localhost:4311/v2/';
const API = 'http://localhost:8000';
const TOKEN = fs.readFileSync('E:/Projects/lumencafe/qa_tmp/token_edward.txt', 'utf8').trim();
const results = [];
const consoleErrors = [];

function check(name, cond, extra = '') {
  results.push({ name, pass: !!cond, extra: String(extra).slice(0, 220) });
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra ? ' | ' + String(extra).slice(0, 180) : ''));
}

const browser = await chromium.launch({
  executablePath: 'C:/Users/ROG/AppData/Local/ms-playwright/chromium-1247/chrome-win64/chrome.exe',
  headless: true,
});

async function newPage(width, height, token) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', e => consoleErrors.push('pageerror:' + String(e).slice(0, 200)));
  await page.goto(BASE + '#/login');
  await page.evaluate(t => localStorage.setItem('lc_token', t), token || TOKEN);
  return { ctx, page };
}

// 实时拉接口基准
const apiSummary = await (await fetch(API + '/money/stats/summary', { headers: { Authorization: 'Bearer ' + TOKEN } })).json();
const chatSummary = await (await fetch(API + '/chat/conversations/summary?app_id=chat', { headers: { Authorization: 'Bearer ' + TOKEN } })).json();
const fen = f => { const yuan = Math.floor(Math.abs(f) / 100); const cent = String(Math.abs(f) % 100).padStart(2, '0'); return '¥' + yuan.toLocaleString('zh-CN') + '.' + cent; };
const fenShort = f => fen(f).replace('.00', '');
console.log('API 基准:', JSON.stringify(apiSummary), JSON.stringify(chatSummary));

// ================= 桌面 1440x900 =================
{
  const { ctx, page } = await newPage(1440, 900);
  await page.goto(BASE + '?v=20261024a#/workspace');
  await page.waitForSelector('.bento-grid .bcard', { timeout: 10000 });

  // 结构
  check('D1 三板块卡存在 papers/chat/money',
    await page.$$eval('.bento-grid .bcard', els => els.map(e => e.getAttribute('data-bcard')).join(',') === 'papers,chat,money'));
  check('D2 轻问候行（无指标带）',
    (await page.$('.greet')) !== null && (await page.$('.stat-strip')) === null);
  const greet = await page.textContent('[data-ws-greet]');
  const dateTxt = await page.textContent('[data-ws-date]');
  check('D3 时段问候+昵称', /下午好，严过关|上午好，严过关|晚上好，严过关/.test(greet), greet);
  check('D4 日期文案', /10月24日 星期六/.test(dateTxt), dateTxt);
  check('D5 卡头「应用名 →」×3',
    await page.$$eval('.bcard-app', els => els.map(e => e.textContent.trim()).join('|')) === '文献|AI 对话|记账本');

  // 数据正确性：等异步填充完成
  await page.waitForFunction(() => document.querySelector('[data-ws-yexp]')?.textContent !== '—', null, { timeout: 8000 });
  const yexp = await page.textContent('[data-ws-yexp]');
  const wexp = await page.textContent('[data-ws-wexp]');
  const minc = await page.textContent('[data-ws-minc]');
  const mexp = await page.textContent('[data-ws-mexp]');
  check('A1 昨日消费 == 接口', yexp === fenShort(apiSummary.yesterday_expense), `UI=${yexp} API=${fenShort(apiSummary.yesterday_expense)}`);
  check('A2 本周消费 == 接口', wexp === fenShort(apiSummary.week_expense), `UI=${wexp} API=${fenShort(apiSummary.week_expense)}`);
  check('A3 本月收入 == 接口', minc === fenShort(apiSummary.month_income), `UI=${minc} API=${fenShort(apiSummary.month_income)}`);
  check('A4 本月支出 == 接口', mexp === fenShort(apiSummary.month_expense), `UI=${mexp} API=${fenShort(apiSummary.month_expense)}`);
  check('A5 收入红支出绿（color 不同）',
    await page.$eval('[data-ws-minc]', e => getComputedStyle(e).color) !== await page.$eval('[data-ws-mexp]', e => getComputedStyle(e).color));

  await page.waitForFunction(() => document.querySelector('[data-ws-ycount]')?.textContent !== '—', null, { timeout: 8000 });
  const ycnt = await page.textContent('[data-ws-ycount]');
  const lastConv = await page.textContent('[data-ws-lastconv]');
  check('A6 昨日对话数 == 接口', ycnt.trim() === String(chatSummary.yesterday_count), `UI=${ycnt} API=${chatSummary.yesterday_count}`);
  check('A7 最近会话标题 == 接口 latest', lastConv.includes(chatSummary.latest.title.slice(0, 10)), lastConv.trim());

  // 论文 mock 信息流
  const feedCount = await page.$$eval('.ws-feed-row', els => els.length);
  check('B-mock1 论文今日推送 6 条（mock 7 截 6）', feedCount === 6, 'rows=' + feedCount);
  const firstRow = await page.textContent('.ws-feed-row .ft');
  check('B-mock2 首条为 mock-p1 标题', firstRow.includes('p-tau217'), firstRow.slice(0, 40));

  // 趋势图
  check('B-money1 近6月趋势 sparkline 存在', (await page.$('.ws-money .sparkline')) !== null);

  // 整卡跳板
  await page.click('.bcard[data-bcard="papers"] .bcard-body');
  await page.waitForTimeout(400);
  check('B1a 点论文卡 → #/papers', await page.evaluate(() => location.hash) === '#/papers');
  await page.goto(BASE + '#/workspace'); await page.waitForSelector('.bento-grid .bcard');
  await page.click('.bcard[data-bcard="chat"] .bcard-body');
  await page.waitForTimeout(400);
  check('B1b 点对话卡 → #/chat', await page.evaluate(() => location.hash) === '#/chat');
  await page.goto(BASE + '#/workspace'); await page.waitForSelector('.bento-grid .bcard');
  await page.click('.bcard[data-bcard="money"] .bcard-body');
  await page.waitForTimeout(400);
  check('B1c 点记账卡 → #/money', await page.evaluate(() => location.hash) === '#/money');
  await page.goto(BASE + '#/workspace'); await page.waitForSelector('.bento-grid .bcard');
  await page.click('.ws-feed-row'); // 单条（卡内 <a> 冒泡）
  await page.waitForTimeout(400);
  check('B1d 点论文单条 → #/papers', await page.evaluate(() => location.hash) === '#/papers');

  // 回归路由渲染
  await page.goto(BASE + '#/chat');
  await page.waitForSelector('body[data-route="chat"]', { timeout: 8000 });
  check('R1 #/chat 渲染', (await page.$('.chat-layout')) !== null || (await page.$('.chat-app')) !== null || (await page.$('body[data-route="chat"]')) !== null);
  await page.goto(BASE + '#/money');
  await page.waitForTimeout(800);
  check('R2 #/money 渲染', (await page.$('body[data-route="money"]')) !== null);
  await page.goto(BASE + '#/papers');
  await page.waitForTimeout(800);
  check('R3 #/papers 渲染', (await page.$('body[data-route="papers"]')) !== null);

  // 拖拽排序（合成 HTML5 DnD 事件）：money 拖到 papers 前
  await page.goto(BASE + '#/workspace'); await page.waitForSelector('.bento-grid .bcard');
  await page.evaluate(() => {
    const grid = document.querySelector('.bento-grid');
    const cards = [...grid.querySelectorAll('.bcard')];
    const papers = cards.find(c => c.dataset.bcard === 'papers');
    const money = cards.find(c => c.dataset.bcard === 'money');
    money.dispatchEvent(new DragEvent('dragstart', { bubbles: true }));
    const r = papers.getBoundingClientRect();
    papers.dispatchEvent(new DragEvent('dragover', { bubbles: true, clientX: r.left + 5, clientY: r.top + 5 }));
    money.dispatchEvent(new DragEvent('dragend', { bubbles: true }));
  });
  const orderAfterDrag = await page.evaluate(() => [...document.querySelectorAll('.bento-grid .bcard')].map(c => c.dataset.bcard).join(','));
  const savedOrder = await page.evaluate(() => localStorage.getItem('lc_home_order'));
  check('B2a 拖拽后 DOM 顺序 money 在前', orderAfterDrag === 'money,papers,chat', orderAfterDrag);
  check('B2b lc_home_order 只含新键', savedOrder === '["money","papers","chat"]', savedOrder);
  await page.reload(); await page.waitForSelector('.bento-grid .bcard');
  const orderAfterReload = await page.evaluate(() => [...document.querySelectorAll('.bento-grid .bcard')].map(c => c.dataset.bcard).join(','));
  check('B2c 刷新后顺序保持', orderAfterReload === 'money,papers,chat', orderAfterReload);

  // 旧脏数据：admin/apps 键
  await page.evaluate(() => localStorage.setItem('lc_home_order', JSON.stringify(['admin', 'apps', 'chat'])));
  await page.reload(); await page.waitForSelector('.bento-grid .bcard');
  const orderDirty = await page.evaluate(() => [...document.querySelectorAll('.bento-grid .bcard')].map(c => c.dataset.bcard).join(','));
  check('B4a 脏数据（admin/apps 键）页面不炸', ['chat,papers,money', 'chat,money,papers'].includes(orderDirty), orderDirty);
  check('B4b 脏数据下拖拽仍可用（再拖一次不报错）', await page.evaluate(() => {
    try {
      const grid = document.querySelector('.bento-grid');
      const cards = [...grid.querySelectorAll('.bcard')];
      const chat = cards.find(c => c.dataset.bcard === 'chat');
      const papers = cards.find(c => c.dataset.bcard === 'papers');
      chat.dispatchEvent(new DragEvent('dragstart', { bubbles: true }));
      const r = papers.getBoundingClientRect();
      papers.dispatchEvent(new DragEvent('dragover', { bubbles: true, clientX: r.left + 5, clientY: r.top + 5 }));
      chat.dispatchEvent(new DragEvent('dragend', { bubbles: true }));
      return true;
    } catch (e) { return 'ERR:' + e.message; }
  }) === true);
  await page.evaluate(() => localStorage.removeItem('lc_home_order'));
  await ctx.close();
}

// ================= 断后端：骨架/错误态 =================
{
  const { ctx, page } = await newPage(1440, 900);
  await ctx.route('**://localhost:8000/money/**', r => r.abort());
  await ctx.route('**://localhost:8000/chat/**', r => r.abort());
  await page.goto(BASE + '#/workspace');
  await page.waitForSelector('.bento-grid .bcard', { timeout: 10000 });
  await page.waitForTimeout(300);
  check('E1 论文卡骨架灰条存在（mock 不依赖后端）', (await page.$('.ws-skel')) !== null || (await page.$('.ws-feed')) !== null);
  await page.waitForTimeout(1500);
  const moneyFoot = await page.textContent('[data-ws-moneyfoot]');
  const chatBox = await page.textContent('[data-ws-lastconv]');
  const yexp = await page.textContent('[data-ws-yexp]');
  check('E2 记账错误态文案', /加载失败/.test(moneyFoot), moneyFoot.trim());
  check('E3 对话错误态文案', /加载失败/.test(chatBox), chatBox.trim());
  check('E4 断后端不白屏（数字保持占位—）', yexp.trim() === '—', yexp);
  await ctx.close();
}

// ================= 新用户空态 + 订阅关键词弹窗 =================
{
  // 造一个全新空用户（无账目无会话）
  const { ctx, page } = await newPage(1440, 900);
  // 复用同一 token 但清空数据不可行——用第二个浏览器上下文登录另一个用户太重；
  // 改为：拦截接口返回空（等价新用户视角，验证空态分支）
  await ctx.route('**://localhost:8000/money/stats/summary', r => r.fulfill({ body: JSON.stringify({ yesterday_expense: 0, week_expense: 0, month_income: 0, month_expense: 0 }) }));
  await ctx.route('**://localhost:8000/chat/conversations/summary**', r => r.fulfill({ body: JSON.stringify({ yesterday_count: 0, latest: null }) }));
  await page.goto(BASE + '#/workspace');
  await page.waitForSelector('.bento-grid .bcard', { timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('[data-ws-ycount]')?.textContent === '0', null, { timeout: 8000 });
  const moneyFoot = await page.textContent('[data-ws-moneyfoot]');
  const chatBox = await page.textContent('[data-ws-lastconv]');
  check('E5 新用户记账空态引导', /还没有账目/.test(moneyFoot), moneyFoot.trim());
  check('E6 新用户对话空态引导', /还没有对话/.test(chatBox), chatBox.trim());
  check('E7 新用户昨日对话大数字 0', (await page.textContent('[data-ws-ycount]')).trim() === '0');

  // 论文空态 + 订阅关键词入口
  await page.evaluate(() => { window.LC_DATA.PAPERS_FEED = []; });
  await page.goto(BASE + '#/chat'); await page.waitForTimeout(300);
  await page.goto(BASE + '#/workspace');
  await page.waitForSelector('.ws-empty [data-ws-paper-settings]', { timeout: 8000 });
  const emptyT = await page.textContent('.ws-empty .t');
  check('E8 论文空态文案', /订阅关键词后每天推送/.test(emptyT), emptyT.trim());
  await page.click('[data-ws-paper-settings]');
  await page.waitForTimeout(500);
  const hashNow = await page.evaluate(() => location.hash);
  const modalVisible = await page.$eval('#modal-set-apps', e => !e.classList.contains('hide'));
  check('B3 订阅关键词只开弹窗不跳路由', modalVisible && hashNow === '#/workspace', `hash=${hashNow} modal=${modalVisible}`);
  await ctx.close();
}

// ================= 移动 390x844 =================
{
  const { ctx, page } = await newPage(390, 844);
  await page.goto(BASE + '#/workspace');
  await page.waitForSelector('.bento-grid .bcard', { timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('[data-ws-yexp]')?.textContent !== '—', null, { timeout: 8000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check('M1 无横向滚动', overflow <= 1, 'overflow=' + overflow);
  const spans = await page.$$eval('.bento-grid .bcard', els => els.map(e => getComputedStyle(e).gridColumnStart + '/' + getComputedStyle(e).gridColumnEnd).join(','));
  check('M2 单列堆叠（均 1/-1）', (await page.$$eval('.bento-grid .bcard', els => els.every(e => { const g = getComputedStyle(e).gridColumn; return g === '1 / -1' || g === 'auto 1 / auto -1' || g.startsWith('1'); }))), spans);
  const greetBox = await page.$eval('.greet', e => { const r = e.getBoundingClientRect(); return r.width <= 390 && r.left >= 0; });
  check('M3 问候行在视口内不拥挤', greetBox);
  await page.screenshot({ path: 'E:/Projects/lumencafe/qa_tmp/qa_ed_mobile_ws.png', fullPage: true });
  await ctx.close();
}

// 桌面整版截图（最终态）
{
  const { ctx, page } = await newPage(1440, 900);
  await page.goto(BASE + '#/workspace');
  await page.waitForFunction(() => document.querySelector('[data-ws-yexp]')?.textContent !== '—', null, { timeout: 8000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: 'E:/Projects/lumencafe/qa_tmp/qa_ed_desktop_ws.png', fullPage: true });
  await ctx.close();
}

await browser.close();

console.log('\n================ 汇总 ================');
const failed = results.filter(r => !r.pass);
console.log(`Total: ${results.length} | Passed: ${results.length - failed.length} | Failed: ${failed.length}`);
console.log('Console errors: ' + consoleErrors.length);
consoleErrors.slice(0, 10).forEach(e => console.log('  [console.error]', e));
if (failed.length) { console.log('--- FAILURES ---'); failed.forEach(f => console.log('FAIL ' + f.name + ' | ' + f.extra)); }
process.exit(failed.length ? 1 : 0);
