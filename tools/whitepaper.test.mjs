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
  assert.equal(mermaidBlocks.length, 10, '全文必须保留十张 Mermaid 图（§06 两张架构图 + 八张时序图）');
  assert.equal(
    matches(secondHtml, /<svg\b[^>]*class="mermaid-svg"/g).length,
    10,
    '十张 Mermaid 图必须预渲染为内联 SVG',
  );
  assert.equal(
    matches(secondHtml, /<details class="diagram-source">/g).length,
    10,
    '十张图必须保留可查看的 Mermaid 源码',
  );
  assert.ok(secondHtml.includes('✅ 已实测验证（2026-11-11）'), '必须保留 chord 实测回填');
  assert.ok(secondHtml.includes('总体架构图：主请求链路（容器视图）'), '必须保留第一张图标题');
  assert.ok(secondHtml.includes('数据与运行边界（补充视图）'), '必须保留第二张图标题');
  assert.ok(secondHtml.includes('普通聊天时序图：保存确认后再生成（基础版）'), '必须保留普通聊天时序图标题');
  assert.ok(secondHtml.includes('总对话只读查询时序图：写操作在网关拒绝（方案 C 边界）'), '必须保留总对话只读查询时序图标题');
  assert.ok(secondHtml.includes('失败重试与草稿恢复时序图：三种状态全手动重试（基础版）'), '必须保留失败重试与草稿恢复时序图标题');
  assert.ok(secondHtml.includes('AI 记一笔时序图：先出草稿，点确认才入账（幂等）'), '必须保留 AI 记一笔时序图标题');
  assert.ok(secondHtml.includes('对话统计时序图：模型只出三条件，代码执行聚合（方案 C）'), '必须保留对话统计时序图标题');
  assert.ok(secondHtml.includes('论文下载解析时序图：pi agent 护栏内换源探索，MinerU 解析入库（慢活）'), '必须保留论文下载解析时序图标题');
  assert.ok(secondHtml.includes('单篇问答时序图：双路检索加云端重排，出处点回原文段落（block 级）'), '必须保留单篇问答时序图标题');
  assert.ok(secondHtml.includes('定时抓取推送时序图：每日早八点一轮，push_logs 幂等防重'), '必须保留定时抓取推送时序图标题');

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

