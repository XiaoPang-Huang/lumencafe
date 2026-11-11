import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer';

const projectRoot = fileURLToPath(new URL('../', import.meta.url));
const outputUrl = pathToFileURL(join(projectRoot, 'docs', '白皮书-v3.html')).href;
const screenshotDirectory = join(tmpdir(), 'lumencafe-whitepaper-verification');

async function assertPageHasNoHorizontalOverflow(page, label) {
  const metrics = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    mainWidth: document.querySelector('main').getBoundingClientRect().width,
  }));
  assert.ok(
    metrics.documentWidth <= metrics.viewportWidth,
    `${label} 出现页面级横向溢出：${JSON.stringify(metrics)}`,
  );
  assert.ok(
    metrics.mainWidth <= metrics.viewportWidth,
    `${label} 正文被目录挤压或撑宽：${JSON.stringify(metrics)}`,
  );
}

async function assertDiagramsUseNaturalScale(page, label) {
  const diagrams = await page.$$eval('.mermaid-svg', (nodes) =>
    nodes.map((svg) => {
      const viewBoxParts = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
      const naturalWidth = viewBoxParts[2];
      const actualWidth = svg.getBoundingClientRect().width;
      const matrix = svg.getScreenCTM();
      const scale = matrix ? Math.hypot(matrix.a, matrix.b) : actualWidth / naturalWidth;
      const labelNode = svg.querySelector('.nodeLabel') || svg.querySelector('text');
      const fontSize = labelNode ? parseFloat(getComputedStyle(labelNode).fontSize) : 16;
      return {
        naturalWidth,
        actualWidth,
        scale,
        fontSize,
        effectiveFontSize: fontSize * scale,
      };
    }),
  );

  assert.equal(diagrams.length, 5, `${label} 应有五张图（两张架构图 + 三张时序图）`);
  for (const [index, diagram] of diagrams.entries()) {
    assert.ok(
      Math.abs(diagram.actualWidth - diagram.naturalWidth) <= 1,
      `${label} 第 ${index + 1} 张图必须按自然宽度渲染：${JSON.stringify(diagram)}`,
    );
    assert.ok(
      diagram.effectiveFontSize >= 14 && diagram.effectiveFontSize <= 20,
      `${label} 第 ${index + 1} 张图标签有效字号应在 14–20px：${JSON.stringify(diagram)}`,
    );
  }
}

const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox'],
});

