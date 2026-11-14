// 每日 digest：定时抓取 → 去重入库 → 单次 LLM 摘要 → 推送 → push_logs 幂等（第 4 批）
// 判活规矩（白皮书）：整条链步骤固定，只有摘要一次 LLM 调用，不动用 agent。
// 每日早 8 点固定推；无新增也发「今日无新论文」；同一 push_key 重复触发只推一次。
import { getPg } from "../db.mjs";
import { notify } from "./notify.mjs";
import { streamChat } from "./llm.mjs";
import { requireAdmin, gateApp } from "./gateway.mjs";

const MOCK = process.env.CRAWL_MOCK === "1";

const todayKey = () => `digest-${new Date().toISOString().slice(0, 10)}`;

/* ---------- 抓取源（arXiv / Semantic Scholar；mock 模式产固定候选） ---------- */
async function crawlKeyword(keyword) {
  if (MOCK) {
    const stamp = Date.now().toString(36).slice(-4);
    return [{
      arxiv_id: `mock.${stamp}`,
      title: `${keyword} 领域的新进展 Mock 研究 ${stamp}`,
      authors: "Mock 作者", journal: "arXiv", year: new Date().getFullYear(),
      abstract: `这是一篇关于 ${keyword} 的 mock 论文摘要，用于验证抓取推送链路。提出了一种新方法，实验表明效果良好。`,
    }];
  }
  const out = [];
  try {
    const res = await fetch(`https://export.arxiv.org/api/query?search_query=all:${encodeURIComponent(keyword)}&sortBy=submittedDate&sortOrder=descending&max_results=8`);
    if (res.ok) {
      const xml = await res.text();
      for (const chunk of xml.split("<entry>").slice(1)) {
        const pick = (tag) => chunk.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1]?.trim() ?? "";
        out.push({
          arxiv_id: (pick("id").match(/abs\/(\S+?)(v\d+)?$/)?.[1]) ?? null,
          title: pick("title").replace(/\s+/g, " "),
          authors: [...chunk.matchAll(/<name>(.*?)<\/name>/g)].map((m) => m[1]).join(", ").slice(0, 300),
          journal: "arXiv", year: Number(pick("published").slice(0, 4)) || null,
          abstract: pick("summary").replace(/\s+/g, " ").slice(0, 2000),
        });
      }
    }
  } catch (error) {
    console.warn(`[push] arXiv 抓取失败（${keyword}）:`, error.message);
  }
  return out;
}

/** 去重入库（doi/arxiv_id/标题归一）；返回本轮新增 papers 行 */
async function upsertCandidates(cands) {
  const pg = getPg();
  const fresh = [];
  for (const c of cands) {
    const normTitle = c.title.toLowerCase().replace(/\s+/g, " ").trim();
    const dup = await pg.query(
      `SELECT id FROM papers WHERE
         ($1::text IS NOT NULL AND arxiv_id = $1) OR ($2::text IS NOT NULL AND doi = $2) OR lower(title) = $3
       LIMIT 1`,
      [c.arxiv_id ?? null, c.doi ?? null, normTitle],
    );
    if (dup.rows[0]) continue;
    const inserted = await pg.query(
      `INSERT INTO papers (doi, arxiv_id, title, authors, journal, year, abstract, tags)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
       ON CONFLICT (arxiv_id) WHERE arxiv_id IS NOT NULL DO NOTHING
       RETURNING *`,
      [c.doi ?? null, c.arxiv_id ?? null, c.title, c.authors ?? "", c.journal ?? "", c.year ?? null, c.abstract ?? "", []],
    );
    if (inserted.rows[0]) fresh.push(inserted.rows[0]);
  }
  return fresh;
}

async function makeDigest(keyword, fresh) {
  const lines = fresh.map((p) => `标题：${p.title}\n摘要：${(p.abstract ?? "").slice(0, 300)}`).join("\n\n");
  const summary = await streamChat({
    systemPrompt: "你是论文推送助手。根据给定的新论文列表写一段今日 digest：先说今日命中几篇，再每篇一句话点题，口吻简洁。",
    messages: [{ role: "user", content: `订阅关键词「${keyword}」，今日新增：\n${lines}` }],
  });
  return `**流光咖啡馆 · 论文 digest**\n> 关键词：${keyword} ｜ 新增 ${fresh.length} 篇\n\n${summary}`;
}

