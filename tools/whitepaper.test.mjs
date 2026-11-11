import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const projectRoot = fileURLToPath(new URL('../', import.meta.url));
const generatorPath = join(projectRoot, 'tools', 'build-whitepaper.mjs');
const sourcePath = join(projectRoot, 'docs', '白皮书-v3.md');
const outputPath = join(projectRoot, 'docs', '白皮书-v3.html');

function runGenerator(args = []) {
  return spawnSync(process.execPath, [generatorPath, ...args], {
    cwd: projectRoot,
    encoding: 'utf8',
    env: { ...process.env },
  });
}

function sha256(content) {
  return createHash('sha256').update(content).digest('hex');
}

function matches(content, pattern) {
  return [...content.matchAll(pattern)];
}

function textOnly(html) {
  return html
    .replace(/<a\b[^>]*class="heading-anchor"[\s\S]*?<\/a>/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .trim();
}

test('从 Markdown 完整、确定性地生成可离线阅读的 HTML', () => {
  const sourceBefore = readFileSync(sourcePath, 'utf8');
  const firstBuild = runGenerator();
  assert.equal(
    firstBuild.status,
    0,
    `首次生成失败：\n${firstBuild.stdout}\n${firstBuild.stderr}`,
  );

  const firstHtml = readFileSync(outputPath, 'utf8');
  const secondBuild = runGenerator();
  assert.equal(
    secondBuild.status,
    0,
    `第二次生成失败：\n${secondBuild.stdout}\n${secondBuild.stderr}`,
  );
  const secondHtml = readFileSync(outputPath, 'utf8');
  assert.equal(sha256(secondHtml), sha256(firstHtml), '连续两次生成的字节必须一致');

  const check = runGenerator(['--check']);
  assert.equal(check.status, 0, `同步检查失败：\n${check.stdout}\n${check.stderr}`);
  assert.equal(readFileSync(sourcePath, 'utf8'), sourceBefore, '生成器不得改写 Markdown 源文件');

  const chapterHeadings = matches(sourceBefore, /^##\s+(.+)$/gm).map((match) => match[1]);
  const htmlChapters = matches(secondHtml, /<h2\b[^>]*>([\s\S]*?)<\/h2>/g).map((match) =>
    textOnly(match[1]),
  );
  assert.equal(chapterHeadings.length, 18, 'Markdown 应包含 00–17 共 18 个二级章节');
  assert.deepEqual(htmlChapters, chapterHeadings, 'HTML 必须按原顺序完整呈现 00–17 章节');

  const allSourceHeadings = matches(sourceBefore, /^#{2,3}\s+(.+)$/gm);
  const tocMatch = secondHtml.match(
    /<nav\b[^>]*id="whitepaper-toc"[^>]*>([\s\S]*?)<\/nav>/,
  );
  assert.ok(tocMatch, '必须生成白皮书目录');
  const tocLinks = matches(tocMatch[1], /href="#([^"]+)"/g).map((match) => match[1]);
  assert.equal(tocLinks.length, allSourceHeadings.length, '目录必须覆盖全部二级和三级标题');
  assert.equal(new Set(tocLinks).size, tocLinks.length, '目录锚点不得重复');
  for (const anchor of tocLinks) {
    assert.ok(
      secondHtml.includes(`id="${anchor}"`),
      `目录锚点 #${anchor} 必须存在对应标题`,
    );
  }

  const tableCount = matches(sourceBefore, /^\|(?:\s*:?-{3,}:?\s*\|)+$/gm).length;
  assert.ok(tableCount > 0, '源文档应包含表格');
  assert.equal(matches(secondHtml, /<table>/g).length, tableCount, '所有 Markdown 表格必须保留');
  assert.equal(
    matches(secondHtml, /<div class="table-wrap"/g).length,
    tableCount,
    '表格必须有独立的横向滚动容器',
  );

  const mermaidBlocks = matches(sourceBefore, /```mermaid\r?\n([\s\S]*?)```/g);
  assert.equal(mermaidBlocks.length, 7, '全文必须保留七张 Mermaid 图（§06 两张架构图 + 五张时序图）');
  assert.equal(
    matches(secondHtml, /<svg\b[^>]*class="mermaid-svg"/g).length,
    7,
    '七张 Mermaid 图必须预渲染为内联 SVG',
  );
  assert.equal(
    matches(secondHtml, /<details class="diagram-source">/g).length,
    7,
    '七张图必须保留可查看的 Mermaid 源码',
  );
  assert.ok(secondHtml.includes('✅ 已实测验证（2026-11-11）'), '必须保留 chord 实测回填');
  assert.ok(secondHtml.includes('总体架构图：主请求链路（容器视图）'), '必须保留第一张图标题');
  assert.ok(secondHtml.includes('数据与运行边界（补充视图）'), '必须保留第二张图标题');
  assert.ok(secondHtml.includes('普通聊天时序图：保存确认后再生成（基础版）'), '必须保留普通聊天时序图标题');
  assert.ok(secondHtml.includes('总对话只读查询时序图：写操作在网关拒绝（方案 C 边界）'), '必须保留总对话只读查询时序图标题');
  assert.ok(secondHtml.includes('失败重试与草稿恢复时序图：三种状态全手动重试（基础版）'), '必须保留失败重试与草稿恢复时序图标题');
  assert.ok(secondHtml.includes('AI 记一笔时序图：先出草稿，点确认才入账（幂等）'), '必须保留 AI 记一笔时序图标题');
  assert.ok(secondHtml.includes('对话统计时序图：模型只出三条件，代码执行聚合（方案 C）'), '必须保留对话统计时序图标题');

  const markdownLinks = matches(sourceBefore, /\[[^\]]+\]\((https?:\/\/[^)]+)\)/g).map(
    (match) => match[1],
  );
  for (const url of markdownLinks) {
    assert.ok(secondHtml.includes(`href="${url}"`), `外部链接必须保留：${url}`);
  }

  const ids = matches(secondHtml, /(?<![\w-])id="([^"]+)"/g).map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length, 'HTML 与内联 SVG 中的所有 id 必须唯一');
  assert.doesNotMatch(secondHtml, /<script\b[^>]*\bsrc=/i, '运行时不得加载外部脚本');
  assert.doesNotMatch(secondHtml, /<link\b[^>]*\bhref="https?:/i, '运行时不得加载外部样式');
  assert.ok(secondHtml.includes('<meta name="viewport"'), '必须包含移动端 viewport');
  assert.ok(secondHtml.includes('id="menu-toggle"'), '必须提供移动目录按钮');
  assert.ok(secondHtml.includes('aria-controls="site-nav"'), '移动目录按钮必须关联目录');
  assert.ok(secondHtml.includes('@media (max-width: 900px)'), '必须提供移动布局断点');
  assert.ok(secondHtml.includes('class="chapter-nav"'), '必须提供上一章/下一章导航');
  assert.ok(
    secondHtml.includes(`<meta name="source-sha256" content="${sha256(sourceBefore)}">`),
    '生成物必须记录 Markdown 源文件哈希以支持同步检查',
  );
});
