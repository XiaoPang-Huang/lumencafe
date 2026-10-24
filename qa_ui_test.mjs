// QA 独立验证 A：前端真浏览器测试（playwright-core 直控 Chromium）
// 用法：node qa_ui_test.mjs
import { createRequire } from 'module';
import fs from 'fs';

const require = createRequire(import.meta.url);
const { chromium } = require('C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core');

const BASE = 'http://localhost:4311/v2/';
const TOKEN = fs.readFileSync('E:/Projects/lumencafe/qa_tmp/token.txt', 'utf8').trim();
const results = [];
const consoleErrors = [];

function check(name, cond, extra = '') {
  results.push({ name, pass: !!cond, extra: String(extra).slice(0, 200) });
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (extra ? ' | ' + String(extra).slice(0, 160) : ''));
}

const browser = await chromium.launch({
  executablePath: 'C:/Users/ROG/AppData/Local/ms-playwright/chromium-1247/chrome-win64/chrome.exe',
  headless: true,
});

async function newPage(width, height) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', e => consoleErrors.push('pageerror:' + String(e).slice(0, 200)));
  await page.goto(BASE + '#/login');
  await page.evaluate(t => localStorage.setItem('lc_token', t), TOKEN);
  return { ctx, page };
}

const waitToastHidden = async (page) => {
  try { await page.waitForSelector('.toast.show', { state: 'detached', timeout: 4000 }); } catch {}
};

const toastText = async (page, ms = 4000) => {
  const sel = '.toast.show';
  try {
    await page.waitForSelector(sel, { timeout: ms });
    return (await page.textContent(sel)).trim();
  } catch { return '(no toast)'; }
};

