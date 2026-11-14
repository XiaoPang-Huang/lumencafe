// 记账应用（第 2 批，白皮书 §08 记账拍板实现）
// 2a 表单增删改查 + 月份统计；2b AI 记一笔（单次调用出草稿，确认才入账，request_id 幂等）；
// 2c 对话统计（模型只出三条件，代码拼参数化聚合，结果交回模型说人话，不让模型写 SQL）
import { getPg } from "../db.mjs";
import { conv as chatConv, msg as chatMsg } from "./chat-db.mjs";
import { streamChat } from "./llm.mjs";

const PRESET_EXPENSE = ["餐饮", "交通", "购物", "居住", "日用", "娱乐", "医疗", "教育", "人情", "其他支出"];
const PRESET_INCOME = ["工资", "奖金", "兼职", "理财", "其他收入"];

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value) => ({ kind: "json", value });
const keyOf = (ctx) => JSON.stringify(ctx.principal);

/* ---------- 分类 ---------- */
async function ensureCategories(userId) {
  const pg = getPg();
  const { rows } = await pg.query("SELECT COUNT(*)::int AS n FROM categories WHERE user_id = $1", [userId]);
  if (rows[0].n > 0) return;
  let sort = 0;
  for (const name of PRESET_EXPENSE) {
    await pg.query("INSERT INTO categories (user_id, name, kind, built_in, sort) VALUES ($1,$2,'expense',true,$3)", [userId, name, sort++]);
  }
  sort = 0;
  for (const name of PRESET_INCOME) {
    await pg.query("INSERT INTO categories (user_id, name, kind, built_in, sort) VALUES ($1,$2,'income',true,$3)", [userId, name, sort++]);
  }
}

const listCategories = async (userId) => {
  await ensureCategories(userId);
  const { rows } = await getPg().query(
    "SELECT * FROM categories WHERE user_id = $1 ORDER BY kind, sort, id", [userId]);
  return rows;
};

/* ---------- 可见范围（白皮书：个人=自己私人+自己记的shared；家庭=两人全部shared） ---------- */
/* $1 恒被引用并显式定型：避免 family 分支 $1 闲置导致 PG 参数类型推断失败 */
const VIEW_SQL = {
  personal: "((t.user_id = $1::text AND t.shared = false) OR (t.created_by = $1::text AND t.shared = true))",
  family: "($1::text IS NOT NULL AND t.shared = true)",
};

/* ---------- AI：单次 JSON 调用 ---------- */
async function chatJson(systemPrompt, userText) {
  const text = await streamChat({ messages: [{ role: "user", content: userText }], systemPrompt });
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("模型没返回 JSON");
  return JSON.parse(m[0]);
}

const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/** 单次调用：把一句话分类并解析成 记账草稿 或 统计三条件（白名单校验前） */
async function parseIntent(text, categories) {
  const expense = categories.filter((c) => c.kind === "expense" && !c.hidden).map((c) => c.name);
  const income = categories.filter((c) => c.kind === "income" && !c.hidden).map((c) => c.name);
  return chatJson(
    `你是记账助手。把用户输入解析成一个 JSON 对象（只输出 JSON，不要别的）。
意图二选一：
1) 记一笔：{"intent":"record","amount_fen":<正整数分>,"type":"expense|income","category":"<必须从给定清单选>","occurred_on":"YYYY-MM-DD","shared":<提到两人/全家/家庭/共同开销时为 true，否则 false>,"note":"<备注或空串>","confidence":0到1}
2) 统计：{"intent":"stats","from":"YYYY-MM-DD","to":"YYYY-MM-DD","category":null或"<清单中名称>","type":null或"income|expense","view":"<两人/全家/家庭 出现时是 family，否则 personal>"}
今天是 ${todayStr()}。「昨天/前天/上周/上个月」等相对日期按今天换算。金额必须换算成分（1 元 = 100 分）。
支出分类清单：${expense.join("、")}
收入分类清单：${income.join("、")}
解析不了金额时 amount_fen 给 null。`,
    text,
  );
}

const validDate = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s));

