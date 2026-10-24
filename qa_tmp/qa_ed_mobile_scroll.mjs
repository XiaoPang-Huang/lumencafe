import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');
const BASE = 'http://localhost:4311/v2/?v=20261024a';
const TOKEN = fs.readFileSync('E:/Projects/lumencafe/qa_tmp/token_edward.txt', 'utf8').trim();
const browser = await chromium.launch({ executablePath: 'C:/Users/ROG/AppData/Local/ms-playwright/chromium-1247/chrome-win64/chrome.exe', headless: true });
const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
await page.goto(BASE + '#/login');
await page.evaluate(t => localStorage.setItem('lc_token', t), TOKEN);
await page.goto(BASE + '&m=2#/workspace');
await page.waitForFunction(() => document.querySelector('[data-ws-yexp]')?.textContent !== '—', null, { timeout: 10000 });
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(500);
const res = await page.evaluate(() => {
  const foot = document.querySelector('[data-ws-moneyfoot]').getBoundingClientRect();
  const nav = document.querySelector('.m-nav') || document.querySelector('.bottom-nav') || [...document.querySelectorAll('body > *')].find(e => { const s = getComputedStyle(e); return s.position === 'fixed' && s.bottom === '0px'; });
  const navR = nav ? nav.getBoundingClientRect() : null;
  return { footBottom: Math.round(foot.bottom), footTop: Math.round(foot.top), vh: innerHeight,
    navTop: navR ? Math.round(navR.top) : null, navVisible: !!navR,
    obscured: navR ? foot.bottom > navR.top : false };
});
console.log(JSON.stringify(res));
await page.screenshot({ path: 'E:/Projects/lumencafe/qa_tmp/qa_ed_mobile_bottom.png' });
await browser.close();
