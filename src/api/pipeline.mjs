// 论文下载 + 解析管线（第 3 批，白皮书 §08 论文下载解析时序图）
// 实施说明（2026-11-14）：探索器暂为代码级多源适配器（arXiv/OpenAlex/S2/PubMed/DOAJ），
// 护栏语义与白皮书一致（≤5 源 / ≤10 步 / 失败分类落库 / 全手动重试 / 幂等）；
// 接口留成可替换——第 5 批 agent 底座落地后换 pi agent 探索器，应用代码一行不动。
// 慢活三规矩：写数据 + 记待办同一次事务（papers.mjs 提交处）；后台并发 1；任务幂等。
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { getPg } from "../db.mjs";
import { storage } from "./storage.mjs";
import { parsePdfBuffer } from "./mineru.mjs";

const stagingDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", ".data", "staging");
fs.mkdirSync(stagingDir, { recursive: true });

const MOCK = process.env.PAPERS_MOCK === "1";
const GUARD = { maxSources: 5, maxSteps: 10, maxBytes: 30 * 1024 * 1024 };

/* ---------- 元数据解析（添加论文时用） ---------- */
export async function resolveMeta(input) {
  const text = String(input ?? "").trim();
  if (!text) throw new Error("请给标题、DOI 或 arXiv 编号");
  if (MOCK) {
    return {
      arxiv_id: /^\d{4}\.\d{4,5}/.test(text) ? text.match(/^\d{4}\.\d{4,5}/)[0] : null,
      doi: /^10\./.test(text) ? text : null,
      title: /^\d{4}\.\d{4,5}/.test(text) || /^10\./.test(text) ? `Mock 论文 ${text.slice(0, 24)}` : text.slice(0, 200),
      authors: "Mock 作者", journal: "Mock 期刊", year: new Date().getFullYear(), abstract: "Mock 摘要。",
    };
  }
  // 真实解析：按形态路由到源（arXiv 编号 / DOI / 标题走 OpenAlex）
  const arxiv = text.match(/(?:arxiv:|arxiv\.org\/abs\/)?(\d{4}\.\d{4,5})(v\d+)?/i);
  if (arxiv) return arxivMeta(arxiv[1]);
  if (/^10\.\d{4,}\//.test(text)) return openAlexByDoi(text);
  return openAlexByTitle(text);
}

async function arxivMeta(id) {
  const res = await fetch(`https://export.arxiv.org/api/query?id_list=${id}`);
  if (!res.ok) throw new Error(`arXiv 查询失败 HTTP ${res.status}`);
  const xml = await res.text();
  const entry = xml.split("<entry>")[1];
  if (!entry) throw new Error("arXiv 上没有这篇");
  const pick = (tag) => entry.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1]?.trim() ?? "";
  return {
    arxiv_id: id,
    title: pick("title").replace(/\s+/g, " "),
    authors: [...entry.matchAll(/<name>(.*?)<\/name>/g)].map((m) => m[1]).join(", ").slice(0, 300),
    journal: "arXiv",
    year: Number(pick("published").slice(0, 4)) || null,
    abstract: pick("summary").replace(/\s+/g, " ").slice(0, 4000),
  };
}

async function openAlexByDoi(doi) {
  const res = await fetch(`https://api.openalex.org/works/doi:${encodeURIComponent(doi)}`);
  if (!res.ok) throw new Error(`OpenAlex 查不到 DOI（HTTP ${res.status}）`);
  return openAlexShape(await res.json(), doi);
}

async function openAlexByTitle(title) {
  const res = await fetch(`https://api.openalex.org/works?search=${encodeURIComponent(title)}&per-page=1`);
  if (!res.ok) throw new Error(`OpenAlex 查询失败 HTTP ${res.status}`);
  const data = await res.json();
  if (!data.results?.length) throw new Error("OpenAlex 上没有匹配的论文");
  return openAlexShape(data.results[0], null);
}

const openAlexShape = (w, doi) => ({
  doi: doi ?? w.doi?.replace("https://doi.org/", "") ?? null,
  title: w.title ?? w.display_name ?? "",
  authors: (w.authorships ?? []).map((a) => a.author?.display_name).filter(Boolean).join(", ").slice(0, 300),
  journal: w.primary_location?.source?.display_name ?? "",
  year: w.publication_year ?? null,
  cited_by: w.cited_by_count ?? 0,
  abstract: w.abstract_inverted_index
    ? Object.entries(w.abstract_inverted_index).sort((a, b) => a[1][0] - b[1][0]).map(([word]) => word).join(" ").slice(0, 4000)
    : "",
});

