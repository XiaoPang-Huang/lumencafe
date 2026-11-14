// 阅读器与单篇问答（第 3 批 3d）
// 问答按白皮书：模型只出检索意图和单次回答，不写 SQL；检索范围锁本篇 blocks+批注；
// 出处 = block 级，点引用跳原文 flash（复用批注 anchor 机制）。
import { getPg } from "../db.mjs";
import { conv as chatConv, msg as chatMsg } from "./chat-db.mjs";
import { streamChat } from "./llm.mjs";
import { gateApp } from "./gateway.mjs";

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });
const keyOf = (ctx) => JSON.stringify(ctx.principal);

/** 条目可见性：本人或 shared */
async function visibleItem(itemId, userId) {
  const { rows } = await getPg().query(
    "SELECT i.*, p.title FROM library_items i JOIN papers p ON p.id = i.paper_id WHERE i.id = $1",
    [itemId],
  );
  const item = rows[0];
  if (!item) return null;
  if (item.user_id !== userId && !item.shared) return null;
  return item;
}

async function embedQuery(text) {
  if (process.env.EMBEDDING_API_KEY) {
    const res = await fetch(`${process.env.EMBEDDING_BASE_URL ?? "https://api.siliconflow.cn/v1"}/embeddings`, {
      method: "POST",
      headers: { Authorization: `Bearer ${process.env.EMBEDDING_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: process.env.EMBEDDING_MODEL ?? "BAAI/bge-m3", input: [text] }),
    });
    if (res.ok) return (await res.json()).data[0].embedding;
  }
  // mock 与 pipeline 同规则
  const v = new Array(1024).fill(0);
  for (let i = 0; i < text.length; i++) v[(text.charCodeAt(i) + i * 31) % 1024] += (text.charCodeAt(i) % 97) / 97;
  const norm = Math.sqrt(v.reduce((a, b) => a + b * b, 0)) || 1;
  return v.map((x) => x / norm);
}

export function readerRoutes() {
  // 批 3：阅读器归属论文应用，同走 papers 门槛
  return gateApp("papers", {
    // 论文问答会话（每人一条，消息存 SQLite 框架态）
    "GET /api/papers/conversation": async (_r, ctx) =>
      json({ conversation: chatConv.ensureApp(keyOf(ctx), "papers", "论文问答") }),

    // 阅读器内容：blocks + 我的批注
    "GET /api/papers/items/:id/reader": async (request, ctx) => {
      const userId = keyOf(ctx);
      const item = await visibleItem(request.params.id, userId);
      if (!item) return bad(404, "论文不存在或无权查看");
      const pg = getPg();
      const { rows: blocks } = await pg.query(
        "SELECT block_idx, block_type, text_level, page_no, content, content_zh FROM parse_blocks WHERE paper_id = $1 ORDER BY block_idx",
        [item.paper_id],
      );
      const { rows: annotations } = await pg.query(
        "SELECT * FROM annotations WHERE paper_id = $1 AND user_id = $2 ORDER BY anchor_block, id",
        [item.paper_id, userId],
      );
      return json({ item, paper: { id: item.paper_id, title: item.title }, blocks, annotations });
    },

    /* ---------- 批注笔记 ---------- */
    "POST /api/papers/items/:id/annotations": async (request, ctx) => {
      const userId = keyOf(ctx);
      const item = await visibleItem(request.params.id, userId);
      if (!item) return bad(404, "论文不存在或无权查看");
      const body = await request.json().catch(() => null);
      const anchor = Number(body?.anchor_block);
      const text = String(body?.body ?? "").trim();
      if (!Number.isInteger(anchor) || !text) return bad(400, "批注需要锚定段落和内容");
      const { rows: blk } = await getPg().query(
        "SELECT content FROM parse_blocks WHERE paper_id = $1 AND block_idx = $2", [item.paper_id, anchor],
      );
      const links = Array.isArray(body?.links) ? body.links.map(String).slice(0, 20) : [];
      const { rows } = await getPg().query(
        `INSERT INTO annotations (paper_id, user_id, anchor_block, anchor_quote, body, links) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *`,
        [item.paper_id, userId, anchor, blk[0]?.content.slice(0, 80) ?? "", text.slice(0, 2000), links],
      );
      return json({ annotation: rows[0] }, 201);
    },

    "PATCH /api/papers/annotations/:id": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const r = await getPg().query(
        "UPDATE annotations SET body = $3, links = $4, updated_at = now() WHERE id = $1 AND user_id = $2 RETURNING *",
        [request.params.id, keyOf(ctx), String(body?.body ?? "").slice(0, 2000), Array.isArray(body?.links) ? body.links.map(String).slice(0, 20) : []],
      );
      return r.rows[0] ? json({ annotation: r.rows[0] }) : bad(404, "批注不存在");
    },

    "DELETE /api/papers/annotations/:id": async (request, ctx) => {
      const r = await getPg().query("DELETE FROM annotations WHERE id = $1 AND user_id = $2 RETURNING id", [request.params.id, keyOf(ctx)]);
      return r.rows[0] ? json({ ok: true }) : bad(404, "批注不存在");
    },

    /* ---------- 中英对照翻译（走 LLM 渠道；mock 时前缀标注） ---------- */
    "POST /api/papers/items/:id/translate": async (request, ctx) => {
      const userId = keyOf(ctx);
      const item = await visibleItem(request.params.id, userId);
      if (!item) return bad(404, "论文不存在或无权查看");
      const body = await request.json().catch(() => null);
      const anchor = Number(body?.block_idx);
      const pg = getPg();
      const { rows: blk } = await pg.query(
        "SELECT content, content_zh FROM parse_blocks WHERE paper_id = $1 AND block_idx = $2", [item.paper_id, anchor],
      );
      if (!blk[0]) return bad(404, "段落不存在");
      if (blk[0].content_zh) return json({ block_idx: anchor, content_zh: blk[0].content_zh, cached: true });
      const zh = await streamChat({
        systemPrompt: "你是论文翻译助手。把给定段落译成通顺的中文，只给译文，保留公式记号。",
        messages: [{ role: "user", content: blk[0].content }],
      });
      await pg.query("UPDATE parse_blocks SET content_zh = $3 WHERE paper_id = $1 AND block_idx = $2", [item.paper_id, anchor, zh]);
      return json({ block_idx: anchor, content_zh: zh, cached: false });
    },

    /* ---------- 单篇问答（双路检索 + 重排 + 带出处回答） ---------- */
    "POST /api/papers/items/:id/ask": async (request, ctx) => {
      const userId = keyOf(ctx);
      const item = await visibleItem(request.params.id, userId);
      if (!item) return bad(404, "论文不存在或无权查看");
      const body = await request.json().catch(() => null);
      const question = String(body?.question ?? "").trim();
      const reqId = body?.req_id;
      if (!question || typeof reqId !== "string" || !reqId) return bad(400, "缺少问题或请求标识");

      const pg = getPg();
      const c = chatConv.ensureApp(userId, "papers", "论文问答");
      chatMsg.saveUser(c.id, { reqId, content: `【${item.title}】${question}` });
      chatConv.touch(userId, c.id);

      const { rows: blocks } = await pg.query(
        "SELECT block_idx, content FROM parse_blocks WHERE paper_id = $1 ORDER BY block_idx", [item.paper_id],
      );
      if (blocks.length === 0) {
        const m = chatMsg.saveAssistant(c.id, { reqId: `qa-${reqId}`, content: "这篇还没解析出内容，等阶段条走完再提问。" });
        return json({ message: m, citations: [] });
      }

      // 1) 单次调用：问题 → 检索意图（语义串 + 关键词）
      let intent;
      try {
        intent = await streamChat({
          systemPrompt: "你是检索意图提取器。把用户的论文问题提取成 JSON：{\"semantic\":\"<语义查询串>\",\"keywords\":[\"<2到4个关键词>\"]}。只输出 JSON。",
          messages: [{ role: "user", content: question }],
        }).then((t) => JSON.parse(t.match(/\{[\s\S]*\}/)?.[0] ?? "{}"));
      } catch {
        intent = { semantic: question, keywords: question.replace(/[？?，。,.!！]/g, " ").split(/\s+/).filter((w) => w.length >= 2).slice(0, 4) };
      }

      // 2) 双路检索（范围锁本篇；模型不写 SQL）
      const vec = await embedQuery(intent.semantic || question);
      const { rows: vecHits } = await pg.query(
        `SELECT block_idx, chunk_text, 1 - (vector <=> $2::vector) AS score
         FROM embeddings WHERE paper_id = $1 ORDER BY vector <=> $2::vector LIMIT 6`,
        [item.paper_id, `[${vec.join(",")}]`],
      );
      const kw = (intent.keywords ?? []).filter((k) => typeof k === "string" && k.length >= 2).slice(0, 4);
      let kwHits = [];
      if (kw.length) {
        const { rows } = await pg.query(
          `SELECT block_idx, content AS chunk_text, 0.9 AS score FROM parse_blocks
           WHERE paper_id = $1 AND (${kw.map((_, i) => `content ILIKE $${i + 2}`).join(" OR ")}) LIMIT 6`,
          [item.paper_id, ...kw.map((k) => `%${k}%`)],
        );
        kwHits = rows;
      }

      // 3) 合并去重 → 重排（有重排 API 用 bge-reranker-v2-m3，否则按分数取 top5）
      const merged = new Map();
      for (const h of [...kwHits, ...vecHits]) {
        if (!merged.has(h.block_idx) || merged.get(h.block_idx).score < h.score) merged.set(h.block_idx, h);
      }
      let candidates = [...merged.values()].sort((a, b) => b.score - a.score).slice(0, 8);
      if (process.env.RERANK_API_KEY && candidates.length > 2) {
        try {
          const pairs = candidates.map((h) => [question, h.chunk_text]);
          const res = await fetch(`${process.env.RERANK_BASE_URL ?? "https://api.siliconflow.cn/v1"}/rerank`, {
            method: "POST",
            headers: { Authorization: `Bearer ${process.env.RERANK_API_KEY}`, "Content-Type": "application/json" },
            body: JSON.stringify({ model: process.env.RERANK_MODEL ?? "BAAI/bge-reranker-v2-m3", query: question, documents: pairs.map((p) => p[1]) }),
          });
          if (res.ok) {
            const data = await res.json();
            candidates = data.results.slice(0, 5).map((r) => candidates[r.index]);
          }
        } catch { /* 重排失败就用原顺序 */ }
      } else {
        candidates = candidates.slice(0, 5);
      }
      if (candidates.length === 0) {
        const m = chatMsg.saveAssistant(c.id, { reqId: `qa-${reqId}`, content: "在这篇里没找到相关段落。" });
        return json({ message: m, citations: [] });
      }

      // 4) 单次回答：top 段落（带 block 标号）→ 回答 + 〔N〕出处
      const labeled = candidates.map((h, i) => `【段落${h.block_idx}】${h.chunk_text}`).join("\n\n");
      let answer;
      try {
        answer = await streamChat({
          systemPrompt: "你是论文阅读助手。只能根据给定段落回答，每处依据后面标〔段落号〕（如〔3〕）；段落里没有的不要编；回答用中文，简洁。",
          messages: [{ role: "user", content: `问题：${question}\n\n本篇候选段落：\n${labeled}` }],
        });
      } catch (error) {
        const m = chatMsg.saveAssistant(c.id, { reqId: `qa-${reqId}`, content: "生成失败，请点重试。", status: "failed" });
        return json({ message: m, citations: [], failed: true });
      }
      const citations = [...new Set([...answer.matchAll(/〔(\d+)〕/g)].map((m) => Number(m[1])))].filter((n) => candidates.some((c2) => c2.block_idx === n));
      const m = chatMsg.saveAssistant(c.id, { reqId: `qa-${reqId}`, content: answer, kind: "paper_qa" });
      return json({
        message: m,
        citations,
        details: candidates.filter((c2) => citations.includes(c2.block_idx)),
      });
    },
  });
}
