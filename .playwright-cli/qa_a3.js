/* QA A3：我的→应用设置→对话→已安装技能（来源/路径/开关/卸载 confirm） */
const { chromium } = require(String.raw`C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core`);
const results = [];
function check(name, cond, detail) {
  results.push([name, !!cond]);
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : ' | ' + String(detail).slice(0, 250)));
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errs = [];
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('pageerror', e => errs.push(e.message));
  await page.goto('http://localhost:4311/v2/');
  await page.fill('input[type="password"]', 'change-me-too');
  await page.click('button:has-text("进入咖啡馆")');
  await page.waitForTimeout(1500);

  // 先装一个 skill（UI 路径）
  await page.goto('http://localhost:4311/v2/#/chat');
  await page.waitForTimeout(1000);
  await page.click('.fn-item:has-text("Skill")');
  await page.waitForTimeout(800);
  const modal = page.locator('#modal-skillhub');
  const row = modal.locator('.skill-row', { hasText: '代码审查' });
  const installBtn = row.locator('[data-skill-install]');
  page.once('dialog', d => d.accept());
  if (await installBtn.count()) { await installBtn.click(); await page.waitForTimeout(800); }
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  // 我的 → 应用设置 → 管理
  await page.goto('http://localhost:4311/v2/#/me');
  await page.waitForTimeout(800);
  await page.click('.me-item:has-text("应用设置")');
  await page.waitForTimeout(600);
  const setApps = page.locator('#modal-set-apps');
  check('A3 应用设置弹窗打开', await setApps.evaluate(el => el.classList.contains('open')));
  await setApps.locator('[data-modal-switch="#modal-skills"]').click();
  await page.waitForTimeout(800);
  const sk = page.locator('#modal-skills');
  check('A3 已安装技能弹窗打开', await sk.evaluate(el => el.classList.contains('open')));
  const body = await sk.locator('[data-myskills-body]').innerText();
  check('A3 来源徽标 SkillHub', body.includes('SkillHub'), body.slice(0, 300));
  check('A3 路径 skills/<slug>/', /skills\/[a-z0-9-]+\//.test(body), body.slice(0, 300));
  check('A3 本地包只读条目', body.includes('test-local') && body.includes('本地') && body.includes('只读'), body.slice(0, 400));

  // 开关
  const toggle = sk.locator('[data-myskill-toggle]').first();
  await toggle.click();
  await page.waitForTimeout(500);
  check('A3 开关关闭生效', (await toggle.getAttribute('data-enabled')) === '0');
  await toggle.click();
  await page.waitForTimeout(500);
  check('A3 开关重新开启', (await toggle.getAttribute('data-enabled')) === '1');

  // 卸载 confirm 文案（先 dismiss 看文案）
  let confirmText = '';
  page.once('dialog', d => { confirmText = d.message(); d.dismiss(); });
  await sk.locator('[data-myskill-del]').first().click();
  await page.waitForTimeout(500);
  check('A3 卸载 confirm 含「删除本地技能目录」', confirmText.includes('删除本地技能目录'), confirmText);

  // 确认卸载 → toast + 条目消失
  page.once('dialog', d => d.accept());
  await sk.locator('[data-myskill-del]').first().click();
  await page.waitForTimeout(900);
  const after = await sk.locator('[data-myskills-body]').innerText();
  check('A3 卸载后条目消失', !/code-review|代码审查/.test(after), after.slice(0, 300));
  check('A3 卸载 toast', await page.locator('.toast, [class*="toast"]').count() > 0);
  check('A3 console 0 错误', errs.length === 0, errs.join(';;').slice(0, 300));

  // 宿主目录也被删（B4 佐证）
  const fs = require('fs');
  check('A3 宿主 skills/code-review 目录已删', !fs.existsSync('E:/Projects/lumencafe/skills/code-review'));

  await page.screenshot({ path: '.playwright-cli/qa_a3_myskills.png' });
  await browser.close();
  console.log('\n==== SUMMARY ====');
  const fails = results.filter(x => !x[1]);
  console.log(`total=${results.length} pass=${results.length - fails.length} fail=${fails.length}`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
