// 只读工具注册表（白皮书 §09 方案 C + §12 危险动作隔离）
// 铁规矩：这里注册的只有只读查询工具——写操作根本没有工具可调，网关结构性拒绝；
// 密钥不进工具闭包；每次调用经 beforeToolCall 复核角色并落 audit_log。
import { getPg } from "../db.mjs";

const keyOf = (ctx) => JSON.stringify(ctx.principal);

const t = (name, label, description, parameters, execute, opts = {}) => ({ name, label, description, parameters, execute, ...opts });

/* ---------- 记账只读 ---------- */
const moneyMonthSummary = (ctx) => t(
  "money_month_summary", "月度收支汇总", "查询某月个人或家庭的收入/支出合计与笔数（只读）",
  { type: "object", properties: { month: { type: "string", description: "YYYY-MM，省略=本月" }, view: { type: "string", enum: ["personal", "family"], description: "personal=自己的账+自己记的 shared；family=两人全部 shared" } } },
  async (_id, args) => {
    const userId = keyOf(ctx);
    const month = /^\d{4}-\d{2}$/.test(args?.month ?? "") ? args.month : new Date().toISOString().slice(0, 7);
    const view = args?.view === "family" ? "family" : "personal";
    const scope = view === "family"
      ? "($1::text IS NOT NULL AND t.shared = true)"
      : "((t.user_id = $1 AND t.shared = false) OR (t.created_by = $1 AND t.shared = true))";
    const [y, m] = month.split("-").map(Number);
    const to = `${month}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`;
    const { rows } = await getPg().query(
      `SELECT t.type, SUM(t.amount_fen)::bigint AS total, COUNT(*)::int AS n FROM transactions t
       WHERE ${scope} AND t.occurred_on BETWEEN $2 AND $3 GROUP BY t.type`,
      [userId, `${month}-01`, to],
    );
    return { content: [{ type: "text", text: JSON.stringify({ month, view, summary: rows }) }] };
  },
);

const moneyCategoryQuery = (ctx) => t(
  "money_category_query", "分类支出查询", "按时间段+分类+收支类型聚合查账（只读，模型不写 SQL）",
  { type: "object", properties: {
    from: { type: "string", description: "YYYY-MM-DD" }, to: { type: "string", description: "YYYY-MM-DD" },
    category: { type: "string", description: "分类名，如 餐饮" },
    type: { type: "string", enum: ["income", "expense"] },
    view: { type: "string", enum: ["personal", "family"] },
  }, required: ["from", "to"] },
  async (_id, args) => {
    const userId = keyOf(ctx);
    const cats = await getPg().query("SELECT * FROM categories WHERE user_id = $1", [userId]);
    const categoryId = args?.category ? cats.rows.find((c) => c.name === args.category)?.id : null;
    if (args?.category && !categoryId) throw new Error(`分类「${args.category}」不存在`);
    const view = args?.view === "family" ? "family" : "personal";
    const scope = view === "family"
      ? "($1::text IS NOT NULL AND t.shared = true)"
      : "((t.user_id = $1 AND t.shared = false) OR (t.created_by = $1 AND t.shared = true))";
    const conds = [scope];
    const params = [userId, args.from, args.to];
    let i = 4;
    if (args?.type) { conds.push(`t.type = $${i++}`); params.push(args.type); }
    if (categoryId) { conds.push(`t.category_id = $${i++}`); params.push(categoryId); }
    const { rows } = await getPg().query(
      `SELECT COALESCE(SUM(t.amount_fen),0)::bigint AS total, COUNT(*)::int AS n FROM transactions t
       WHERE ${conds.join(" AND ")} AND t.occurred_on BETWEEN $2 AND $3`, params);
    return { content: [{ type: "text", text: JSON.stringify({ total: Number(rows[0].total), n: rows[0].n, view }) }] };
  },
);

/* ---------- 论文只读 ---------- */
const papersSearch = (ctx) => t(
  "papers_search", "论文库检索", "在我可见的论文库（自己的+共享的）里按关键词搜标题和摘要（只读）",
  { type: "object", properties: { keyword: { type: "string" }, limit: { type: "number" } }, required: ["keyword"] },
  async (_id, args) => {
    const userId = keyOf(ctx);
    const { rows } = await getPg().query(
      `SELECT i.id, i.phase, i.shared, p.title, p.authors, p.year, left(p.abstract, 300) AS abstract
       FROM library_items i JOIN papers p ON p.id = i.paper_id
       WHERE (i.user_id = $1 OR i.shared = true) AND (p.title ILIKE $2 OR p.abstract ILIKE $2)
       ORDER BY i.updated_at DESC LIMIT $3`,
      [userId, `%${String(args.keyword).slice(0, 50)}%`, Math.min(Number(args.limit) || 5, 10)],
    );
    return { content: [{ type: "text", text: JSON.stringify({ hits: rows }) }] };
  },
);

const viewPushLogs = (ctx) => t(
  "view_push_logs", "推送记录", "查看每日 digest 推送记录（仅主人；只读）",
  { type: "object", properties: {} },
  async () => {
    const { rows } = await getPg().query("SELECT push_key, channel, ok, new_count, created_at FROM push_logs ORDER BY created_at DESC LIMIT 10");
    return { content: [{ type: "text", text: JSON.stringify({ logs: rows }) }] };
  },
  { ownerOnly: true },
);

/** 工具装载：按会话应用给工具集；总对话（hub）挂全部只读工具。
 *  ownerOnly 工具照常装载（模型看得见），调用前由 beforeToolCall 按角色复核拒绝——
 *  白皮书 §12：写死能用哪些 + 调用前再查一遍角色，双保险。 */
export function toolsFor(app, ctx) {
  const all = [moneyMonthSummary(ctx), moneyCategoryQuery(ctx), papersSearch(ctx), viewPushLogs(ctx)];
  switch (app) {
    case "hub": return all;
    case "money": return all.filter((x) => x.name.startsWith("money_"));
    case "papers": return all.filter((x) => x.name.startsWith("papers_"));
    default: return []; // 普通对话：agent 模式先不带工具，后续按域加
  }
}