/** 白名单校验 + 代码聚合（模型不碰 SQL、不碰账本数据） */
async function runStatsQuery(userId, p) {
  if (!validDate(p.from) || !validDate(p.to) || p.from > p.to) return { error: "时间段我没听懂，换个说法比如「这个月」" };
  const view = p.view === "family" ? "family" : "personal";
  if (p.type != null && !["income", "expense"].includes(p.type)) return { error: "收支类型只支持收入或支出" };
  const categories = await listCategories(userId);
  let categoryId = null;
  if (p.category != null) {
    const hit = categories.find((c) => c.name === p.category);
    if (!hit) return { error: `分类「${p.category}」不在你的分类里` };
    categoryId = hit.id;
  }
  const conds = [VIEW_SQL[view]];
  const params = [userId, p.from, p.to];
  let i = 4;
  if (p.type) { conds.push(`t.type = $${i++}`); params.push(p.type); }
  if (categoryId) { conds.push(`t.category_id = $${i++}`); params.push(categoryId); }
  const { rows } = await getPg().query(
    `SELECT COALESCE(SUM(t.amount_fen),0)::bigint AS total, COUNT(*)::int AS n
     FROM transactions t WHERE ${conds.join(" AND ")} AND t.occurred_on BETWEEN $2 AND $3`,
    params,
  );
  const { rows: details } = await getPg().query(
    `SELECT t.id, t.amount_fen, t.type, t.note, t.occurred_on::text AS occurred_on, t.shared, c.name AS category_name
     FROM transactions t JOIN categories c ON c.id = t.category_id
     WHERE ${conds.join(" AND ")} AND t.occurred_on BETWEEN $2 AND $3
     ORDER BY t.occurred_on DESC, t.id DESC LIMIT 20`,
    params,
  );
  return { total: Number(rows[0].total), n: rows[0].n, view, details };
}

const fen2yuan = (fen) => (fen / 100).toFixed(2);

async function sayStats(text, result) {
  const detailLines = result.details.slice(0, 8)
    .map((d) => `${d.occurred_on.slice(0, 10)} ${d.category_name} ${fen2yuan(d.amount_fen)}元${d.note ? "（" + d.note + "）" : ""}`).join("\n");
  return streamChat({
    messages: [{
      role: "user",
      content: `用户问：「${text}」\n聚合结果：合计 ${fen2yuan(result.total)} 元，共 ${result.n} 笔。${result.view === "family" ? "（家庭视图，两人共享账）" : "（个人视图）"}\n明细：\n${detailLines || "无"}\n\n请用一两句口语化中文回答，必须带金额（元）和笔数，只根据给定数据回答，不要编造。明细最多提三笔，更多就说「明细可回记账页看」。`,
    }],
    systemPrompt: "你是记账助手，回答简短口语化。",
  });
}

/* ---------- 记账对话（应用专属会话，消息存 SQLite 框架态） ---------- */
async function moneyConversation(ownerKey) {
  return chatConv.ensureApp(ownerKey, "money", "记账助手");
}