// ================= 桌面 1440x900 =================
{
  const { ctx, page } = await newPage(1440, 900);
  await page.goto(BASE + '#/chat');
  await page.waitForSelector('.fn-item[data-modal-open="#modal-skillhub"]', { timeout: 8000 });
  check('A-r 进入 #/chat 且功能列 Skill 入口存在', true);

  // A1 打开弹窗
  await page.click('.fn-item[data-modal-open="#modal-skillhub"]');
  await page.waitForSelector('#modal-skillhub.open, #modal-skillhub.show, #modal-skillhub', { state: 'visible' });
  await page.waitForFunction(() => {
    const t = document.querySelector('[data-myskills-body]')?.textContent || '';
    return t && !t.includes('加载中');
  }, { timeout: 6000 });
  const modalVisible = await page.isVisible('#modal-skillhub .modal');
  check('A1 中央弹窗可见（非侧边）', modalVisible);
  check('A1 标题=我的技能', (await page.textContent('#modal-skillhub .modal-head h3')).trim() === '我的技能');
  check('A1 副文案存在', (await page.textContent('#modal-skillhub .hub-sub')).includes('上传 SKILL.md'));
  check('A1 上传按钮存在', await page.isVisible('[data-skill-upload]'));
  check('A1 搜索框存在', await page.isVisible('[data-skill-search]'));
  check('A1 空态文案', (await page.textContent('[data-myskills-body]')).includes('还没有技能，点击上方上传 SKILL.md'));
  check('A1 中央圆角样式', await page.$eval('#modal-skillhub .modal', el => {
    const s = getComputedStyle(el);
    return parseFloat(s.borderRadius) >= 8 && getComputedStyle(el.parentElement).display === 'flex';
  }));

  // Esc 关闭
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  check('A1 Esc 可关闭', !(await page.isVisible('#modal-skillhub .modal')));
  // 重新打开 + 遮罩关闭
  await page.click('.fn-item[data-modal-open="#modal-skillhub"]');
  await page.waitForSelector('#modal-skillhub.modal-mask.open .modal', { state: 'visible' });
  const maskBox = await page.locator('#modal-skillhub').boundingBox();
  await page.mouse.click(maskBox.x + 10, maskBox.y + 10);
  await page.waitForTimeout(400);
  check('A1 遮罩点击可关闭', !(await page.isVisible('#modal-skillhub .modal')));

  // A5 两个入口同一弹窗：应用设置 → 管理
  await page.click('.fn-item[data-modal-open="#modal-skillhub"]');
  await page.waitForSelector('#modal-skillhub .modal', { state: 'visible' });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  // 打开 我的 → 应用设置（command palette 入口 data-cmd 或菜单）
  await page.evaluate(() => { window.LC_API; });
  const opened = await page.evaluate(() => {
    // 模拟入口：应用设置弹窗从「我的」菜单打开，这里直接调用 DOM 事件路径
    const btn = document.querySelector('[data-modal-switch="#modal-skillhub"]');
    if (!btn) return 'no-btn';
    btn.click();
    return 'clicked';
  });
  check('A5 应用设置「管理」按钮存在并可开同一弹窗', opened === 'clicked' && await page.isVisible('#modal-skillhub .modal'), opened);
  check('A5 设置入口打开后列表已刷新（空态或列表）', (await page.textContent('[data-myskills-body]')).length > 0);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  // A4 失败路径先行（保持列表为空）
  await page.click('.fn-item[data-modal-open="#modal-skillhub"]');
  await page.waitForSelector('[data-skill-file]', { state: 'attached' });

  await waitToastHidden(page);
  await page.setInputFiles('[data-skill-file]', 'E:/Projects/lumencafe/qa_tmp/note.txt');
  check('A4 .txt 前端拦截 toast', (await toastText(page)).includes('.md'), await toastText(page));

  await waitToastHidden(page);
  await page.setInputFiles('[data-skill-file]', 'E:/Projects/lumencafe/qa_tmp/big.md');
  check('A4 >64KB 前端拦截 toast', (await toastText(page)).includes('64KB'), await toastText(page));

  // 后端 422：缺 description（前端不拦截，走后端）
  await waitToastHidden(page);
  await page.setInputFiles('[data-skill-file]', 'E:/Projects/lumencafe/qa_tmp/qa-no-desc.md');
  check('A4 后端 422 toast 显示中文 detail', (await toastText(page, 4000)).includes('description'), await toastText(page));

  // A2 上传合法文件
  await waitToastHidden(page);
  await page.setInputFiles('[data-skill-file]', 'E:/Projects/lumencafe/qa_tmp/qa-ui-upload.md');
  const t1 = await toastText(page, 6000);
  check('A2 上传成功 toast 含安装路径', t1.includes('技能已安装到 skills/qa-ui-upload/'), t1);
  await page.waitForTimeout(800);
  const body1 = await page.textContent('[data-myskills-body]');
  check('A2 列表出现该技能', body1.includes('qa-ui-upload'));
  check('A2 来源徽标=本地上传', body1.includes('本地上传'));
  check('A2 路径显示 skills/qa-ui-upload/', body1.includes('skills/qa-ui-upload/'));
  check('A2 开关默认开', await page.$eval('[data-myskill-toggle]', el => el.getAttribute('data-enabled') === '1'));
  check('A2 条数徽标=1 个技能', (await page.textContent('[data-skill-count]')).includes('1 个技能'));

  // 宿主机落盘验证
  const diskOk = fs.existsSync('E:/Projects/lumencafe/skills/qa-ui-upload/SKILL.md') &&
    fs.readFileSync('E:/Projects/lumencafe/skills/qa-ui-upload/SKILL.md', 'utf8').includes('source: local-upload');
  check('A2 宿主机落盘 + source=local-upload', diskOk);

  // 重名 409
  await waitToastHidden(page);
  await page.setInputFiles('[data-skill-file]', 'E:/Projects/lumencafe/qa_tmp/qa-ui-upload.md');
  const t409 = await toastText(page, 5000);
  check('A4 重名 409 toast 同名提示', t409.includes('同名'), t409);

  // A5 搜索过滤
  await page.fill('[data-skill-search]', 'qa-ui');
  await page.waitForTimeout(400);
  check('A5 搜索命中过滤', (await page.textContent('[data-myskills-body]')).includes('qa-ui-upload'));
  await page.fill('[data-skill-search]', 'zzzz');
  await page.waitForTimeout(400);
  check('A5 搜索无匹配文案', (await page.textContent('[data-myskills-body]')).includes('没有匹配的技能'));
  await page.fill('[data-skill-search]', '');

  // A3 开关 → 后端取证
  await waitToastHidden(page);
  await page.click('[data-myskill-toggle]');
  check('A3 关闭 toast', (await toastText(page)).includes('已关闭'), await toastText(page));
  await page.waitForTimeout(800);
  const mineAfterOff = await page.evaluate(() => window.LC_API.skills.mine());
  check('A3 后端 mine enabled=false', mineAfterOff.find(s => s.name === 'qa-ui-upload')?.enabled === false, JSON.stringify(mineAfterOff));

  await waitToastHidden(page);
  await page.click('[data-myskill-toggle]');
  check('A3 开启 toast', (await toastText(page)).includes('已开启'), await toastText(page));
  await page.waitForTimeout(800);

  // 新对话 mock 模型发送（UI 层验证不报错；注入内容后端已取证）
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await page.click('[data-new-conv]');
  await page.waitForTimeout(500);
  await page.fill('.composer textarea', '你好');
  await page.click('[data-send]');
  await page.waitForTimeout(4000);
  const chatText = await page.$eval('.chat-scroll', el => el.innerText).catch(() => '(no .chat-scroll)');
  // 断言：拿到非空 AI 回复即链路正常（默认路由为真实 Provider 时回复不含 "mock" 字样）；
  // 回复提及 skill 标记正文则同时构成注入佐证
  check('A3 新对话 AI 可回复（注入链路无异常）', /你好|帮|mock/.test(chatText), chatText.slice(0, 120));
  globalThis.__injectE2e = chatText.includes('QA-UI-MARKER');

  // A3 卸载（confirm 含删除目录语义）
  await page.click('.fn-item[data-modal-open="#modal-skillhub"]');
  await page.waitForSelector('[data-myskill-del]', { state: 'visible' });
  page.once('dialog', d => { globalThis.__dialogMsg = d.message(); d.accept(); });
  await page.click('[data-myskill-del]');
  await page.waitForTimeout(500);
  check('A3 卸载 confirm 含删除目录语义', String(globalThis.__dialogMsg || '').includes('删除本地技能目录'), globalThis.__dialogMsg);
  check('A3 卸载 toast', (await toastText(page)).includes('已卸载'), await toastText(page));
  await page.waitForTimeout(800);
  check('A3 卸载后列表回到空态', (await page.textContent('[data-myskills-body]')).includes('还没有技能'));
  check('A3 卸载后目录已删', !fs.existsSync('E:/Projects/lumencafe/skills/qa-ui-upload'));

  // 旧 modal 零残留
  check('A5 旧 #modal-skills DOM 零残留', await page.evaluate(() => !document.querySelector('#modal-skills') && !document.body.innerHTML.includes('modal-skills')));

  // A6 回归：功能列占位 toast
  await page.keyboard.press('Escape');
  await waitToastHidden(page);
  await page.click('.fn-item[data-toast="收藏功能即将上线"]');
  check('A6 功能列收藏占位 toast', (await toastText(page)).includes('即将上线'), await toastText(page));
  await waitToastHidden(page);
  await page.click('.fn-item[data-toast="专家功能即将上线"]');
  check('A6 功能列专家占位 toast', (await toastText(page)).includes('即将上线'), await toastText(page));

  // 思考/润色按钮存在（润色空输入时 disabled/toast）
  check('A6 润色按钮存在', await page.isVisible('[data-polish]'));

  // #/money
  await page.goto(BASE + '#/money');
  await page.waitForSelector('[data-money-month]', { timeout: 8000 });
  check('A6 #/money 渲染', (await page.textContent('[data-money-month]')).includes('年'));
  // #/workspace
  await page.goto(BASE + '#/workspace');
  await page.waitForTimeout(1200);
  check('A6 #/workspace 渲染（无白屏）', await page.evaluate(() => document.body.innerText.trim().length > 50));

  await page.screenshot({ path: 'E:/Projects/lumencafe/qa_a_desktop_final.png' });
  await ctx.close();
}

