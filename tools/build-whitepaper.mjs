import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';
import puppeteer from 'puppeteer';

const projectRoot = fileURLToPath(new URL('../', import.meta.url));
const sourcePath = join(projectRoot, 'docs', '白皮书-v3.md');
const outputPath = join(projectRoot, 'docs', '白皮书-v3.html');
const mermaidEntryPath = fileURLToPath(import.meta.resolve('mermaid'));
const mermaidBundlePath = join(dirname(mermaidEntryPath), 'mermaid.min.js');

/** Escape text for safe inclusion in HTML. */
function escapeHtml(value) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/** Preserve Mermaid's natural viewBox width so labels render at their configured size. */
function setNaturalDiagramSize(svg) {
  const openingTagMatch = svg.match(/<svg\b[^>]*>/);
  if (!openingTagMatch) throw new Error('Mermaid 输出缺少 SVG 起始标签');
  const openingTag = openingTagMatch[0];
  const viewBoxMatch = openingTag.match(/\bviewBox="([^"]+)"/);
  if (!viewBoxMatch) throw new Error('Mermaid 输出缺少 viewBox，无法确定自然尺寸');
  const viewBoxParts = viewBoxMatch[1].trim().split(/\s+/).map(Number);
  const naturalWidth = viewBoxParts[2];
  if (viewBoxParts.length !== 4 || !Number.isFinite(naturalWidth) || naturalWidth <= 0) {
    throw new Error(`Mermaid 输出包含无效 viewBox：${viewBoxMatch[1]}`);
  }

  let sizedOpeningTag = openingTag.replace(/<svg\b/, '<svg class="mermaid-svg"');
  if (/\bwidth="[^"]*"/.test(sizedOpeningTag)) {
    sizedOpeningTag = sizedOpeningTag.replace(/\bwidth="[^"]*"/, `width="${naturalWidth}"`);
  } else {
    sizedOpeningTag = sizedOpeningTag.replace(/>$/, ` width="${naturalWidth}">`);
  }
  return sizedOpeningTag + svg.slice(openingTag.length);
}

/** Return visible text from a Markdown inline token, including nested tokens. */
function inlineText(token) {
  if (!token.children || token.children.length === 0) {
    return token.type === 'softbreak' || token.type === 'hardbreak' ? ' ' : token.content;
  }
  return token.children.map((child) => inlineText(child)).join('');
}

/** Create readable Unicode slugs and deterministic suffixes for duplicate titles. */
function createSlugger() {
  const occurrences = new Map();
  return (title) => {
    const normalized = title
      .normalize('NFKC')
      .toLocaleLowerCase('zh-CN')
      .replace(/[^\p{Letter}\p{Number}\p{Mark}\s_-]/gu, '')
      .trim()
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-');
    const base = normalized || 'section';
    const count = (occurrences.get(base) || 0) + 1;
    occurrences.set(base, count);
    return count === 1 ? base : `${base}-${count}`;
  };
}

/** Build a nested two-level table of contents from h2 and h3 headings. */
function buildToc(headings) {
  const chapters = [];
  for (const heading of headings) {
    if (heading.level === 2) {
      chapters.push({ ...heading, children: [] });
    } else if (heading.level === 3 && chapters.length > 0) {
      chapters.at(-1).children.push(heading);
    }
  }

  const items = chapters
    .map((chapter) => {
      const children = chapter.children.length
        ? `<ol class="toc-children">${chapter.children
            .map(
              (child) =>
                `<li><a class="toc-link toc-link-child" href="#${child.id}" data-heading-id="${child.id}">${escapeHtml(child.title)}</a></li>`,
            )
            .join('')}</ol>`
        : '';
      return `<li class="toc-chapter"><a class="toc-link toc-link-chapter" href="#${chapter.id}" data-heading-id="${chapter.id}">${escapeHtml(chapter.title)}</a>${children}</li>`;
    })
    .join('');
  return `<ol class="toc-list">${items}</ol>`;
}

