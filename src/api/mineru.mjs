// MinerU 在线 API 客户端（白皮书 §15-2：一律走在线 API；先下载 PDF 再上传，绕开国外源超时）
// 真实流程沿用旧栈已验证调用：POST /file-urls/batch 取签名直传 → PUT 上传 →
// 轮询 GET /extract-results/batch/{batch_id} → 下载 zip 取 Markdown/JSON。
// 未配置 MINERU_API_TOKEN 时走 mock：产出确定性的假 blocks（全链路可演示，验收标注）。
import { storage } from "./storage.mjs";

const BASE = process.env.MINERU_BASE_URL ?? "https://mineru.net/api/v4";
const hasToken = () => Boolean(process.env.MINERU_API_TOKEN);

/** 上传 PDF → 解析 → 返回 blocks：[{block_idx, block_type, text_level, page_no, content}] */
export async function parsePdfBuffer(pdfBuf, itemId) {
  if (!hasToken()) return mockParse(pdfBuf, itemId);
  return realParse(pdfBuf);
}

async function realParse(pdfBuf) {
  const headers = { Authorization: `Bearer ${process.env.MINERU_API_TOKEN}` };
  // 1) 申请批量上传地址
  const urlsRes = await fetch(`${BASE}/file-urls/batch`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ enable_formula: true, enable_table: true, files: [{ name: "paper.pdf", is_ocr: true, data_id: `lc-${Date.now()}` }] }),
  });
  if (!urlsRes.ok) throw new Error(`MinerU 申请上传失败：HTTP ${urlsRes.status}`);
  const urlsData = await urlsRes.json();
  const file = urlsData.data?.file_urls?.[0];
  if (!file?.batch_id || !file?.url) throw new Error("MinerU 返回缺少 batch_id/url");

  // 2) 直传 PDF 到签名地址
  const up = await fetch(file.url, { method: "PUT", body: pdfBuf });
  if (!up.ok) throw new Error(`MinerU 上传失败：HTTP ${up.status}`);

  // 3) 轮询解析结果（最长 10 分钟）
  const deadline = Date.now() + 10 * 60 * 1000;
  for (;;) {
    await new Promise((r) => setTimeout(r, 4000));
    const res = await fetch(`${BASE}/extract-results/batch/${file.batch_id}`, { headers });
    if (!res.ok) throw new Error(`MinerU 查询失败：HTTP ${res.status}`);
    const data = await res.json();
    const state = data.data?.state;
    if (state === "done") {
      const zipUrl = data.data?.full_zip_url;
      if (!zipUrl) throw new Error("MinerU 完成但未给 zip 地址");
      return await extractBlocksFromZip(zipUrl);
    }
    if (state === "failed") throw new Error(`MinerU 解析失败：${JSON.stringify(data.data?.err_msg ?? "")}`);
    if (Date.now() > deadline) throw new Error("MinerU 解析超时（10 分钟）");
  }
}

// 从 zip 里取 JSON 结构产物转 blocks（字段按 MinerU v4 产物：pdf_info[].para_blocks）
async function extractBlocksFromZip(zipUrl) {
  const res = await fetch(zipUrl);
  if (!res.ok) throw new Error(`下载 MinerU 产物失败：HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  const { unzipSync } = await import("node:zlib");
  let files;
  try {
    files = unzipSync(buf);
  } catch {
    // 有的返回直接是 JSON
    return jsonTextToBlocks(Buffer.from(buf).toString("utf8"));
  }
  for (const [name, content] of Object.entries(files)) {
    if (name.endsWith("_content_list.json") || (name.endsWith(".json") && !name.includes("middle"))) {
      return jsonTextToBlocks(content.toString("utf8"));
    }
  }
  throw new Error("MinerU zip 里没有 JSON 产物");
}

function jsonTextToBlocks(text) {
  const data = JSON.parse(text);
  const pages = Array.isArray(data) ? data : (data.pdf_info ?? []);
  const blocks = [];
  let idx = 0;
  for (const page of pages) {
    for (const para of page.para_blocks ?? []) {
      const content = (para.text ?? "").trim();
      if (!content) continue;
      blocks.push({
        block_idx: idx++,
        block_type: para.type ?? (para.text_level ? "heading" : "text"),
        text_level: para.text_level ?? 0,
        page_no: page.page_idx ?? 0,
        content,
      });
    }
  }
  if (blocks.length === 0) throw new Error("MinerU 产物里没有文本块");
  return blocks;
}

// 未配置 token：确定性假 blocks（内容是 PDF 字节数的派生文本，保证幂等演示）
function mockParse(pdfBuf, itemId) {
  const seed = pdfBuf.length;
  const topics = ["研究背景与动机", "方法概述", "实验设置", "结果与分析", "结论与展望"];
  return topics.map((t, i) => ({
    block_idx: i,
    block_type: i === 0 ? "heading" : "text",
    text_level: i === 0 ? 1 : 0,
    page_no: Math.floor(i / 2) + 1,
    content: `${t}：这是 MinerU mock 解析产物（未配置 MINERU_API_TOKEN，种子 ${seed}，条目 ${itemId}）。真实解析走 mineru.net 在线 API，配置 token 后本段替换为论文真实内容。`,
  }));
}
