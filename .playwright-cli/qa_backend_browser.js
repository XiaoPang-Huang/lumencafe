/* QA 后端接口真调（经浏览器 fetch，复用 lc_token） */
const { chromium } = require(String.raw`C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core`);

const API = 'http://localhost:8000';
const results = [];
function check(name, cond, detail) {
  results.push([name, !!cond]);
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : ' | ' + String(detail).slice(0, 250)));
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext()).newPage();
  await page.goto('http://localhost:4311/v2/');
  await page.fill('input[type="password"]', 'change-me-too');
  await page.click('button:has-text("进入咖啡馆")');
  await page.waitForTimeout(1500);
  check('login ok', await page.evaluate(() => location.hash) !== '#/login');

  const api = (method, path, body) => page.evaluate(async ([m, p, b]) => {
    const t = localStorage.getItem('lc_token');
    const r = await fetch('http://localhost:8000' + p, {
      method: m,
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + t },
      body: b ? JSON.stringify(b) : undefined,
    });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  }, [method, path, body]);

  // B1 catalog
  let r = await api('GET', '/skills/catalog');
  check('B1 catalog 200', r.status === 200, r.status);
  check('B1 catalog 5 mock', r.body && r.body.items.length === 5, JSON.stringify(r.body).slice(0, 150));
  check('B1 catalog installed=false', r.body.items.every(i => !i.installed));
  r = await api('GET', '/skills/catalog?q=' + encodeURIComponent('周报'));
  check('B1 search q=周报', r.status === 200 && r.body.items.length === 1 && r.body.items[0].name === '周报助手', JSON.stringify(r.body).slice(0, 150));

  // B1 install
  r = await api('POST', '/skills/install', { skillhub_id: 'mock-translation-polish' });
  check('B1 install 201', r.status === 201, JSON.stringify(r.body).slice(0, 200));
  check('B1 install path echo', r.body && r.body.path === 'skills/translation-polish/', JSON.stringify(r.body).slice(0, 200));
  check('B1 install source=skillhub', r.body && r.body.source === 'skillhub');
  r = await api('POST', '/skills/install', { skillhub_id: 'mock-translation-polish' });
  check('B1 reinstall 409', r.status === 409, r.status);
  r = await api('GET', '/skills/catalog');
  check('B1 catalog installed=true', r.body.items.filter(i => i.installed).length === 1);

  // B5 路径穿越
  r = await api('POST', '/skills/install', { skillhub_id: '../../etc' });
  check('B5 weird id 拒绝', r.status !== 201, r.status + ' ' + JSON.stringify(r.body).slice(0, 100));
  r = await api('POST', '/skills/install', { skillhub_id: '..%2f..%2fetc' });
  check('B5 encoded traversal 拒绝', r.status !== 201, r.status);

  // B1 mine
  r = await api('GET', '/skills/mine?app_id=chat');
  const mine = r.body || [];
  const m = Object.fromEntries(mine.map(x => [x.name, x]));
  check('B1 mine 200', r.status === 200, r.status);
  check('B1 mine source/path', m['translation-polish'] && m['translation-polish'].source === 'skillhub' && m['translation-polish'].path === 'skills/translation-polish/', JSON.stringify(mine).slice(0, 250));

  // B4 chat 注入（SSE 读取 system 不可见；验证 chat 200 且后端注入逻辑由 pytest 覆盖；此处验证开关影响 mine）
  r = await api('POST', '/chat', { app_id: 'chat', message: 'qa' });
  check('B1 chat 200', r.status === 200, r.status);

  // 开关
  const sid = m['translation-polish'].id;
  r = await api('PUT', '/skills/' + sid + '/enabled', { enabled: false });
  check('B4 disable 200', r.status === 200, r.status);
  r = await api('GET', '/skills/mine?app_id=chat');
  const off = r.body.find(x => x.name === 'translation-polish');
  check('B4 disabled reflected', off && off.enabled === false, JSON.stringify(off));
  r = await api('PUT', '/skills/' + sid + '/enabled', { enabled: true });
  check('B4 re-enable 200', r.status === 200, r.status);

  // B3 手工删目录 → 自动清理（用 page 所在宿主机文件系统由 Node 做）
  const fs = require('fs');
  const dir = 'E:/Projects/lumencafe/skills/translation-polish';
  fs.rmSync(dir, { recursive: true, force: true });
  r = await api('GET', '/skills/mine?app_id=chat');
  check('B3 orphan cleaned', !r.body.some(x => x.name === 'translation-polish'), JSON.stringify(r.body).slice(0, 200));

  // 重装 → 验证落盘 frontmatter → 正式卸载
  r = await api('POST', '/skills/install', { skillhub_id: 'mock-translation-polish' });
  check('B3 reinstall 201', r.status === 201, r.status + JSON.stringify(r.body).slice(0, 100));
  const md = fs.readFileSync(dir + '/SKILL.md', 'utf-8');
  const fm = md.split('---')[1] || '';
  check('B1 SKILL.md 落盘+四键', ['name:', 'description:', 'source:', 'version:'].every(k => fm.includes(k)) && fm.includes('skillhub:mock-translation-polish'), fm.slice(0, 200));

  r = await api('DELETE', '/skills/' + r.body.id);
  check('B4 uninstall 200', r.status === 200, r.status);
  check('B4 dir removed', !fs.existsSync(dir));
  r = await api('GET', '/skills/mine?app_id=chat');
  check('B4 gone from mine', !r.body.some(x => x.name === 'translation-polish'));

  // B2 本地包（由前端 QA 脚本已建；此处只读验证 + 不误删）
  const ldir = 'E:/Projects/lumencafe/skills/test-local';
  if (!fs.existsSync(ldir + '/SKILL.md')) {
    fs.mkdirSync(ldir, { recursive: true });
    fs.writeFileSync(ldir + '/SKILL.md', '---\nname: test-local\ndescription: QA 手工本地包\nsource: local:test-local\nversion: 0.1.0\n---\n\n【技能：本地测试】本地包正文。\n');
  }
  r = await api('GET', '/skills/mine?app_id=chat');
  const loc = r.body.find(x => x.name === 'test-local');
  check('B2 local in mine', loc && loc.source === 'local' && loc.id === 0 && loc.path === 'skills/test-local/', JSON.stringify(loc));
  r = await api('PUT', '/skills/0/enabled', { enabled: false });
  check('B2 local toggle 404', r.status === 404, r.status);
  r = await api('DELETE', '/skills/0');
  check('B2 local delete 404', r.status === 404, r.status);
  check('B2 local dir intact', fs.existsSync(ldir + '/SKILL.md'));

  // B4 限流（写 25 次，应出现 429）
  const codes = [];
  for (let i = 0; i < 25; i++) {
    const x = await api('PUT', '/skills/999/enabled', { enabled: true });
    codes.push(x.status);
  }
  check('B4 rate limit 429', codes.includes(429), JSON.stringify(codes.slice(-6)));

  await browser.close();
  console.log('\n==== SUMMARY ====');
  const fails = results.filter(x => !x[1]);
  console.log(`total=${results.length} pass=${results.length - fails.length} fail=${fails.length}`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('SCRIPT ERROR', e); process.exit(2); });
