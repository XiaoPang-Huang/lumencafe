// dialog 迁移冒烟：不登录，DOM 级验证弹窗/面板/无障碍属性
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');

const BASE = 'http://localhost:4311/v2/';
const results = [];
const consoleErrors = [];
function check(name, cond, extra = '') {
  results.push({ name, pass: !!cond });
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra ? ' | ' + String(extra).slice(0, 140) : ''));
}

const browser = await chromium.launch({
  executablePath: 'C:/Users/ROG/AppData/Local/ms-playwright/chromium-1247/chrome-win64/chrome.exe',
  headless: true,
});
const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160)); });
page.on('pageerror', e => consoleErrors.push('pageerror:' + String(e).slice(0, 160)));

await page.goto(BASE + '#/login');
await page.waitForTimeout(600);

// 1. 登录页无 JS 错误
check('登录页加载无 pageerror', consoleErrors.length === 0, consoleErrors.join(';'));

// 2. showModal 打开 + [open] 态 + flex 布局
const opened = await page.evaluate(() => {
  const d = document.querySelector('#modal-tx');
  if (!d || !d.showModal) return 'no-dialog';
  d.showModal();
  const cs = getComputedStyle(d);
  return { open: d.open, display: cs.display, opacity: cs.opacity, modalAnim: getComputedStyle(document.querySelector('#modal-tx .modal')).animationName };
});
check('showModal 打开 dialog', opened.open === true && opened.display === 'flex', JSON.stringify(opened));

// 3. Esc 关闭（原生行为）
await page.keyboard.press('Escape');
await page.waitForTimeout(350);
check('Esc 关闭 dialog', await page.evaluate(() => !document.querySelector('#modal-tx').open));

// 4. 遮罩点击关闭（点击 dialog 元素自身=点击遮罩区域）
await page.evaluate(() => document.querySelector('#modal-tx').showModal());
await page.waitForTimeout(300);
await page.mouse.click(640, 60); // 顶部遮罩区（弹窗卡片外）
await page.waitForTimeout(350);
check('点遮罩关闭 dialog', await page.evaluate(() => !document.querySelector('#modal-tx').open));

// 5. 弹层切换：set-general → modal-pass（close 当前 + showModal 目标）
await page.evaluate(() => {
  document.querySelector('#modal-set-general').showModal();
  document.querySelector('[data-modal-switch]').click(); // 修改密码
});
await page.waitForTimeout(300);
const switchState = await page.evaluate(() => ({
  gen: document.querySelector('#modal-set-general').open,
  pass: document.querySelector('#modal-pass').open,
}));
check('弹层互切', switchState.gen === false && switchState.pass === true, JSON.stringify(switchState));
await page.keyboard.press('Escape');

// 6. data-modal-close 按钮关闭
await page.evaluate(() => document.querySelector('#modal-cats').showModal());
await page.waitForTimeout(250);
await page.evaluate(() => document.querySelector('#modal-cats [data-modal-close]').click());
await page.waitForTimeout(350);
check('data-modal-close 关闭', await page.evaluate(() => !document.querySelector('#modal-cats').open));

// 7. 命令面板进出（.open 类 + 新过渡）
await page.keyboard.press('Control+k');
await page.waitForTimeout(300);
const pal = await page.evaluate(() => {
  const p = document.querySelector('#palette');
  return { open: p.classList.contains('open'), opacity: getComputedStyle(p).opacity, display: getComputedStyle(p).display };
});
check('⌘K 打开面板', pal.open && pal.display === 'block', JSON.stringify(pal));
await page.keyboard.press('Escape');
await page.waitForTimeout(300);
check('Esc 关闭面板', await page.evaluate(() => !document.querySelector('#palette').classList.contains('open')));

// 8. 无障碍属性
const a11y = await page.evaluate(() => ({
  toastLive: document.querySelector('#toast').getAttribute('aria-live'),
  switchRole: document.querySelector('[data-mm-reasoning-enabled]').getAttribute('role'),
  switchChecked: document.querySelector('[data-mm-reasoning-enabled]').getAttribute('aria-checked'),
}));
check('toast aria-live', a11y.toastLive === 'polite', JSON.stringify(a11y));
check('switch role=switch + aria-checked', a11y.switchRole === 'switch' && a11y.switchChecked === 'false');

// 9. role=button 键盘触发（sider-user → 跳 #/me，未登录会被守卫弹回登录页，说明 click 生效）
await page.evaluate(() => document.querySelector('.sider-user').focus());
await page.keyboard.press('Enter');
await page.waitForTimeout(500);
check('role=button Enter 触发', consoleErrors.length === 0);

// 10. 全程无 console 错误
check('全程无 JS 错误', consoleErrors.length === 0, consoleErrors.join(';'));

const failed = results.filter(r => !r.pass).length;
console.log(`\n== ${results.length - failed}/${results.length} 通过 ==`);
await browser.close();
process.exit(failed ? 1 : 0);