/** Render previous/next links without splitting the document into multiple pages. */
function buildChapterPager(chapters, chapterIndex) {
  const previous = chapters[chapterIndex - 1];
  const next = chapters[chapterIndex + 1];
  const previousLink = previous
    ? `<a class="chapter-nav-link chapter-nav-previous" href="#${previous.id}"><span class="chapter-nav-direction">← 上一章</span><span class="chapter-nav-title">${escapeHtml(previous.title)}</span></a>`
    : '<span class="chapter-nav-placeholder" aria-hidden="true"></span>';
  const nextLink = next
    ? `<a class="chapter-nav-link chapter-nav-next" href="#${next.id}"><span class="chapter-nav-direction">下一章 →</span><span class="chapter-nav-title">${escapeHtml(next.title)}</span></a>`
    : '<span class="chapter-nav-placeholder" aria-hidden="true"></span>';
  return `<nav class="chapter-nav" aria-label="章节翻页">${previousLink}${nextLink}</nav>`;
}

/** Create the Markdown parser and token transformations used by the generator. */
function createMarkdownParser() {
  const md = new MarkdownIt({
    html: false,
    linkify: true,
    typographer: false,
    langPrefix: 'language-',
  });

  md.core.ruler.push('whitepaper_heading_metadata', (state) => {
    const slug = createSlugger();
    state.env.headings = [];
    state.env.chapters = [];

    for (let index = 0; index < state.tokens.length; index += 1) {
      const token = state.tokens[index];
      if (token.type !== 'heading_open') continue;
      const level = Number(token.tag.slice(1));
      const inline = state.tokens[index + 1];
      const title = inlineText(inline).trim();
      const id = slug(title);
      token.attrSet('id', id);
      token.attrJoin('class', 'doc-heading');
      if (level === 2 || level === 3) {
        const heading = { id, title, level, line: token.map?.[0] ?? 0 };
        state.env.headings.push(heading);
        if (level === 2) state.env.chapters.push(heading);
      }
    }
  });

  md.core.ruler.push('whitepaper_chapter_sections', (state) => {
    const transformed = [];
    let chapterIndex = -1;
    const htmlToken = (content) => {
      const token = new state.Token('html_block', '', 0);
      token.content = content;
      return token;
    };

    for (const token of state.tokens) {
      if (token.type === 'heading_open' && token.tag === 'h2') {
        if (chapterIndex >= 0) {
          transformed.push(
            htmlToken(`${buildChapterPager(state.env.chapters, chapterIndex)}</section>`),
          );
        }
        chapterIndex += 1;
        const id = token.attrGet('id');
        transformed.push(
          htmlToken(`<section class="chapter" aria-labelledby="${id}" data-chapter="${chapterIndex}">`),
        );
      }
      transformed.push(token);
    }
    if (chapterIndex >= 0) {
      transformed.push(
        htmlToken(`${buildChapterPager(state.env.chapters, chapterIndex)}</section>`),
      );
    }
    state.tokens = transformed;
  });

  md.renderer.rules.heading_close = (tokens, index) => {
    const opening = tokens[index - 2];
    const id = opening.attrGet('id');
    const title = inlineText(tokens[index - 1]).trim();
    return `<a class="heading-anchor" href="#${id}" aria-label="链接到此标题：${escapeHtml(title)}"><span aria-hidden="true">#</span></a></${opening.tag}>`;
  };

  md.renderer.rules.fence = (tokens, index) => {
    const token = tokens[index];
    const language = token.info.trim().split(/\s+/)[0] || 'text';
    return `<figure class="code-block"><figcaption><span>代码</span><span>${escapeHtml(language)}</span></figcaption><pre tabindex="0"><code class="language-${escapeHtml(language)}">${md.utils.escapeHtml(token.content)}</code></pre></figure>`;
  };

  md.renderer.rules.table_open = () =>
    '<div class="table-wrap" role="region" aria-label="表格，可横向滚动" tabindex="0"><table>';
  md.renderer.rules.table_close = () => '</table></div>';

  md.renderer.rules.link_open = (tokens, index, options, env, self) => {
    const href = tokens[index].attrGet('href') || '';
    if (/^https?:\/\//.test(href)) {
      tokens[index].attrSet('target', '_blank');
      tokens[index].attrSet('rel', 'noopener noreferrer');
    }
    return self.renderToken(tokens, index, options);
  };

  return md;
}

