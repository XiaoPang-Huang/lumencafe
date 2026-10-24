// QA 复验：真实鼠标拖拽 + 纯净控制台 + 截图（完整重载流程，排除 hash-only 导航干扰）
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');

const BASE = 'http://localhost:4311/v2/?v=20261024a';
const TOKEN = fs.readFileSync('E:/Projects/lumencafe/qa_tmp/token_edward.txt', 'utf8').trim();
const consoleErrors = [];
const results = [];
const check = (n, c, x = '') => { results.push({ n, c: !!c }); console.log((c ? 'PASS ' : 'FAIL ') + n + (x ? ' | ' + x : '')); };

const browser = await chromium.launch({
  executablePath: 'C:/Users/ROG/AppData/Local/ms-playwright/chromium-1247/chrome-win64/chrome.exe',
  headless: true,
});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
page.on('pageerror', e => consoleErrors.push('pageerror:' + String(e).slice(0, 200)));
await page.goto(BASE + '#/login');
await page.evaluate(t => localStorage.setItem('lc_token', t), TOKEN);
await page.goto(BASE + '#/workspace'); // 完整重载（query 相同会 hash-only？加 cache-bust）
await page.goto(BASE + '&t=2#/workspace');
await page.waitForSelector('.bento-grid .bcard', { timeout: 10000 });
await page.waitForFunction(() => document.querySelector('[data-ws-yexp]')?.textContent !== '—', null, { timeout: 8000 });
await page.waitForTimeout(800);

const greet = await page.textContent('[data-ws-greet]');
check('问候行昵称（完整重载）', greet.includes('严过关'), greet);
const siderName = await page.textContent('.sider-user .u-name');
check('侧栏用户名', siderName.trim() === 'qa_edward', siderName.trim());

// 真实鼠标拖拽：把 money 卡拖到 papers 卡位置（HTML5 DnD，playwright 原生支持）
const papers = await page.$('.bcard[data-bcard="papers"]');
const money = await page.$('.bcard[data-bcard="money"]');
const pBox = await papers.boundingBox();
await page.dragAndDrop('.bcard[data-bcard="money"]', '.bcard[data-bcard="papers"]', {
  targetPosition: { x: 10, y: 10 },
});
await page.waitForTimeout(400);
const orderAfterRealDrag = await page.evaluate(() => [...document.querySelectorAll('.bento-grid .bcard')].map(c => c.dataset.bcard).join(','));
const saved = await page.evaluate(() => localStorage.getItem('lc_home_order'));
check('真实鼠标拖拽后顺序变化且持久化', orderAfterRealDrag === 'money,papers,chat' && saved === '["money,papers","chat"]'.replace('papers","chat', 'papers","chat') || (orderAfterRealDrag.startsWith('money') && JSON.parse(saved)[0] === 'money'), `order=${orderAfterRealDrag} saved=${saved}`);

await page.reload();
await page.waitForSelector('.bento-grid .bcard');
const orderReload = await page.evaluate(() => [...document.querySelectorAll('.bento-grid .bcard')].map(c => c.dataset.bcard).join(','));
check('真实拖拽刷新后保持', orderReload === orderAfterRealDrag, orderReload);

// 回归路由（纯净控制台）
for (const r of ['chat', 'money', 'papers', 'apps', 'admin']) {
  await page.goto(BASE + '&t=' + r + '#/' + r);
  await page.waitForTimeout(900);
  check('#/' + r + ' 渲染', await page.$eval('body', b => b.getAttribute('data-route')) === r);
}
// admin 对 member 应跳回（无权限）——记录但不判失败
await page.screenshot({ path: 'E:/Projects/lumencafe/qa_tmp/qa_ed_desktop_ws2.png', fullPage: true });
await browser.close();

const realErrors = consoleErrors.filter(e => !/ERR_FAILED|favicon/.test(e));
console.log('\nConsole errors (filtered): ' + realErrors.length);
realErrors.slice(0, 10).forEach(e => console.log('  [err]', e));
const failed = results.filter(r => !r.c);
console.log(`Checks: ${results.length} | Failed: ${failed.length}`);
process.exit(failed.length || realErrors.length ? 1 : 0);