/** 主入口：手动触发（run-now）与定时器共用。force=1 绕过 push_key 查重（重推场景） */
export async function runDailyDigest({ force = false } = {}) {
  const pg = getPg();
  const pushKey = todayKey();

  // 幂等：今天推过就不再打扰（白皮书：重复触发不重复推送）
  if (!force) {
    const { rows: done } = await pg.query("SELECT * FROM push_logs WHERE push_key = $1 AND ok = true", [pushKey]);
    if (done[0]) return { skipped: true, push_key: pushKey, detail: "今日已推送过" };
  }

  const { rows: subs } = await pg.query("SELECT * FROM subscriptions WHERE enabled = true ORDER BY id");
  let allFresh = [];
  for (const sub of subs) {
    const run = await pg.query(
      "INSERT INTO crawl_runs (keyword, status) VALUES ($1, 'running') RETURNING id", [sub.keyword],
    );
    try {
      const cands = await crawlKeyword(sub.keyword);
      const fresh = await upsertCandidates(cands);
      await pg.query(
        "UPDATE crawl_runs SET status = 'done', finished_at = now(), found_count = $2, new_count = $3 WHERE id = $1",
        [run.rows[0].id, cands.length, fresh.length],
      );
      allFresh = allFresh.concat(fresh.map((p) => ({ ...p, keyword: sub.keyword })));
    } catch (error) {
      await pg.query(
        "UPDATE crawl_runs SET status = 'failed', finished_at = now(), error = $2 WHERE id = $1",
        [run.rows[0].id, error.message.slice(0, 300)],
      );
    }
  }

  const text = allFresh.length
    ? (await Promise.all([...new Set(allFresh.map((p) => p.keyword))].map(async (kw) => {
        const digest = await makeDigest(kw, allFresh.filter((p) => p.keyword === kw));
        return digest;
      }))).join("\n\n---\n\n")
    : "**流光咖啡馆 · 论文 digest**\n\n今日无新论文。";

  const result = await notify(text);
  await pg.query(
    `INSERT INTO push_logs (push_key, channel, ok, detail, new_count) VALUES ($1,$2,$3,$4,$5)
     ON CONFLICT (push_key) DO UPDATE SET channel = $2, ok = $3, detail = $4, new_count = $5, created_at = now()`,
    [pushKey, result.channel, result.ok, result.detail, allFresh.length],
  );
  return { skipped: false, push_key: pushKey, pushed: result.ok, channel: result.channel, new_count: allFresh.length, detail: result.detail };
}

/* ---------- 订阅与触发的 HTTP 路由 ---------- */
const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });
const keyOf = (ctx) => JSON.stringify(ctx.principal);

export function pushRoutes() {
  // 批 3：成员订阅推送归 papers 域的应用门槛（网关单点）
  // 其中 requireAdmin 的三路由是两层叠加：admin 角色 + papers 授权（默认种子下语义一致）
  return gateApp("papers", {
    "GET /api/push/subscriptions": async (_r, ctx) => {
      const { rows } = await getPg().query(
        "SELECT * FROM subscriptions WHERE user_id = $1 ORDER BY id", [keyOf(ctx)]);
      return json({ subscriptions: rows });
    },
    "POST /api/push/subscriptions": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const keyword = String(body?.keyword ?? "").trim();
      if (!keyword || keyword.length > 50) return bad(400, "关键词不对");
      try {
        const { rows } = await getPg().query(
          "INSERT INTO subscriptions (user_id, keyword) VALUES ($1,$2) RETURNING *", [keyOf(ctx), keyword]);
        return json({ subscription: rows[0] }, 201);
      } catch {
        return bad(409, "这个关键词已经在订阅里");
      }
    },
    "DELETE /api/push/subscriptions/:id": async (request, ctx) => {
      const r = await getPg().query("DELETE FROM subscriptions WHERE id = $1 AND user_id = $2 RETURNING id", [request.params.id, keyOf(ctx)]);
      return r.rows[0] ? json({ ok: true }) : bad(404, "订阅不存在");
    },
    "PATCH /api/push/subscriptions/:id": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const r = await getPg().query(
        "UPDATE subscriptions SET enabled = COALESCE($3, enabled) WHERE id = $1 AND user_id = $2 RETURNING *",
        [request.params.id, keyOf(ctx), typeof body?.enabled === "boolean" ? body.enabled : null]);
      return r.rows[0] ? json({ subscription: r.rows[0] }) : bad(404, "订阅不存在");
    },

    // 手动触发一轮（验收/补推用；幂等：今日推过会跳过，force=1 重推）
    // 角色门槛：批 2 起一律经网关 requireAdmin（白皮书 §12 单点判断）
    "POST /api/push/run-now": requireAdmin(async (request) => {
      const body = await request.json().catch(() => ({}));
      const result = await runDailyDigest({ force: body?.force === true });
      return json({ result });
    }),

    "GET /api/push/logs": requireAdmin(async () => {
      const { rows } = await getPg().query("SELECT * FROM push_logs ORDER BY created_at DESC LIMIT 30");
      return json({ logs: rows });
    }),
    "GET /api/push/crawl-runs": requireAdmin(async () => {
      const { rows } = await getPg().query("SELECT * FROM crawl_runs ORDER BY started_at DESC LIMIT 30");
      return json({ runs: rows });
    }),
  });
}

/* ---------- 定时器：主程序内，每日早 8 点（本地时区）；不开新进程 ---------- */
let timer = null;
function msUntilNext8am() {
  const now = new Date();
  const next = new Date(now);
  next.setHours(8, 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  return next - now;
}
export function startPushScheduler() {
  if (timer || process.env.PUSH_SCHEDULER === "off") return;
  const tick = async () => {
    try {
      const r = await runDailyDigest();
      console.log(`[push] 定时 digest：${r.skipped ? "今日已推，跳过" : r.pushed ? `已推送（${r.channel}，新增 ${r.new_count}）` : `推送失败：${r.detail}`}`);
    } catch (error) {
      console.error("[push] 定时 digest 异常:", error.message);
    } finally {
      timer = setTimeout(tick, msUntilNext8am());
      timer.unref?.();
    }
  };
  timer = setTimeout(tick, msUntilNext8am());
  timer.unref?.();
  console.log("[push] 定时推送已排程（每日早 8 点）");
}
