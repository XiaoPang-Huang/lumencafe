/* QA A4 端到端注入：装→开(有片段)→关(消失)→卸(消失)，容器内 build_messages 取证 */
const { chromium } = require(String.raw`C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core`);
const { spawnSync } = require('child_process');
const results = [];
function check(name, cond, detail) {
  results.push([name, !!cond]);
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : ' | ' + String(detail).slice(0, 250)));
}
const READ_SYSTEM = `
import asyncio
from sqlalchemy import select
from app.db import SessionLocal
from app.models.user import User
from app.services import chat_service
async def main():
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username=='admin'))).scalar_one()
        msgs = await chat_service.build_messages(db, uid, 'chat', 0, 'x')
        print(msgs[0]['content'])
asyncio.run(main())
`;
function systemNow() {
  const r = spawnSync('docker', ['exec', 'lumencafe-api-1', 'python', '-c', READ_SYSTEM],
    { maxBuffer: 10 * 1024 * 1024, shell: false, encoding: 'utf-8' });
  if (r.error) { console.log('spawn err', r.error); return ''; }
  if (r.status !== 0) { console.log('docker stderr:', (r.stderr || '').slice(0, 300)); }
  return r.stdout || '';
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext()).newPage();
  await page.goto('http://localhost:4311/v2/');
  await page.fill('input[type="password"]', 'change-me-too');
  await page.click('button:has-text("进入咖啡馆")');
  await page.waitForTimeout(1200);
  const api = (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const t = localStorage.getItem('lc_token');
    const r = await fetch('http://localhost:8000' + p, {
      method: m, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + t },
      body: b ? JSON.stringify(b) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  }, [method, path, body]);

  let r = await api('POST', '/chat', { app_id: 'chat', message: '注入测试' });
  check('A4 chat 200(SSE)', r.status === 200, r.status);

  r = await api('POST', '/skills/install', { skillhub_id: 'mock-weekly-report' });
  check('A4 install 201', r.status === 201, JSON.stringify(r.body).slice(0, 150));
  const sid = r.body.id;

  let sys = systemNow();
  check('A4 开启时 system 含技能片段', sys.includes('【技能：周报助手】'), sys.slice(0, 200));

  await api('PUT', '/skills/' + sid + '/enabled', { enabled: false });
  sys = systemNow();
  check('A4 关闭后片段消失', !sys.includes('【技能：周报助手】'), sys.slice(0, 200));

  await api('PUT', '/skills/' + sid + '/enabled', { enabled: true });
  sys = systemNow();
  check('A4 再开启片段恢复', sys.includes('【技能：周报助手】'));

  // 改盘验证真相源（磁盘正文优先于 DB）
  const fs = require('fs');
  const p = 'E:/Projects/lumencafe/skills/weekly-report/SKILL.md';
  fs.writeFileSync(p, '---\nname: weekly-report\ndescription: d\nsource: skillhub:mock-weekly-report\nversion: 1.0.0\n---\n\n【技能：周报助手】QA 改写磁盘正文证据。\n');
  sys = systemNow();
  check('A4 读盘为真相源(改写后注入新正文)', sys.includes('QA 改写磁盘正文证据'), sys.slice(0, 200));

  r = await api('DELETE', '/skills/' + sid);
  check('A4 uninstall 200', r.status === 200, r.status);
  sys = systemNow();
  check('A4 卸载后片段消失', !sys.includes('【技能：周报助手】'), sys.slice(0, 200));
  check('A4 宿主目录已删', !fs.existsSync('E:/Projects/lumencafe/skills/weekly-report'));

  await browser.close();
  console.log('\n==== SUMMARY ====');
  const fails = results.filter(x => !x[1]);
  console.log(`total=${results.length} pass=${results.length - fails.length} fail=${fails.length}`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