/* ---------- 探索器：多源找 PDF（护栏内换源） ---------- */
async function findPdf(paper) {
  if (MOCK) {
    // mock 源：生成一个最小 PDF 形态字节串，验证与入库流程全通
    const buf = Buffer.concat([
      Buffer.from("%PDF-1.4 mock\n"),
      Buffer.from(`% mock pdf for paper ${paper.id} ${paper.title}`),
    ]);
    return { buf, source: "mock", steps: 1 };
  }
  const sources = [];
  if (paper.arxiv_id) sources.push(arxivSource(paper.arxiv_id));
  if (paper.doi) sources.push(openAlexSource(paper.doi), unpaywallSource(paper.doi));
  sources.push(semanticScholarSource(paper));

  const failures = [];
  let steps = 0;
  for (const src of sources.slice(0, GUARD.maxSources)) {
    if (steps >= GUARD.maxSteps) break;
    steps++;
    try {
      const url = await src.find();
      if (!url) { failures.push(`${src.name}:无 PDF 链接`); continue; }
      steps++;
      const buf = await downloadLimited(url);
      return { buf, source: src.name, steps };
    } catch (error) {
      failures.push(`${src.name}:${error.message}`);
    }
  }
  const failClass = failures.some((f) => /付费墙|paywall/i.test(f)) ? "付费墙"
    : failures.every((f) => /查不到|没有|无元数据/.test(f)) ? "无元数据" : "有元数据无PDF";
  const guardHit = steps >= GUARD.maxSteps || sources.length > GUARD.maxSources ? "（超护栏止损）" : "";
  throw Object.assign(new Error(`试了 ${Math.min(sources.length, GUARD.maxSources)} 个源没拿到全文${guardHit}：${failures.join("；")}`), { failClass });
}

const arxivSource = (id) => ({
  name: "arXiv",
  find: async () => `https://arxiv.org/pdf/${id}`,
});
const openAlexSource = (doi) => ({
  name: "OpenAlex",
  find: async () => {
    const res = await fetch(`https://api.openalex.org/works/doi:${encodeURIComponent(doi)}`);
    if (!res.ok) throw new Error("无元数据");
    const w = await res.json();
    return w.open_access?.oa_url ?? w.best_oa_location?.pdf_url ?? null;
  },
});
const unpaywallSource = (doi) => ({
  name: "Unpaywall",
  find: async () => {
    const res = await fetch(`https://api.unpaywall.org/v2/${encodeURIComponent(doi)}?email=dev@lumencafe.local`);
    if (!res.ok) throw new Error("无元数据");
    const d = await res.json();
    const loc = d.best_oa_location ?? d.oa_locations?.[0];
    if (!loc) throw new Error("无 PDF");
    return loc.url_for_pdf ?? loc.url;
  },
});
const semanticScholarSource = (paper) => ({
  name: "SemanticScholar",
  find: async () => {
    const id = paper.doi ? `DOI:${paper.doi}` : paper.pmid ? `PMID:${paper.pmid}` : null;
    if (!id) throw new Error("无元数据");
    const res = await fetch(`https://api.semanticscholar.org/graph/v1/paper/${encodeURIComponent(id)}?fields=openAccessPdf,title`);
    if (!res.ok) throw new Error("无元数据");
    const d = await res.json();
    if (!d.openAccessPdf?.url) throw new Error("无 PDF（可能付费墙）");
    return d.openAccessPdf.url;
  },
});

async function downloadLimited(url) {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`下载 HTTP ${res.status}`);
  const reader = res.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > GUARD.maxBytes) throw new Error("文件超过 30MB 上限");
    chunks.push(value);
  }
  return Buffer.concat(chunks);
}

/* ---------- 向量化（bge-m3 可配；无 key 走确定性 mock，换模型全量重算） ---------- */
const EMB_MODEL = process.env.EMBEDDING_API_KEY ? "bge-m3" : "mock-v1";

async function embedTexts(texts) {
  if (process.env.EMBEDDING_API_KEY) {
    const res = await fetch(`${process.env.EMBEDDING_BASE_URL ?? "https://api.siliconflow.cn/v1"}/embeddings`, {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.EMBEDDING_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: process.env.EMBEDDING_MODEL ?? "BAAI/bge-m3", input: texts }),
    });
    if (!res.ok) throw new Error(`向量化失败 HTTP ${res.status}`);
    const data = await res.json();
    return data.data.map((d) => d.embedding);
  }
  // mock：文本哈希 → 确定性单位向量（只保证链路通，语义检索靠关键词路）
  return texts.map((t) => {
    const v = new Array(1024).fill(0);
    for (let i = 0; i < t.length; i++) v[(t.charCodeAt(i) + i * 31) % 1024] += (t.charCodeAt(i) % 97) / 97;
    const norm = Math.sqrt(v.reduce((a, b) => a + b * b, 0)) || 1;
    return v.map((x) => x / norm);
  });
}

/* ---------- 单条管线（四段阶段条：fetch → upload → queue → parse → done） ---------- */
async function setPhase(itemId, phase, extra = {}) {
  const fields = Object.keys(extra).map((k, i) => `${k} = $${i + 3}`).join(", ");
  await getPg().query(
    `UPDATE library_items SET phase = $2, updated_at = now() ${fields ? ", " + fields : ""} WHERE id = $1`,
    [itemId, phase, ...Object.values(extra)],
  );
}