test('每张 Mermaid 图源必须保留对应的拍板关键句（语义防回退断言）', () => {
  // 背景：2026-11-11 论文图验收曾发现「图内分支行为与拍板正文矛盾」（空轮不推送 vs
  // 「无命中也发」）。构建链路只能保证 MD↔HTML 同步与 Mermaid 语法有效，发现不了语义
  // 相悖；本测试是 AGENTS 规则「时序图语义须逐条比对拍板原文」的自动化另一半：
  // 每条断言直接引用拍板原文短句，图源一旦被改回旧口径，docs:test 立即变红。
  //
  // 断言对象是 Markdown 源中的 mermaid 块内容（不是 HTML），并按「块前最近的 ### 标题」
  // 定位到具体图块，避免全文 includes 造成假通过。
  const source = readFileSync(sourcePath, 'utf8');
  const diagramSources = new Map();
  for (const match of source.matchAll(/```mermaid\r?\n[\s\S]*?```/g)) {
    const before = source.slice(0, match.index);
    const headings = matches(before, /^###\s+(.+)$/gm);
    const title = headings.length > 0 ? headings.at(-1)[1].trim() : '(无标题)';
    diagramSources.set(title, match[0]);
  }
  assert.equal(diagramSources.size, 10, '应能按三级标题定位到全部十张图');

  /** Assert that the diagram under `title` contains the pinned decision phrase. */
  function assertDecisionPhrase(title, phrase, origin) {
    const block = diagramSources.get(title);
    assert.ok(block, `找不到标题为「${title}」的图源`);
    assert.ok(
      block.includes(phrase),
      `「${title}」图源必须保留拍板关键句「${phrase}」（拍板出处：${origin}）`,
    );
  }

  // §06 总体架构图 —— 网关默认拒绝（拍板原文见 §03 chord 能力「HTTP 默认拒绝」与 §04）
  assertDecisionPhrase(
    '总体架构图：主请求链路（容器视图）',
    '默认拒绝',
    '§03 chord 能力·HTTP 默认拒绝（401）/ §04',
  );

  // §06 数据与运行边界 —— Docker 沙箱第五步才启用（§12 白皮书原有内容，非拍板新增）；
  // 慢活三规矩之并发 1–2 与幂等（§10 慢活拍板）
  assertDecisionPhrase(
    '数据与运行边界（补充视图）',
    '第五步才启用 · 密钥留在主程序',
    '§12 危险动作怎么关起来·第五步再开 + 密钥只放主程序',
  );
  assertDecisionPhrase(
    '数据与运行边界（补充视图）',
    '并发 1–2 · 幂等',
    '§10 慢活三规矩：并发 1–2、任务幂等',
  );

  // §08 普通聊天时序图 —— 保存确认后才生成（「失败重试与输入草稿」拍板第 4 条：
  // 发送链路需明确用户消息已保存的确认）；停止后标记「已停止」（「停止与重新生成」拍板）
  assertDecisionPhrase(
    '普通聊天时序图：保存确认后再生成（基础版）',
    '用户消息保存确认',
    '§08 失败重试与输入草稿·手动重试与链路确认（2026-11-11）',
  );
  assertDecisionPhrase(
    '普通聊天时序图：保存确认后再生成（基础版）',
    '标记“已停止”',
    '§08 停止与重新生成（2026-11-11）',
  );

  // §08 失败重试时序图 —— 全部手动重试、不自动重试（「失败重试与输入草稿」拍板第 4 条）
  assertDecisionPhrase(
    '失败重试与草稿恢复时序图：三种状态全手动重试（基础版）',
    '所有重试都由用户点击触发，不自动重试',
    '§08 失败重试与输入草稿·手动重试（2026-11-11）',
  );

  // §08 AI 记一笔时序图 —— 解析只出草稿、点确认才入账（「AI 记一笔」拍板：
  // 不做高置信度直接入账）
  assertDecisionPhrase(
    'AI 记一笔时序图：先出草稿，点确认才入账（幂等）',
    '返回草稿，此时不入账',
    '§08 AI 记一笔（2026-11-11）',
  );

  // §08 对话统计时序图 —— 模型只出参数不写 SQL（「对话统计查询边界」拍板：
  // 不让模型自己写 SQL）；家庭账本可查范围（「家庭账本」拍板第 3 条：
  // 配偶私人账不在可查范围）
  assertDecisionPhrase(
    '对话统计时序图：模型只出三条件，代码执行聚合（方案 C）',
    '模型只出参数，不写 SQL、不直接接触账本数据',
    '§08 对话统计查询边界（2026-11-11）',
  );
  assertDecisionPhrase(
    '对话统计时序图：模型只出三条件，代码执行聚合（方案 C）',
    '配偶的私人账不在可查范围内，越界一律拒',
    '§08 家庭账本·统计视图边界（2026-11-11）',
  );

  // §08 论文下载解析时序图 —— 换源顺序由 agent 自主决定（§15-3 修订拍板：
  // 废除定死源顺序，pi agent 探索 + 三重硬护栏；候选源 = 原型 5 源）
  assertDecisionPhrase(
    '论文下载解析时序图：pi agent 护栏内换源探索，MinerU 解析入库（慢活）',
    '顺序由 agent 自主决定',
    '§15-3 论文下载探索源清单修订拍板（2026-11-11）',
  );
  assertDecisionPhrase(
    '论文下载解析时序图：pi agent 护栏内换源探索，MinerU 解析入库（慢活）',
    '三重护栏计数：≤5 源 · ≤10 步工具调用 · token 预算封顶',
    '§08 下载引擎与止损·三重硬护栏（2026-11-11）',
  );

  // §08 单篇问答时序图 —— 检索为空不编造（语义源头是 §11 RAG 定义「不凭记忆瞎编」；
  // §08 问答入口与出处拍板只覆盖单篇范围与出处粒度）
  assertDecisionPhrase(
    '单篇问答时序图：双路检索加云端重排，出处点回原文段落（block 级）',
    '检索为空就直说「没找到相关段落」，不编造',
    '§11 RAG 定义·不凭记忆瞎编（§08 问答拍板仅覆盖单篇范围与出处粒度）',
  );

  // §08 定时抓取推送时序图 —— 空轮也推「今日无新论文」（「推送频率」拍板：
  // 无命中也发「今日无新论文」；Round 1 阻塞级缺陷即此句曾被画反）
  assertDecisionPhrase(
    '定时抓取推送时序图：每日早八点一轮，push_logs 幂等防重',
    '推送「今日无新论文」',
    '§08 推送频率·无命中也发（2026-11-11）',
  );

  // §09 总对话只读查询时序图 —— 网关调用前复核（§09 派生硬规矩：
  // 总对话挂的应用工具一律只读）
  assertDecisionPhrase(
    '总对话只读查询时序图：写操作在网关拒绝（方案 C 边界）',
    '调用前复核身份、角色和只读权限',
    '§09 总对话只读硬规矩（方案 C）',
  );
});
