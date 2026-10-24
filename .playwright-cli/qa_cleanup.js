const PW = String.raw`C:/Users/ROG/.workbuddy/binaries/node/versions/22.22.2-6/node_modules/@playwright/cli/node_modules/playwright-core`;
const { chromium } = require(PW);

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext()).newPage();
  await page.goto('http://localhost:4311/v2/');
  await page.fill('input[type="password"]', 'change-me-too');
  await page.click('button:has-text("进入咖啡馆")');
  await page.waitForTimeout(1200);

  async function api(method, path) {
    return page.evaluate(async (args) => {
      const m = args[0], p = args[1];
      const t = localStorage.getItem('lc_token');
      const r = await fetch('http://localhost:8000' + p, {
        method: m,
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + t }
      });
      let body = null;
      try { body = await r.json(); } catch (e) {}
      return { status: r.status, body: body };
    }, [method, path]);
  }

  const list = await api('GET', '/chat/conversations?app_id=chat');
  const convs = list.body || [];
  console.log('conversations count:', convs.length);
  for (const c of convs) {
    const d = await api('DELETE', '/chat/conversations/' + c.id + '?app_id=chat');
    console.log('deleted conv', c.id, 'status', d.status);
  }
  const mine = await api('GET', '/skills/mine?app_id=chat');
  console.log('skills mine:', JSON.stringify(mine.body));
  await browser.close();
}

main().catch(e => { console.error('ERR', e); process.exit(1); });