/** Render Mermaid source blocks to stable, self-contained SVG in a build-time browser. */
async function renderMermaidDiagrams(tokens, headings) {
  const diagramTokens = tokens.filter(
    (token) => token.type === 'fence' && token.info.trim().split(/\s+/)[0] === 'mermaid',
  );
  if (diagramTokens.length === 0) return;
  if (!existsSync(mermaidBundlePath)) {
    throw new Error(`找不到 Mermaid 浏览器包：${mermaidBundlePath}。请先运行 npm --prefix=tools run docs:install。`);
  }

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1600, height: 1200, deviceScaleFactor: 1 });
    await page.setContent('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body></body></html>');
    await page.addScriptTag({ path: mermaidBundlePath });

    for (let index = 0; index < diagramTokens.length; index += 1) {
      const token = diagramTokens[index];
      const diagramId = `whitepaper-diagram-${index + 1}`;
      const heading = headings
        .filter((candidate) => candidate.line < (token.map?.[0] ?? 0))
        .at(-1);
      const title = heading?.title || `架构图 ${index + 1}`;
      const svg = await page.evaluate(
        async ({ id, source }) => {
          if (!window.mermaid) throw new Error('Mermaid 浏览器包未正确加载');
          window.mermaid.initialize({
            startOnLoad: false,
            securityLevel: 'strict',
            theme: 'neutral',
            deterministicIds: true,
            deterministicIDSeed: id,
            flowchart: {
              htmlLabels: true,
              curve: 'basis',
              useMaxWidth: false,
              nodeSpacing: 45,
              rankSpacing: 55,
            },
            themeVariables: {
              fontFamily: '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif',
              fontSize: '16px',
              primaryColor: '#f2f6ff',
              primaryTextColor: '#172033',
              primaryBorderColor: '#8ba7d8',
              lineColor: '#52627a',
              secondaryColor: '#f7f9fc',
              tertiaryColor: '#ffffff',
              clusterBkg: '#f8fafc',
              clusterBorder: '#b9c4d4',
              edgeLabelBackground: '#ffffff',
            },
          });
          const result = await window.mermaid.render(id, source);
          return result.svg;
        },
        { id: diagramId, source: token.content },
      );

      const responsiveSvg = setNaturalDiagramSize(svg);
      const sourceCode = escapeHtml(token.content);
      token.type = 'html_block';
      token.tag = '';
      token.nesting = 0;
      token.children = null;
      token.info = '';
      token.markup = '';
      token.content = `<figure class="diagram" aria-label="${escapeHtml(title)}"><figcaption class="diagram-caption"><span>${escapeHtml(title)}</span><span>图 ${index + 1} / ${diagramTokens.length}</span></figcaption><div class="diagram-viewport" role="img" aria-label="${escapeHtml(title)}；宽图可横向滚动" tabindex="0">${responsiveSvg}</div><details class="diagram-source"><summary>查看 Mermaid 源码</summary><pre tabindex="0"><code class="language-mermaid">${sourceCode}</code></pre></details></figure>`;
    }
  } finally {
    await browser.close();
  }
}