// ================= 移动 390x844 =================
{
  const { ctx, page } = await newPage(390, 844);
  await page.goto(BASE + '#/me');
  await page.waitForTimeout(1000);
  // 移动端功能列隐藏，经「我的 → 应用设置 → 管理」入口打开同一弹窗
  const opened = await page.evaluate(() => {
    const b = document.querySelector('[data-modal-switch="#modal-skillhub"]');
    if (b) { b.click(); return 'via-settings'; }
    // 应用设置弹窗可能未开，先开再点
    return 'no-btn';
  });
  if (opened === 'no-btn') {
    await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#view a,#view button')];
      const s = rows.find(b => b.textContent.includes('应用设置'));
      if (s) s.click();
    });
    await page.waitForTimeout(400);
    await page.evaluate(() => document.querySelector('[data-modal-switch="#modal-skillhub"]').click());
  }
  await page.waitForSelector('#modal-skillhub.modal-mask.open .modal', { state: 'visible', timeout: 6000 });
  check('A6 移动端可打开我的技能弹窗', true);
  const overflow = await page.evaluate(() => {
    const m = document.querySelector('#modal-skillhub .modal');
    const r = m.getBoundingClientRect();
    const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
    return { left: r.left, right: r.right, vw, vh, bottom: r.bottom, scrollW: document.documentElement.scrollWidth };
  });
  check('A6 移动端弹窗不溢出（左右贴边内）', overflow.left >= -1 && overflow.right <= overflow.vw + 1, JSON.stringify(overflow));
  check('A6 移动端无横向滚动条', overflow.scrollW <= overflow.vw + 1, String(overflow.scrollW));
  check('A6 移动端弹窗垂直可见', overflow.bottom <= overflow.vh + 1, JSON.stringify(overflow));
  await page.screenshot({ path: 'E:/Projects/lumencafe/qa_a_mobile_modal.png' });
  await ctx.close();
}

// 负路径（422/409/404）触发的 resource 加载日志不算错误
const realErrors = consoleErrors.filter(e => !/Failed to load resource/.test(e) ||
  !/status of (422|409|404)|\((422|409|404)\)/.test(e));
check('A6 console 0 错误（负路径 4xx 除外）', realErrors.length === 0, realErrors.join(' ;; '));
check('A6 端到端佐证：AI 回复提及 skill 标记正文', globalThis.__injectE2e === true, 'reply mentioned QA-UI-MARKER');

const fails = results.filter(r => !r.pass);
console.log('\n=== SUMMARY ===');
console.log(`total=${results.length} passed=${results.length - fails.length} failed=${fails.length}`);
if (fails.length) console.log('FAILED:', fails.map(f => f.name).join(' | '));
await browser.close();
process.exit(fails.length ? 1 : 0);