/* ---------- 路由 ---------- */
export function moneyRoutes() {
  return {
    "GET /api/money/categories": async (_r, ctx) =>
      json({ categories: await listCategories(keyOf(ctx)) }),

    "POST /api/money/categories": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const name = String(body?.name ?? "").trim();
      if (!name || !["expense", "income"].includes(body?.kind)) return bad(400, "分类名或类型不对");
      try {
        const { rows } = await getPg().query(
          "INSERT INTO categories (user_id, name, kind, sort) VALUES ($1,$2,$3,99) RETURNING *",
          [keyOf(ctx), name.slice(0, 12), body.kind],
        );
        return json({ category: rows[0] }, 201);
      } catch {
        return bad(409, "同名分类已存在");
      }
    },

    "PATCH /api/money/categories/:id": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const r = await getPg().query(
        "UPDATE categories SET name = COALESCE($3, name), hidden = COALESCE($4, hidden) WHERE id = $1 AND user_id = $2 RETURNING *",
        [request.params.id, keyOf(ctx), body?.name ?? null, typeof body?.hidden === "boolean" ? body.hidden : null],
      );
      return r.rows[0] ? json({ category: r.rows[0] }) : bad(404, "分类不存在");
    },

    "DELETE /api/money/categories/:id": async (request, ctx) => {
      const pg = getPg();
      const { rows } = await pg.query("SELECT * FROM categories WHERE id = $1 AND user_id = $2", [request.params.id, keyOf(ctx)]);
      if (!rows[0]) return bad(404, "分类不存在");
      if (rows[0].built_in) return bad(400, "预置分类不可删除，可以改名或隐藏");
      const used = await pg.query("SELECT COUNT(*)::int AS n FROM transactions WHERE category_id = $1", [request.params.id]);
      if (used.rows[0].n > 0) return bad(400, "分类下还有账目，先改账再删");
      await pg.query("DELETE FROM categories WHERE id = $1", [request.params.id]);
      return json({ ok: true });
    },

    // 账目：按月 + 视图查询（列表 + 汇总 + 分类条形 + 近6月趋势）
    "GET /api/money/entries": async (request, ctx) => {
      const userId = keyOf(ctx);
      const month = /^\d{4}-\d{2}$/.test(request.query.get("month") ?? "") ? request.query.get("month") : todayStr().slice(0, 7);
      const view = request.query.get("view") === "family" ? "family" : "personal";
      const pg = getPg();
      const [from, to] = [`${month}-01`, monthEnd(month)];
      const scope = VIEW_SQL[view];
      const { rows: entries } = await pg.query(
        `SELECT t.id, t.created_by, t.amount_fen, t.type, t.category_id, t.note, t.occurred_on::text AS occurred_on, t.shared, t.request_id, t.created_at, c.name AS category_name
         FROM transactions t JOIN categories c ON c.id = t.category_id
         WHERE ${scope} AND t.occurred_on BETWEEN $2 AND $3 ORDER BY t.occurred_on DESC, t.id DESC LIMIT 500`,
        [userId, from, to],
      );
      const { rows: summary } = await pg.query(
        `SELECT t.type, COALESCE(SUM(t.amount_fen),0)::bigint AS total, COUNT(*)::int AS n
         FROM transactions t WHERE ${scope} AND t.occurred_on BETWEEN $2 AND $3 GROUP BY t.type`,
        [userId, from, to],
      );
      const { rows: byCategory } = await pg.query(
        `SELECT c.name, c.kind, COALESCE(SUM(t.amount_fen),0)::bigint AS total
         FROM transactions t JOIN categories c ON c.id = t.category_id
         WHERE ${scope} AND t.occurred_on BETWEEN $2 AND $3 GROUP BY c.name, c.kind ORDER BY total DESC`,
        [userId, from, to],
      );
      // 近 6 月趋势
      const months = [];
      const [y, mo] = month.split("-").map(Number);
      for (let i = 5; i >= 0; i--) {
        const d = new Date(y, mo - 1 - i, 1);
        months.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
      }
      const { rows: trend } = await pg.query(
        `SELECT to_char(t.occurred_on, 'YYYY-MM') AS m, t.type, COALESCE(SUM(t.amount_fen),0)::bigint AS total
         FROM transactions t WHERE ${scope} AND to_char(t.occurred_on, 'YYYY-MM') = ANY($2::text[])
         GROUP BY 1, 2`,
        [userId, months],
      );
      return json({
        month, view, entries,
        summary: Object.fromEntries(summary.map((s) => [s.type, { total: Number(s.total), n: s.n }])),
        by_category: byCategory.map((r) => ({ ...r, total: Number(r.total) })),
        trend: months.map((m) => ({
          month: m,
          expense: Number(trend.find((t) => t.m === m && t.type === "expense")?.total ?? 0),
          income: Number(trend.find((t) => t.m === m && t.type === "income")?.total ?? 0),
        })),
      });
    },

    // 写账（表单与 AI 确认同一条路径）：request_id 幂等，重复提交返回原账
    "POST /api/money/entries": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const userId = keyOf(ctx);
      const amount = Number(body?.amount_fen);
      const type = body?.type;
      const categoryId = Number(body?.category_id);
      const occurredOn = body?.occurred_on;
      const reqId = body?.request_id;
      if (!Number.isInteger(amount) || amount <= 0) return bad(400, "金额必须是不为零的正数（分）");
      if (!["income", "expense"].includes(type)) return bad(400, "收支类型不对");
      if (!validDate(occurredOn)) return bad(400, "日期不合法");
      if (typeof reqId !== "string" || !reqId) return bad(400, "缺少请求标识");
      const { rows: cats } = await getPg().query("SELECT * FROM categories WHERE id = $1 AND user_id = $2", [categoryId, userId]);
      if (!cats[0]) return bad(400, "分类不存在");
      const shared = body?.shared === true;
      const note = String(body?.note ?? "").slice(0, 100);
      const { rows } = await getPg().query(
        `INSERT INTO transactions (user_id, created_by, amount_fen, type, category_id, note, occurred_on, shared, request_id)
         VALUES ($1,$1,$2,$3,$4,$5,$6,$7,$8)
         ON CONFLICT (request_id) DO UPDATE SET request_id = EXCLUDED.request_id
         RETURNING *, (xmax = 0) AS inserted`,
        [userId, amount, type, categoryId, note, occurredOn, shared, reqId],
      );
      const entry = await getPg().query(
        `SELECT t.id, t.created_by, t.amount_fen, t.type, t.category_id, t.note, t.occurred_on::text AS occurred_on, t.shared, t.request_id, t.created_at, c.name AS category_name
         FROM transactions t JOIN categories c ON c.id = t.category_id WHERE t.id = $1`,
        [rows[0].id],
      );
      return json({ entry: entry.rows[0], duplicated: !rows[0].inserted });
    },

    "PATCH /api/money/entries/:id": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const userId = keyOf(ctx);
      const { rows } = await getPg().query("SELECT * FROM transactions WHERE id = $1", [request.params.id]);
      const t = rows[0];
      if (!t) return bad(404, "账目不存在");
      if (!t.shared && t.user_id !== userId) return bad(403, "私人账目仅本人可改");
      const amount = body?.amount_fen != null ? Number(body.amount_fen) : t.amount_fen;
      if (!Number.isInteger(amount) || amount <= 0) return bad(400, "金额必须是不为零的正数（分）");
      const r = await getPg().query(
        `UPDATE transactions SET amount_fen = $2, type = $3, category_id = $4, note = $5, occurred_on = $6, shared = $7
         WHERE id = $1 RETURNING id, created_by, amount_fen, type, category_id, note, occurred_on::text AS occurred_on, shared, request_id, created_at`,
        [t.id, amount, body?.type ?? t.type, body?.category_id ?? t.category_id,
         String(body?.note ?? t.note).slice(0, 100), validDate(body?.occurred_on) ? body.occurred_on : t.occurred_on,
         typeof body?.shared === "boolean" ? body.shared : t.shared],
      );
      const withCat = await getPg().query(
        "SELECT c.name AS category_name FROM categories c WHERE c.id = $1", [r.rows[0].category_id]);
      return json({ entry: { ...r.rows[0], category_name: withCat.rows[0]?.name ?? "" } });
    },

    "DELETE /api/money/entries/:id": async (request, ctx) => {
      const userId = keyOf(ctx);
      const { rows } = await getPg().query("SELECT * FROM transactions WHERE id = $1", [request.params.id]);
      const t = rows[0];
      if (!t) return bad(404, "账目不存在");
      if (!t.shared && t.user_id !== userId) return bad(403, "私人账目仅本人可删");
      await getPg().query("DELETE FROM transactions WHERE id = $1", [t.id]);
      return json({ ok: true });
    },

    // 记账专属对话：一句话进来 → 记一笔草稿 或 统计回答
    "POST /api/money/ai": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const text = String(body?.text ?? "").trim();
      const reqId = body?.req_id;
      if (!text || typeof reqId !== "string" || !reqId) return bad(400, "缺少内容或请求标识");
      const userId = keyOf(ctx);
      const c = await moneyConversation(userId);
      const saved = chatMsg.saveUser(c.id, { reqId, content: text });
      await chatConv.touch(userId, c.id);

      let reply;
      let kind = "text";
      let details = null;
      try {
        const parsed = await parseIntent(text, await listCategories(userId));
        if (parsed?.intent === "record") {
          const amount = Number(parsed.amount_fen);
          const cats = await listCategories(userId);
          const category = cats.find((x) => x.name === parsed.category);
          if (!Number.isInteger(amount) || amount <= 0 || !category) {
            reply = "没听懂这笔账：金额或分类对不上。补一句「比如：午饭 32 元」，或者点「记一笔」用表单。";
          } else {
            kind = "draft";
            details = {
              amount_fen: amount,
              type: category.kind,
              category_id: category.id,
              category_name: category.name,
              occurred_on: validDate(parsed.occurred_on) ? parsed.occurred_on : todayStr(),
              shared: parsed.shared === true,
              note: String(parsed.note ?? "").slice(0, 100),
              request_id: reqId, // 确认入账沿用原请求标识 → 幂等
              confidence: Number(parsed.confidence ?? 0),
            };
            reply = JSON.stringify(details);
          }
        } else if (parsed?.intent === "stats") {
          const result = await runStatsQuery(userId, parsed);
          if (result.error) {
            reply = `${result.error}。统计只支持「时间段 + 分类 + 收支类型」，改账请用记账页表单。`;
          } else {
            kind = "stats";
            details = result;
            reply = await sayStats(text, result);
          }
        } else {
          reply = "没听懂。记一笔就说「午饭 32 元」，查账就说「这个月吃饭花了多少」。";
        }
      } catch (error) {
        console.error("[money] AI 解析失败:", error.message);
        reply = "这次没解析成功，请换个说法再试，或用表单记一笔。";
      }
      const message = chatMsg.saveAssistant(c.id, { reqId: `ai-${reqId}`, content: reply, kind });
      return json({ message, details, user_message: saved.message, conversation: c });
    },

    "GET /api/money/conversation": async (_r, ctx) =>
      json({ conversation: await moneyConversation(keyOf(ctx)) }),
  };
}

function monthEnd(month) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m, 0);
  return `${month}-${String(d.getDate()).padStart(2, "0")}`;
}