/** Return the complete single-file HTML document. */
function renderDocument(body, headings, sourceHash) {
  const chapters = headings.filter((heading) => heading.level === 2);
  const toc = buildToc(headings);
  const title = headings.length > 0 ? '流光咖啡馆 · 白皮书 v3' : '流光咖啡馆';

  const styles = `
:root {
  color-scheme: light;
  --brand: #1664ff;
  --brand-soft: #eef4ff;
  --text: #172033;
  --muted: #5c687a;
  --faint: #7b8697;
  --border: #e2e7ee;
  --surface: #f7f9fc;
  --topbar-height: 64px;
  --sidebar-width: 304px;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: calc(var(--topbar-height) + 28px); }
body { margin: 0; background: #fff; color: var(--text); font-size: 16px; line-height: 1.8; }
body.nav-open { overflow: hidden; }
a { color: var(--brand); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { text-decoration-thickness: 2px; }
button, a { -webkit-tap-highlight-color: transparent; }
button { font: inherit; }
[hidden] { display: none !important; }
.skip-link { position: fixed; z-index: 100; top: 8px; left: 8px; padding: 8px 14px; background: var(--text); color: #fff; transform: translateY(-150%); }
.skip-link:focus { transform: translateY(0); }
.topbar { position: sticky; z-index: 50; top: 0; height: var(--topbar-height); display: flex; align-items: center; gap: 16px; padding: 0 28px; border-bottom: 1px solid var(--border); background: rgba(255, 255, 255, .97); }
.brand { display: inline-flex; align-items: center; gap: 10px; color: var(--text); font-size: 15px; font-weight: 650; text-decoration: none; white-space: nowrap; }
.brand-mark { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; background: var(--brand); color: #fff; font-size: 12px; font-weight: 750; letter-spacing: .04em; }
.topbar-divider { width: 1px; height: 20px; background: var(--border); }
.document-kind { color: var(--muted); font-size: 14px; }
.source-link { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; color: var(--muted); font-size: 13px; text-decoration: none; white-space: nowrap; }
.source-link:hover { color: var(--brand); }
.source-link svg { width: 15px; height: 15px; }
.menu-toggle { display: none; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; gap: 7px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text); cursor: pointer; }
.menu-toggle svg { width: 19px; height: 19px; }
.page-shell { display: grid; grid-template-columns: var(--sidebar-width) minmax(0, 1fr); max-width: 1600px; margin: 0 auto; }
.sidebar { position: sticky; top: var(--topbar-height); grid-column: 1; grid-row: 1; height: calc(100vh - var(--topbar-height)); overflow-y: auto; overscroll-behavior: contain; border-right: 1px solid var(--border); background: #fff; scrollbar-width: thin; scrollbar-color: #c7d0dc transparent; }
.sidebar-inner { padding: 24px 16px 40px; }
.sidebar-heading { display: flex; align-items: center; justify-content: space-between; padding: 0 12px 14px; color: var(--text); font-size: 13px; font-weight: 700; letter-spacing: .06em; }
.sidebar-heading span:last-child { color: var(--faint); font-size: 12px; font-weight: 500; letter-spacing: 0; }
.toc-list, .toc-children { margin: 0; padding: 0; list-style: none; }
.toc-chapter { margin: 2px 0; }
.toc-link { position: relative; display: block; border-radius: 6px; color: var(--muted); text-decoration: none; transition: background-color .15s ease, color .15s ease; }
.toc-link:hover { background: var(--surface); color: var(--text); }
.toc-link:focus-visible, .heading-anchor:focus-visible, .chapter-nav-link:focus-visible, .menu-toggle:focus-visible { outline: 3px solid rgba(22, 100, 255, .25); outline-offset: 2px; }
.toc-link-chapter { padding: 7px 12px; font-size: 13.5px; font-weight: 550; line-height: 1.5; }
.toc-children { margin: 3px 0 7px 13px; padding-left: 10px; border-left: 1px solid var(--border); }
.toc-link-child { padding: 5px 9px; font-size: 12.5px; line-height: 1.5; }
.toc-link.active, .toc-link[aria-current="location"] { background: var(--brand-soft); color: var(--brand); font-weight: 650; }
.toc-link-chapter.active::before, .toc-link-chapter[aria-current="location"]::before { position: absolute; top: 8px; bottom: 8px; left: 0; width: 3px; border-radius: 3px; background: var(--brand); content: ""; }
main { grid-column: 2; grid-row: 1; min-width: 0; }
.whitepaper { width: min(100%, 960px); margin: 0 auto; padding: 48px 48px 64px; }
.whitepaper h1, .whitepaper h2, .whitepaper h3 { position: relative; color: #111b2d; font-weight: 700; line-height: 1.4; letter-spacing: -.015em; }
.whitepaper h1 { max-width: 820px; margin: 0 0 28px; font-size: clamp(30px, 4vw, 42px); line-height: 1.3; }
.whitepaper h2 { margin: 0 0 24px; padding-top: 4px; font-size: 28px; }
.whitepaper h3 { margin: 40px 0 16px; font-size: 20px; }
.heading-anchor { position: absolute; margin-left: 10px; color: #a0abba; font-size: .7em; font-weight: 400; text-decoration: none; opacity: 0; }
.whitepaper h1:hover .heading-anchor, .whitepaper h2:hover .heading-anchor, .whitepaper h3:hover .heading-anchor, .heading-anchor:focus-visible { opacity: 1; }
.whitepaper p { margin: 0 0 18px; }
.whitepaper strong { color: #101b2e; font-weight: 650; }
.whitepaper ul, .whitepaper ol { margin: 0 0 22px; padding-left: 1.6em; }
.whitepaper li { margin: 5px 0; padding-left: 3px; }
.whitepaper li::marker { color: #6b7890; }
.whitepaper blockquote { margin: 0 0 28px; padding: 16px 20px; border: 0; border-left: 3px solid var(--brand); border-radius: 0 7px 7px 0; background: var(--surface); color: #48566b; }
.whitepaper blockquote p { white-space: pre-line; }
.whitepaper blockquote p:last-child { margin-bottom: 0; }
.whitepaper code { padding: .12em .36em; border: 1px solid #e4e8ef; border-radius: 4px; background: #f5f7fa; color: #24324a; font-family: "Cascadia Code", "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: .88em; overflow-wrap: anywhere; }
.whitepaper pre { margin: 0; padding: 20px; overflow: auto; border: 1px solid var(--border); border-radius: 0 0 7px 7px; background: #f7f9fb; line-height: 1.65; tab-size: 2; }
.whitepaper pre code { padding: 0; border: 0; background: transparent; font-size: 13px; overflow-wrap: normal; }
.code-block { margin: 24px 0 28px; }
.code-block figcaption { display: flex; justify-content: space-between; padding: 8px 14px; border: 1px solid var(--border); border-bottom: 0; border-radius: 7px 7px 0 0; background: #fff; color: var(--faint); font-size: 12px; }
.table-wrap { max-width: 100%; margin: 22px 0 28px; overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
table { width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.65; }
th, td { min-width: 96px; padding: 12px 15px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
th { background: var(--surface); color: #354156; font-weight: 650; white-space: nowrap; }
th:not(:last-child), td:not(:last-child) { border-right: 1px solid #edf0f4; }
tr:last-child td { border-bottom: 0; }
tbody tr:hover { background: #fbfcfe; }
.chapter { padding-top: 48px; }
.chapter > hr { height: 1px; margin: 44px 0 28px; border: 0; background: var(--border); }
.whitepaper > h1 + blockquote { margin-bottom: 24px; }
.whitepaper > hr { height: 1px; margin: 28px 0 0; border: 0; background: var(--border); }
.chapter-nav { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin: 0; }
.chapter-nav-link { display: flex; min-height: 84px; flex-direction: column; justify-content: center; gap: 3px; padding: 13px 16px; border: 1px solid var(--border); border-radius: 8px; color: var(--text); text-decoration: none; }
.chapter-nav-link:hover { border-color: #aabfdf; background: #fafcff; }
.chapter-nav-next { align-items: flex-end; text-align: right; }
.chapter-nav-direction { color: var(--brand); font-size: 12px; font-weight: 650; }
.chapter-nav-title { color: var(--muted); font-size: 13px; line-height: 1.5; }
.diagram { margin: 24px 0 30px; border: 1px solid var(--border); border-radius: 9px; background: #fff; }
.diagram-caption { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 11px 16px; border-bottom: 1px solid var(--border); color: #445168; font-size: 13px; font-weight: 600; }
.diagram-caption span:last-child { color: var(--faint); font-size: 11px; font-weight: 500; white-space: nowrap; }
.diagram-viewport { max-width: 100%; padding: 20px; overflow-x: auto; background: #fff; }
.mermaid-svg { display: block; min-width: 0; max-width: none !important; height: auto; margin: 0 auto; }
.diagram-source { border-top: 1px solid var(--border); }
.diagram-source summary { padding: 10px 16px; color: var(--muted); font-size: 12px; cursor: pointer; }
.diagram-source[open] summary { border-bottom: 1px solid var(--border); }
.diagram-source pre { border: 0; border-radius: 0 0 8px 8px; }
.document-footer { width: min(100%, 960px); margin: 0 auto; padding: 22px 48px 40px; border-top: 1px solid var(--border); color: var(--faint); font-size: 12px; }
.document-footer code { font-family: "Cascadia Code", Consolas, monospace; }
.nav-backdrop { display: none; }
@media (min-width: 1500px) {
  :root { --sidebar-width: 320px; }
  .whitepaper { padding-right: 56px; padding-left: 56px; }
}
@media (max-width: 1100px) {
  :root { --sidebar-width: 270px; }
  .whitepaper { padding: 40px 32px 56px; }
  .document-footer { padding-right: 32px; padding-left: 32px; }
}
@media (max-width: 900px) {
  :root { --topbar-height: 58px; }
  .topbar { gap: 12px; padding: 0 16px; }
  .menu-toggle { display: inline-flex; }
  .brand-mark { display: none; }
  .brand { font-size: 14px; }
  .topbar-divider, .document-kind { display: none; }
  .source-link { font-size: 12px; }
  .page-shell { display: block; }
  .sidebar { position: fixed; z-index: 80; top: var(--topbar-height); bottom: 0; left: 0; width: min(86vw, 340px); height: auto; border-right: 1px solid #cfd7e3; transform: translateX(-102%); transition: transform .2s ease; }
  .sidebar.is-open { transform: translateX(0); }
  .sidebar-inner { padding-top: 20px; }
  .toc-link-chapter { min-height: 44px; padding-top: 10px; padding-bottom: 10px; }
  .toc-link-child { min-height: 40px; padding-top: 8px; padding-bottom: 8px; }
  .nav-backdrop { position: fixed; z-index: 70; inset: var(--topbar-height) 0 0; display: block; width: 100%; height: auto; padding: 0; border: 0; background: rgba(23, 32, 51, .32); cursor: pointer; }
  main { width: 100%; }
  .whitepaper { width: 100%; max-width: none; padding: 32px 24px 52px; }
  .whitepaper h1 { font-size: 32px; }
  .whitepaper h2 { font-size: 25px; }
  .chapter { padding-top: 38px; }
  .document-footer { width: 100%; padding: 20px 24px 34px; }
  .heading-anchor { opacity: .55; }
}
@media (max-width: 520px) {
  .source-link span { display: none; }
  .whitepaper { padding: 28px 18px 44px; }
  .whitepaper h1 { font-size: 28px; }
  .whitepaper h2 { font-size: 23px; }
  .whitepaper h3 { font-size: 19px; }
  .whitepaper p, .whitepaper li { font-size: 15.5px; }
  .chapter-nav { grid-template-columns: 1fr; }
  .chapter-nav-placeholder { display: none; }
  .chapter-nav-next { align-items: flex-start; text-align: left; }
  .diagram-viewport { padding: 12px; }
  th, td { padding: 10px 12px; }
  .document-footer { padding-right: 18px; padding-left: 18px; }
}
@media print {
  :root { --topbar-height: 0px; }
  .topbar, .sidebar, .chapter-nav, .nav-backdrop, .heading-anchor, .document-footer { display: none !important; }
  .page-shell { display: block; }
  .whitepaper { width: 100%; max-width: none; padding: 0; }
  .chapter { break-before: page; padding-top: 20px; }
  .chapter:first-of-type { break-before: auto; }
  .table-wrap, .diagram-viewport, .whitepaper pre { overflow: visible; }
  .diagram, .code-block, .table-wrap { break-inside: avoid; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .toc-link, .sidebar { transition: none; }
}
`;

  const script = `
(() => {
  const sidebar = document.getElementById('site-nav');
  const toggle = document.getElementById('menu-toggle');
  const backdrop = document.getElementById('nav-backdrop');
  const links = Array.from(document.querySelectorAll('#whitepaper-toc a[data-heading-id]'));
  const headings = links.map((link) => ({
    id: link.dataset.headingId,
    link,
    element: document.getElementById(link.dataset.headingId)
  })).filter((heading) => heading.element);
  let frame = 0;

  function isMobile() {
    return window.matchMedia('(max-width: 900px)').matches;
  }

  function setActive(id) {
    for (const heading of headings) {
      const active = heading.id === id;
      heading.link.classList.toggle('active', active);
      if (active) heading.link.setAttribute('aria-current', 'location');
      else heading.link.removeAttribute('aria-current');
    }
    const activeLink = links.find((link) => link.dataset.headingId === id);
    if (!activeLink || isMobile()) return;
    const linkRect = activeLink.getBoundingClientRect();
    const sidebarRect = sidebar.getBoundingClientRect();
    if (linkRect.top < sidebarRect.top + 12 || linkRect.bottom > sidebarRect.bottom - 12) {
      const target = sidebar.scrollTop + linkRect.top - sidebarRect.top - sidebarRect.height / 2;
      sidebar.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
    }
  }

  function updatePosition() {
    frame = 0;
    if (!headings.length) return;
    const threshold = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-height')) + 42;
    let current = headings[0];
    for (const heading of headings) {
      if (heading.element.getBoundingClientRect().top <= threshold) current = heading;
      else break;
    }
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      current = headings[headings.length - 1];
    }
    setActive(current.id);
  }

  function requestPositionUpdate() {
    if (!frame) frame = window.requestAnimationFrame(updatePosition);
  }

  function openNav() {
    sidebar.classList.add('is-open');
    toggle.setAttribute('aria-expanded', 'true');
    backdrop.hidden = false;
    document.body.classList.add('nav-open');
  }

  function closeNav(returnFocus) {
    sidebar.classList.remove('is-open');
    toggle.setAttribute('aria-expanded', 'false');
    backdrop.hidden = true;
    document.body.classList.remove('nav-open');
    if (returnFocus) toggle.focus();
  }

  toggle.addEventListener('click', () => {
    if (sidebar.classList.contains('is-open')) closeNav(false);
    else openNav();
  });
  backdrop.addEventListener('click', () => closeNav(true));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && sidebar.classList.contains('is-open')) closeNav(true);
  });
  for (const link of links) {
    link.addEventListener('click', () => {
      setActive(link.dataset.headingId);
      if (isMobile()) closeNav(false);
    });
  }
  window.addEventListener('scroll', requestPositionUpdate, { passive: true });
  window.addEventListener('resize', () => {
    if (!isMobile()) closeNav(false);
    requestPositionUpdate();
  });
  window.addEventListener('hashchange', requestPositionUpdate);
  updatePosition();
})();
`;

  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="source-sha256" content="${sourceHash}">
  <meta name="generator" content="tools/build-whitepaper.mjs">
  <title>${escapeHtml(title)} · 完整阅读版</title>
  <style>${styles}</style>
</head>
<body>
  <a class="skip-link" href="#whitepaper-content">跳到正文</a>
  <header class="topbar">
    <button class="menu-toggle" id="menu-toggle" type="button" aria-label="打开或关闭白皮书目录" aria-controls="site-nav" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" stroke-linecap="round"/></svg>
      <span>目录</span>
    </button>
    <a class="brand" href="#whitepaper-content"><span class="brand-mark" aria-hidden="true">LC</span><span>流光咖啡馆</span></a>
    <span class="topbar-divider" aria-hidden="true"></span>
    <span class="document-kind">白皮书 v3 · 完整阅读版</span>
    <a class="source-link" href="白皮书-v3.md"><span>Markdown 源文件</span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 5h5v5M10 14l9-9M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
  </header>
  <div class="page-shell">
    <aside class="sidebar" id="site-nav" aria-label="白皮书导航">
      <div class="sidebar-inner">
        <div class="sidebar-heading"><span>白皮书目录</span><span>${chapters.length} 章</span></div>
        <nav id="whitepaper-toc" aria-label="全部章节">${toc}</nav>
      </div>
    </aside>
    <main id="whitepaper-content">
      <article class="whitepaper">${body}</article>
      <footer class="document-footer">内容以 <code>docs/白皮书-v3.md</code> 为准 · 本页由生成工具同步重建，可直接离线阅读与打印。</footer>
    </main>
  </div>
  <button class="nav-backdrop" id="nav-backdrop" type="button" aria-label="关闭目录" hidden></button>
  <script>${script}</script>
</body>
</html>
`;
}

/** Build the HTML without touching the Markdown source or starting a server. */
async function build() {
  const originalSource = readFileSync(sourcePath, 'utf8');
  const normalizedSource = originalSource.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const sourceHash = createHash('sha256').update(originalSource).digest('hex');
  const md = createMarkdownParser();
  const env = {};
  const tokens = md.parse(normalizedSource, env);
  await renderMermaidDiagrams(tokens, env.headings);
  const body = md.renderer.render(tokens, md.options, env);
  return renderDocument(body, env.headings, sourceHash);
}

async function main() {
  const args = new Set(process.argv.slice(2));
  const unknownArgs = [...args].filter((argument) => argument !== '--check');
  if (unknownArgs.length > 0) {
    throw new Error(`不支持的参数：${unknownArgs.join(', ')}。仅支持 --check。`);
  }

  const html = await build();
  if (args.has('--check')) {
    if (!existsSync(outputPath)) {
      throw new Error('HTML 尚未生成。请运行 npm --prefix=tools run docs:build。');
    }
    if (readFileSync(outputPath, 'utf8') !== html) {
      throw new Error('HTML 与 Markdown 不同步。请运行 npm --prefix=tools run docs:build 重新生成。');
    }
    console.log('白皮书 HTML 与 Markdown 同步，且确定性重建检查通过。');
    return;
  }

  writeFileSync(outputPath, html, 'utf8');
  console.log(`已生成 ${outputPath}（完整章节、内联 SVG、离线导航）。`);
}

main().catch((error) => {
  console.error(`白皮书生成失败：${error.message}`);
  process.exitCode = 1;
});