export async function runItem(itemId) {
  const pg = getPg();
  const { rows } = await pg.query(
    `SELECT i.*, p.title, p.doi, p.pmid, p.arxiv_id FROM library_items i JOIN papers p ON p.id = i.paper_id WHERE i.id = $1`,
    [itemId],
  );
  const item = rows[0];
  if (!item) return;
  try {
    // 阶段一：获取全文（探索器护栏内换源）
    await setPhase(itemId, "fetch", { phase_error: "", fail_class: "" });
    const { buf, source } = await findPdf(item);

    // 主程序校验（白皮书：agent 只写指定目录，入库前主程序校验）
    if (!buf.subarray(0, 4).toString().startsWith("%PDF")) throw Object.assign(new Error("下载的不是 PDF 文件"), { failClass: "有元数据无PDF" });

    const pdfKey = `papers/${item.paper_id}.pdf`;
    await storage.put(pdfKey, buf);

    // 阶段二/三/四：上传 → 排队 → 解析（MinerU 在线 API；真实轮询时阶段条可见）
    await setPhase(itemId, "upload", { pdf_key: pdfKey });
    const blocks = await parsePdfBuffer(buf, itemId);
    await setPhase(itemId, "queue");

    await pg.query("DELETE FROM parse_blocks WHERE paper_id = $1", [item.paper_id]);
    for (const b of blocks) {
      await pg.query(
        `INSERT INTO parse_blocks (paper_id, block_idx, block_type, text_level, page_no, content)
         VALUES ($1,$2,$3,$4,$5,$6)`,
        [item.paper_id, b.block_idx, b.block_type, b.text_level, b.page_no, b.content],
      );
    }
    await setPhase(itemId, "parse");

    // 切块向量化（问答检索用）
    await pg.query("DELETE FROM embeddings WHERE paper_id = $1", [item.paper_id]);
    const vecs = await embedTexts(blocks.map((b) => b.content));
    for (let i = 0; i < blocks.length; i++) {
      await pg.query(
        `INSERT INTO embeddings (paper_id, block_idx, chunk_text, vector, model) VALUES ($1,$2,$3,$4,$5)`,
        [item.paper_id, blocks[i].block_idx, blocks[i].content.slice(0, 500), `[${vecs[i].join(",")}]`, EMB_MODEL],
      );
    }

    // Markdown 快照归档存储
    const md = blocks.map((b) => `${"#".repeat(Math.min(b.text_level || 1, 6))} ${b.content}`).join("\n\n");
    const snapshotKey = `snapshots/${item.paper_id}.md`;
    await storage.put(snapshotKey, Buffer.from(md, "utf8"));

    await setPhase(itemId, "done", { snapshot_key: snapshotKey, phase_error: `来源：${source}` });
    await todoDone(itemId);
  } catch (error) {
    const failClass = error.failClass ?? "";
    await setPhase(itemId, "failed", { phase_error: error.message.slice(0, 300), fail_class: failClass });
    await todoDone(itemId, error.message.slice(0, 300));
    console.error(`[papers] 条目 ${itemId} 管线失败:`, error.message);
  }
}

/* ---------- 待办（background_todos，与业务同库；worker 并发 1） ---------- */
async function todoDone(itemId, error = null) {
  await getPg().query(
    `UPDATE background_todos SET status = $2, last_error = $3, updated_at = now()
     WHERE kind = 'paper.fetch' AND status = 'running' AND payload->>'item_id' = $1`,
    [String(itemId), error ? "failed" : "done", error],
  );
}

export async function enqueueFetch(itemId, attempt) {
  await getPg().query(
    `INSERT INTO background_todos (kind, payload, idempotency_key, status)
     VALUES ('paper.fetch', $1, $2, 'pending')
     ON CONFLICT (idempotency_key) DO NOTHING`,
    [JSON.stringify({ item_id: itemId }), `paper-fetch-${itemId}-a${attempt}`],
  );
}

let workerTimer = null;
export function startPaperWorker() {
  if (workerTimer) return;
  workerTimer = setInterval(async () => {
    try {
      const { rows } = await getPg().query(
        `UPDATE background_todos SET status = 'running', locked_at = now(), locked_by = 'paper-worker-1', updated_at = now()
         WHERE id = (SELECT id FROM background_todos WHERE kind = 'paper.fetch' AND status = 'pending' AND run_at <= now() ORDER BY id LIMIT 1)
         RETURNING payload`,
      );
      if (!rows.length) return;
      const itemId = Number(rows[0].payload?.item_id);
      if (itemId) await runItem(itemId);
    } catch (error) {
      console.error("[papers] worker 异常:", error.message);
    }
  }, 3000);
  workerTimer.unref?.();
  console.log("[papers] 后台下载工人已启动（并发 1，每 3 秒领一次待办）");
}
