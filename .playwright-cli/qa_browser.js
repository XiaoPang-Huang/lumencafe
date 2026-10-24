/* QA 前端真浏览器验证：Skill 中央弹窗 + 文件夹库管理 + 对话注入端到端 + 回归 */
const { chromium } = require(String.raw`C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core`);

const BASE = 'http://localhost:4311/v2/';
const results = [];
function check(name, cond, detail) {
  results.push([name, !!cond]);
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : ' | ' + String(detail).slice(0, 300)));
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));

  // 登录
  await page.goto(BASE);
  await page.waitForSelector('[data-route="login"] input, .login-card input, input[type="password"]', { timeout: 8000 }).catch(() => {});
  await page.fill('input[type="password"]', 'change-me-too');
  await page.click('button:has-text("进入咖啡馆")');
  await page.waitForTimeout(1500);
  check('login 成功跳转', await page.evaluate(() => location.hash) !== '#/login', await page.evaluate(() => location.hash));

  // A2: 收藏/专家/MCP 占位 toast（PRD v1.2 裁定：维持 toast，无 #modal-soon）
  await page.goto(BASE + '#/chat');
  await page.waitForTimeout(1200);
  check('chat 路由渲染功能列', await page.locator('.fn-col').count() === 1);
  await page.click('.fn-item:has-text("收藏")');
  await page.waitForTimeout(400);
  check('A2 收藏占位 toast', await page.locator('.toast, [class*="toast"]').count() > 0);
  check('A2 无 #modal-soon', await page.locator('#modal-soon').count() === 0);
  check('A2 .skill-panel 零残留(DOM)', await page.locator('.skill-panel, [data-skill-panel], [data-skill-mask]').count() === 0);

  // A1: Skill 中央弹窗
  await page.click('.fn-item:has-text("Skill")');
  await page.waitForTimeout(800);
  const modal = page.locator('#modal-skillhub');
  check('A1 弹窗打开', await modal.evaluate(el => el.classList.contains('open')));
  check('A1 中央弹窗 modal-lg（非侧边）', await modal.locator('.modal.modal-lg').count() === 1);
  check('A1 标题', (await modal.locator('.modal-head h3').innerText()).includes('SkillHub · 技能中心'));
  check('A1 接入标识', (await modal.locator('.hub-sub').innerText()).includes('SkillHub 技能开放平台'));
  const rows = modal.locator('.skill-row');
  check('A1 mock 5 个 skill', await rows.count() === 5, await rows.count());
  // 搜索过滤
  await modal.locator('[data-hub-search]').fill('周报');
  await page.waitForTimeout(600);
  check('A1 搜索过滤生效', await rows.count() === 1, await rows.count());
  await modal.locator('[data-hub-search]').fill('');
  await page.waitForTimeout(600);

  // A1: 安装 → 二次确认 → toast → 按钮变已安装
  page.on('dialog', d => d.accept());
  const row0 = rows.first();
  const firstName = (await row0.innerText()).split('\n')[0];
  await row0.locator('[data-skill-install]').click();
  await page.waitForTimeout(1000);
  check('A1 安装后 toast', await page.locator('.toast, [class*="toast"]').count() > 0);
  const rowAfter = rows.filter({ hasText: firstName }).first();
  check('A1 按钮变已安装', (await rowAfter.innerText()).includes('已安装'), await rowAfter.innerText());
  check('A1 catalog installed 徽标', await modal.locator('.skill-row', { hasText: '已安装' }).count() >= 1);

  // Esc 关闭
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  check('A1 Esc 可关闭', !(await modal.evaluate(el => el.classList.contains('open'))));

  // A4: 对话注入端到端（mock 模型）
  await page.fill('[data-chat-input], textarea, [contenteditable]', '用一句话介绍翻译润色技能').catch(() => {});
  // 找到输入框（按实际选择器兜底）
  const input = page.locator('[data-msg-input], [data-chat-input], .chat-input input, .chat-input textarea, textarea').first();
  await input.fill('用一句话介绍翻译润色技能');
  await page.click('[data-send], button:has-text("发送")').catch(async () => { await input.press('Enter'); });
  await page.waitForTimeout(4000);
  const chatText = await page.locator('.chat-main').innerText().catch(() => '');
  check('A4 对话收到回复', chatText.length > 20, chatText.slice(0, 100));

  // A3: 我的 → 应用设置 → 对话 → 已安装技能
  await page.goto(BASE + '#/settings'); // 兜底：直接找设置入口
  await page.waitForTimeout(800);
  // 通用做法：点击设置里的对话应用设置
  const settingsBody = await page.evaluate(() => {
    const el = document.querySelector('[data-myskills-body]');
    if (el) { el.scrollIntoView(); return true; } return false;
  });
  if (!settingsBody) {
    // 通过弹窗入口
    const opened = await page.evaluate(() => {
      const btn = document.querySelector('[data-modal-switch="#modal-skills"]');
      if (btn) { btn.click(); return true; } return false;
    });
    check('A3 管理弹窗入口存在', opened);
  }
  await page.waitForTimeout(800);
  const skillsModal = page.locator('#modal-skills');
  check('A3 管理弹窗打开', await skillsModal.evaluate(el => el.classList.contains('open')).catch(() => false));
  const bodyText = await skillsModal.locator('[data-myskills-body]').innerText().catch(() => '');
  check('A3 列表含来源徽标 SkillHub', bodyText.includes('SkillHub'), bodyText.slice(0, 200));
  check('A3 显示路径 skills/<slug>/', /skills\/[a-z0-9-]+\//.test(bodyText), bodyText.slice(0, 200));

  // 本地包条目（test-local 由后端脚本或此前步骤放入）
  check('A3 本地包只读条目', bodyText.includes('test-local') && bodyText.includes('本地') && bodyText.includes('只读'), bodyText.slice(0, 300));

  // 开关控制注入
  const toggle = skillsModal.locator('[data-myskill-toggle]').first();
  if (await toggle.count()) {
    await toggle.click();
    await page.waitForTimeout(500);
    const off = await toggle.getAttribute('data-enabled');
    check('A3 开关可关闭', off === '0', off);
    await toggle.click();
    await page.waitForTimeout(500);
  }

  // 卸载 confirm 文案
  let confirmText = '';
  page.once('dialog', d => { confirmText = d.message(); d.dismiss(); });
  const delBtn = skillsModal.locator('[data-myskill-del]').first();
  if (await delBtn.count()) {
    await delBtn.click();
    await page.waitForTimeout(500);
    check('A3 卸载 confirm 含删除本地技能目录', confirmText.includes('删除本地技能目录'), confirmText);
    page.on('dialog', d => d.accept());
    await delBtn.click();
    await page.waitForTimeout(800);
    const after = await skillsModal.locator('[data-myskills-body]').innerText();
    check('A3 卸载后 toast+条目消失', !after.includes(firstName), after.slice(0, 200));
  }
  await page.keyboard.press('Escape');

  // A5 回归：#/money #/workspace + 思考面板/润色
  await page.goto(BASE + '#/money');
  await page.waitForTimeout(800);
  check('A5 #/money 渲染', (await page.content()).length > 5000);
  await page.goto(BASE + '#/workspace');
  await page.waitForTimeout(800);
  check('A5 #/workspace 渲染', await page.locator('.ws-grid, [class*="ws"]').count() > 0 || (await page.content()).length > 5000);
  await page.goto(BASE + '#/chat');
  await page.waitForTimeout(1000);
  check('A5 思考面板/润色按钮存在', await page.locator('[data-reasoning], [data-polish]').count() > 0);

  check('A5 console 0 错误(桌面)', consoleErrors.length === 0, consoleErrors.join(' ;; ').slice(0, 400));
  await page.screenshot({ path: '.playwright-cli/qa_skill_desktop.png', fullPage: false });

  // 移动档 390x844
  await ctx.close();
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mp = await mctx.newPage();
  const mErr = [];
  mp.on('console', m => { if (m.type() === 'error') mErr.push(m.text()); });
  mp.on('pageerror', e => mErr.push('pageerror: ' + e.message));
  await mp.goto(BASE);
  await mp.fill('input[type="password"]', 'change-me-too');
  await mp.click('button:has-text("进入咖啡馆")');
  await mp.waitForTimeout(1500);
  await mp.goto(BASE + '#/chat');
  await mp.waitForTimeout(1200);
  await mp.click('.fn-item:has-text("Skill")').catch(async () => {
    await mp.locator('#conv-toggle, [data-open-conv]').first().click().catch(() => {});
    await mp.waitForTimeout(500);
    await mp.click('.fn-item:has-text("Skill")');
  });
  await mp.waitForTimeout(800);
  const mmodal = mp.locator('#modal-skillhub');
  check('M1 移动端弹窗打开', await mmodal.evaluate(el => el.classList.contains('open')).catch(() => false));
  const overflow = await mmodal.evaluate(el => {
    const r = el.querySelector('.modal').getBoundingClientRect();
    return { w: r.width, vw: window.innerWidth, h: r.height, vh: window.innerHeight };
  }).catch(() => null);
  check('M1 移动端弹窗不溢出(宽)', overflow && overflow.w <= overflow.vw, JSON.stringify(overflow));
  check('M1 移动端弹窗不溢出(高)', overflow && overflow.h <= overflow.vh, JSON.stringify(overflow));
  check('M1 console 0 错误(移动)', mErr.length === 0, mErr.join(' ;; ').slice(0, 300));
  await mp.screenshot({ path: '.playwright-cli/qa_skill_mobile.png' });

  await browser.close();
  console.log('\n==== SUMMARY ====');
  const fails = results.filter(r => !r[1]);
  console.log(`total=${results.length} pass=${results.length - fails.length} fail=${fails.length}`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