try {
  const page = await browser.newPage();
  const runtimeErrors = [];
  const externalRequests = [];
  page.on('pageerror', (error) => runtimeErrors.push(error.message));
  page.on('request', (request) => {
    if (/^https?:/.test(request.url())) externalRequests.push(request.url());
  });
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text());
  });

  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.goto(outputUrl, { waitUntil: 'load' });
  await page.waitForSelector('.mermaid-svg');
  assert.equal(await page.$$eval('main h2', (nodes) => nodes.length), 18);
  assert.equal(await page.$$eval('.mermaid-svg', (nodes) => nodes.length), 5);
  const diagramText = await page.$$eval('.mermaid-svg', (nodes) =>
    nodes.map((node) => ({ text: node.textContent, viewBox: node.getAttribute('viewBox') })),
  );
  for (const label of ['浏览器', '统一入口与权限', '云端大模型']) {
    assert.ok(diagramText[0].text.includes(label), `第一张 SVG 缺少可见标签：${label}`);
  }
  for (const label of ['SQLite', 'PostgreSQL + pgvector', 'MinerU 在线 API']) {
    assert.ok(diagramText[1].text.includes(label), `第二张 SVG 缺少可见标签：${label}`);
  }
  assert.ok(
    diagramText.every((diagram) => {
      const parts = (diagram.viewBox || '').trim().split(/\s+/).map(Number);
      return parts.length === 4 && parts.every(Number.isFinite) && parts[2] > 0 && parts[3] > 0;
    }),
    '五张 SVG 必须有有效的 viewBox 尺寸',
  );
  assert.equal(
    await page.$eval('#site-nav', (node) => getComputedStyle(node).position),
    'sticky',
    '桌面目录应 sticky 固定且独立滚动',
  );
  await assertPageHasNoHorizontalOverflow(page, '桌面布局');
  await assertDiagramsUseNaturalScale(page, '桌面布局');

  await page.evaluate(() => {
    const link = [...document.querySelectorAll('#whitepaper-toc a')].find((node) =>
      node.textContent.startsWith('06 整体分几层'),
    );
    if (!link) throw new Error('未找到 §06 目录链接');
    link.click();
  });
  try {
    await page.waitForFunction(() => {
      const active = document.querySelector('#whitepaper-toc a[aria-current="location"]');
      return active && active.getAttribute('href') === decodeURIComponent(window.location.hash);
    });
  } catch (error) {
    const state = await page.evaluate(() => {
      const target = document.getElementById(decodeURIComponent(window.location.hash).slice(1));
      const active = document.querySelector('#whitepaper-toc a[aria-current="location"]');
      return {
        hash: decodeURIComponent(window.location.hash),
        active: active?.getAttribute('href'),
        targetTop: target?.getBoundingClientRect().top,
        scrollY: window.scrollY,
      };
    });
    throw new Error(`桌面目录位置高亮未同步：${JSON.stringify(state)}`, { cause: error });
  }

  if (process.env.WHITEPAPER_SCREENSHOTS === '1') {
    await mkdir(screenshotDirectory, { recursive: true });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.screenshot({
      path: join(screenshotDirectory, 'whitepaper-desktop.png'),
      captureBeyondViewport: false,
    });
  }

  await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 1 });
  await page.goto(outputUrl, { waitUntil: 'load' });
  await assertPageHasNoHorizontalOverflow(page, '手机布局（目录收起）');
  await assertDiagramsUseNaturalScale(page, '手机布局');
  await page.click('#menu-toggle');
  await page.waitForFunction(() => {
    const drawer = document.querySelector('#site-nav');
    return drawer.classList.contains('is-open') && drawer.getBoundingClientRect().left >= -1;
  });
  assert.equal(await page.$eval('#menu-toggle', (node) => node.getAttribute('aria-expanded')), 'true');
  const drawerMetrics = await page.$eval('#site-nav', (node) => {
    const rect = node.getBoundingClientRect();
    return { left: rect.left, right: rect.right, width: rect.width };
  });
  assert.ok(
    drawerMetrics.left >= -1 && drawerMetrics.right <= 391,
    `手机目录应作为覆盖式抽屉展开：${JSON.stringify(drawerMetrics)}`,
  );
  await assertPageHasNoHorizontalOverflow(page, '手机布局（目录展开）');

  if (process.env.WHITEPAPER_SCREENSHOTS === '1') {
    await mkdir(screenshotDirectory, { recursive: true });
    await page.screenshot({
      path: join(screenshotDirectory, 'whitepaper-mobile-menu.png'),
      captureBeyondViewport: false,
    });
  }

  await page.evaluate(() => {
    const link = [...document.querySelectorAll('#whitepaper-toc a')].find((node) =>
      node.textContent.startsWith('06 整体分几层'),
    );
    if (!link) throw new Error('未找到手机端 §06 目录链接');
    link.click();
  });
  await page.waitForFunction(() =>
    document.querySelector('#menu-toggle').getAttribute('aria-expanded') === 'false',
  );
  assert.ok(await page.evaluate(() => window.location.hash.length > 1), '手机目录锚点应可跳转');
  await assertPageHasNoHorizontalOverflow(page, '手机布局（目录跳转后）');
  assert.deepEqual(runtimeErrors, [], `file:// 阅读不得产生运行时错误：${runtimeErrors.join('\n')}`);
  assert.deepEqual(externalRequests, [], `离线阅读不得发起外部请求：${externalRequests.join('\n')}`);

  console.log('浏览器验收通过：file://、桌面目录与锚点高亮、手机覆盖式抽屉、SVG 自然尺度与 14–20px 有效字号、零外部请求、页面无横向溢出。');
  if (process.env.WHITEPAPER_SCREENSHOTS === '1') {
    console.log(`验收截图：${screenshotDirectory}`);
  }
} finally {
  await browser.close();
}
