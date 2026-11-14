// 论文库路由（第 3 批 3a/3b）
import { getPg } from "../db.mjs";
import { resolveMeta, enqueueFetch } from "./pipeline.mjs";
import { gateApp } from "./gateway.mjs";

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });
const keyOf = (ctx) => JSON.stringify(ctx.principal);

export function papersRoutes() {
  // 批 3：论文应用门槛（网关单点，无授权 403「无权访问该应用」）
  return gateApp("papers", {
    // 我的库 + 共享给我的（默认私人，逐篇 shared 对齐记账先例）
    "GET /api/papers/library": async (_r, ctx) => {
      const userId = keyOf(ctx);
      const { rows } = await getPg().query(
        `SELECT i.id, i.paper_id, i.phase, i.phase_error, i.fail_class, i.shared, i.request_id, i.created_at,
                p.title, p.authors, p.journal, p.year, p.doi, p.arxiv_id, p.cited_by, p.abstract,
                (i.user_id = $1) AS mine
         FROM library_items i JOIN papers p ON p.id = i.paper_id
         WHERE i.user_id = $1 OR i.shared = true
         ORDER BY i.updated_at DESC LIMIT 500`,
        [userId],
      );
      return json({ items: rows });
    },

    // 提交论文：建元数据 + 建库条目 + 记待办，同一次事务（慢活规矩一）
    "POST /api/papers/library": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const userId = keyOf(ctx);
      const reqId = body?.request_id;
      if (typeof reqId !== "string" || !reqId) return bad(400, "缺少请求标识");
      const pg = getPg();
      const existed = await pg.query("SELECT * FROM library_items WHERE request_id = $1", [reqId]);
      if (existed.rows[0]) return json({ item: existed.rows[0], duplicated: true }); // 幂等：不重复建条目

      let meta;
      try {
        meta = await resolveMeta(body?.input);
      } catch (error) {
        return bad(400, `没能识别这篇论文：${error.message}`);
      }
      if (!meta.title) return bad(400, "没能识别这篇论文：缺少标题");

      const client = getPg(); // 单例连接，直接在其上做事务（顺序执行，无并发争抢）
      try {
        await client.query("BEGIN");
        const paper = await client.query(
          `INSERT INTO papers (doi, pmid, arxiv_id, title, authors, journal, year, cited_by, abstract)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
           ON CONFLICT (doi) DO UPDATE SET doi = EXCLUDED.doi
           RETURNING *`,
          [meta.doi ?? null, meta.pmid ?? null, meta.arxiv_id ?? null, meta.title,
           meta.authors ?? "", meta.journal ?? "", meta.year ?? null, meta.cited_by ?? 0, meta.abstract ?? ""],
        );
        // DOI 为 NULL 时 ON CONFLICT (doi) 不触发（NULL 不冲突），可能重复建元数据：两人规模可接受，去重靠库条目唯一键
        const item = await client.query(
          `INSERT INTO library_items (paper_id, user_id, request_id) VALUES ($1,$2,$3)
           ON CONFLICT (paper_id, user_id) DO UPDATE SET updated_at = now()
           RETURNING *`,
          [paper.rows[0].id, userId, reqId],
        );
        const attempt = await client.query(
          "SELECT COUNT(*)::int AS n FROM background_todos WHERE kind = 'paper.fetch' AND payload->>'item_id' = $1",
          [String(item.rows[0].id)],
        );
        await client.query(
          `INSERT INTO background_todos (kind, payload, idempotency_key, status) VALUES ('paper.fetch', $1, $2, 'pending')`,
          [JSON.stringify({ item_id: item.rows[0].id }), `paper-fetch-${item.rows[0].id}-a${attempt.rows[0].n}`],
        );
        await client.query("COMMIT");
        return json({ item: item.rows[0], paper: paper.rows[0], duplicated: false }, 201);
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      }
    },

    // 手动重试（白皮书：全手动，不自动重跑；幂等不重复建条目）
    "POST /api/papers/library/:id/retry": async (request, ctx) => {
      const userId = keyOf(ctx);
      const pg = getPg();
      const { rows } = await pg.query("SELECT * FROM library_items WHERE id = $1 AND user_id = $2", [request.params.id, userId]);
      const item = rows[0];
      if (!item) return bad(404, "条目不存在");
      if (item.phase !== "failed" && item.phase !== "done") return bad(400, "这条还在处理中，不用重试");
      const attempt = await pg.query(
        "SELECT COUNT(*)::int AS n FROM background_todos WHERE kind = 'paper.fetch' AND payload->>'item_id' = $1",
        [String(item.id)],
      );
      await pg.query(
        `UPDATE library_items SET phase = 'fetch', phase_error = '', fail_class = '', updated_at = now() WHERE id = $1`,
        [item.id],
      );
      await enqueueFetch(item.id, attempt.rows[0].n);
      return json({ ok: true, attempt: attempt.rows[0].n });
    },

    "PATCH /api/papers/library/:id": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const r = await getPg().query(
        "UPDATE library_items SET shared = COALESCE($3, shared), updated_at = now() WHERE id = $1 AND user_id = $2 RETURNING *",
        [request.params.id, keyOf(ctx), typeof body?.shared === "boolean" ? body.shared : null],
      );
      return r.rows[0] ? json({ item: r.rows[0] }) : bad(404, "条目不存在");
    },

    "DELETE /api/papers/library/:id": async (request, ctx) => {
      const r = await getPg().query("DELETE FROM library_items WHERE id = $1 AND user_id = $2 RETURNING id", [request.params.id, keyOf(ctx)]);
      return r.rows[0] ? json({ ok: true }) : bad(404, "条目不存在（共享条目请找创建人）");
    },
  });
}
