// 模型 & API 管理路由（需求-模型API管理-v1.md §5）
// 三组：管理端（requireAdmin+gateApp admin）/ 个人（登录即可，owner 强制=自己）/ 前台可见列表在 chat.mjs 消费
// 连通测试与一键拉模型直接发上游 HTTP；密钥只用于请求头，不落日志。
import { getPg } from "../db.mjs";
import { requireAdmin, gateApp, roleOf } from "./gateway.mjs";
import { userByPrincipal } from "./auth.mjs";
import { decryptSecret } from "./secret.mjs";
import * as db from "./model-db.mjs";
import { reloadModels } from "./llm.mjs";

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });

const PROTOCOLS = ["openai", "anthropic", "mineru"];
const AUTH_TYPES = ["bearer", "header", "query", "none"];
const PLAN_TYPES = ["official", "tokenplan", "agentplan", "third_party"];
const CODE_RE = /^[a-z][a-z0-9_-]{1,31}$/;

/** 当前用户 id（无账号的纯邀请成员 → null） */
async function userIdOf(ctx) {
  const u = await userByPrincipal(ctx);
  return u ? u.id : null;
}

/** 按 auth_type 组装请求头/query */
function authHeaders(provider, key) {
  if (!key || provider.authType === "none") return {};
  if (provider.authType === "bearer") return { Authorization: `Bearer ${key}` };
  if (provider.authType === "header") {
    const name = provider.authConfig?.headerName || "X-API-Key";
    const prefix = provider.authConfig?.headerPrefix || "";
    return { [name]: prefix ? `${prefix} ${key}` : key };
  }
  return {};
}
function authQuery(provider, key) {
  if (key && provider.authType === "query") {
    return `?${provider.authConfig?.queryParam || "api_key"}=${encodeURIComponent(key)}`;
  }
  return "";
}

/** 连通测试 + 一键拉模型共用的上游请求 */
async function probeProvider(provider, plan, key) {
  const base = (plan?.baseUrl || provider.baseUrl || "").replace(/\/+$/, "");
  if (!base) return { ok: false, error: "未配置接口地址" };
  const headers = { ...authHeaders(provider, key) };
  let url; let expectModels = true;
  if (provider.protocol === "openai") {
    url = `${base}/models${authQuery(provider, key)}`;
  } else if (provider.protocol === "anthropic") {
    url = `${base}/v1/models${authQuery(provider, key)}`;
    headers["x-api-key"] = key ?? "";
    headers["anthropic-version"] = "2023-06-01";
    delete headers.Authorization;
  } else {
    // mineru：健康检查端点（无统一规范，探测根路径与 /health）
    url = `${base}/health`;
    expectModels = false;
  }
  const t0 = Date.now();
  try {
    const res = await fetch(url, { headers, signal: AbortSignal.timeout(10000) });
    const latency = Date.now() - t0;
    const text = await res.text().catch(() => "");
    if (!res.ok) {
      return { ok: false, latencyMs: latency, httpStatus: res.status, error: `上游 ${res.status}：${text.slice(0, 160)}` };
    }
    let models = null;
    if (expectModels) {
      try {
        const data = JSON.parse(text);
        models = Array.isArray(data.data) ? data.data.map((m) => String(m.id ?? m.name ?? "")).filter(Boolean) : [];
      } catch { models = []; }
    }
    return { ok: true, latencyMs: latency, httpStatus: res.status, models, modelsCount: models?.length ?? null };
  } catch (err) {
    return { ok: false, latencyMs: Date.now() - t0, error: `连接失败：${err.message}` };
  }
}

/** 个人供应商归属校验：非本人 → 404（不暴露存在性） */
async function ownProviderOr404(ctx, id) {
  const p = await db.getProvider(id);
  const uid = await userIdOf(ctx);
  if (!p || p.scope !== "personal" || p.ownerUserId !== uid) return { error: bad(404, "供应商不存在") };
  return { provider: p };
}

function validateProviderBody(body, { partial = false } = {}) {
  const out = {};
  if (!partial || body.name !== undefined) {
    out.name = String(body?.name ?? "").trim();
    if (!out.name) return { error: "名称必填" };
  }
  if (!partial || body.code !== undefined) {
    out.code = String(body?.code ?? "").trim().toLowerCase();
    if (!CODE_RE.test(out.code)) return { error: "code 需为 2-32 位小写字母/数字/下划线/连字符，字母开头" };
  }
  if (!partial || body.protocol !== undefined) {
    out.protocol = body?.protocol;
    if (!PROTOCOLS.includes(out.protocol)) return { error: "协议只支持 openai / anthropic / mineru" };
  }
  if (!partial || body.baseUrl !== undefined) {
    out.baseUrl = String(body?.baseUrl ?? "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//.test(out.baseUrl)) return { error: "接口地址需以 http(s):// 开头" };
  }
  if (body.authType !== undefined) {
    out.authType = body.authType;
    if (!AUTH_TYPES.includes(out.authType)) return { error: "鉴权方式只支持 bearer / header / query / none" };
  }
  if (body.authConfig !== undefined) out.authConfig = body.authConfig ?? {};
  if (body.key !== undefined) out.key = String(body.key ?? "");
  if (body.remark !== undefined) out.remark = String(body.remark ?? "").trim().slice(0, 200);
  if (body.enabled !== undefined) out.enabled = body.enabled === true;
  return { value: out };
}

/* ================= 管理端 ================= */
function adminModelRoutes() {
  return {
    "GET /api/models/tree": requireAdmin(async () => {
      const providers = await db.listProviders({ scope: "system" });
      const tree = [];
      for (const p of providers) {
        const plans = await db.listPlans(p.id);
        const models = await db.listModels({ providerId: p.id });
        tree.push({ ...p, plans, models });
      }
      return json({ providers: tree });
    }),

    "POST /api/models/providers": requireAdmin(async (request) => {
      const body = await request.json().catch(() => ({}));
      const v = validateProviderBody(body);
      if (v.error) return bad(400, v.error);
      const dup = await getPg().query("SELECT 1 FROM model_providers WHERE code = $1", [v.value.code]);
      if (dup.rows[0]) return bad(409, "code 已存在");
      const provider = await db.createProvider({ ...v.value, scope: "system" });
      await reloadModels();
      return json({ provider }, 201);
    }),

    "PATCH /api/models/providers/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const p = await db.getProvider(id);
      if (!p || p.scope !== "system") return bad(404, "供应商不存在");
      const body = await request.json().catch(() => ({}));
      const v = validateProviderBody(body, { partial: true });
      if (v.error) return bad(400, v.error);
      const provider = await db.updateProvider(id, v.value);
      await reloadModels();
      return json({ provider });
    }),

    "DELETE /api/models/providers/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const p = await db.getProvider(id);
      if (!p || p.scope !== "system") return bad(404, "供应商不存在");
      await db.deleteProvider(id);
      await reloadModels();
      return json({ ok: true });
    }),

    "POST /api/models/providers/:id/test": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const p = await db.getProvider(id);
      if (!p || p.scope !== "system") return bad(404, "供应商不存在");
      const row = (await getPg().query("SELECT * FROM model_providers WHERE id = $1", [id])).rows[0];
      const key = decryptSecret(row.key_cipher);
      if (p.authType !== "none" && !key) return json({ ok: false, error: "未配置密钥" });
      return json(await probeProvider(p, null, key));
    }),

    "POST /api/models/plans": requireAdmin(async (request) => {
      const body = await request.json().catch(() => ({}));
      const providerId = Number(body?.providerId);
      const p = await db.getProvider(providerId);
      if (!p || p.scope !== "system") return bad(404, "供应商不存在");
      const name = String(body?.name ?? "").trim();
      if (!name) return bad(400, "套餐名必填");
      if (body?.planType && !PLAN_TYPES.includes(body.planType)) return bad(400, "套餐类型不合法");
      const plan = await db.createPlan({
        providerId, name, planType: body?.planType, baseUrl: body?.baseUrl,
        key: body?.key, rpmLimit: Math.max(0, Number(body?.rpmLimit) || 0),
        dailyLimit: Math.max(0, Number(body?.dailyLimit) || 0), remark: body?.remark,
      });
      return json({ plan }, 201);
    }),

    "PATCH /api/models/plans/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const plan = await db.getPlan(id);
      if (!plan) return bad(404, "套餐不存在");
      const body = await request.json().catch(() => ({}));
      const patch = {};
      if (body.name !== undefined) patch.name = String(body.name).trim() || plan.name;
      if (body.planType !== undefined) {
        if (!PLAN_TYPES.includes(body.planType)) return bad(400, "套餐类型不合法");
        patch.planType = body.planType;
      }
      if (body.baseUrl !== undefined) patch.baseUrl = String(body.baseUrl ?? "").trim().replace(/\/+$/, "");
      if (body.key !== undefined) patch.key = String(body.key ?? "");
      if (body.rpmLimit !== undefined) patch.rpmLimit = Math.max(0, Number(body.rpmLimit) || 0);
      if (body.dailyLimit !== undefined) patch.dailyLimit = Math.max(0, Number(body.dailyLimit) || 0);
      if (body.enabled !== undefined) patch.enabled = body.enabled === true;
      if (body.remark !== undefined) patch.remark = String(body.remark ?? "").trim().slice(0, 200);
      const updated = await db.updatePlan(id, patch);
      return json({ plan: updated });
    }),

    "DELETE /api/models/plans/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      if (!(await db.getPlan(id))) return bad(404, "套餐不存在");
      await db.deletePlan(id);
      await reloadModels();
      return json({ ok: true });
    }),

    "POST /api/models/fetch": requireAdmin(async (request) => {
      const body = await request.json().catch(() => ({}));
      const providerId = Number(body?.providerId);
      const p = await db.getProvider(providerId);
      if (!p || p.scope !== "system") return bad(404, "供应商不存在");
      const row = (await getPg().query("SELECT * FROM model_providers WHERE id = $1", [providerId])).rows[0];
      const key = decryptSecret(row.key_cipher);
      if (p.authType !== "none" && !key) return bad(400, "未配置密钥，无法拉取");
      const probe = await probeProvider(p, null, key);
      if (!probe.ok) return json({ ok: false, error: probe.error, latencyMs: probe.latencyMs }, 502);
      const planId = body?.planId != null ? Number(body.planId) : null;
      let created = 0; let updated = 0;
      for (const modelId of probe.models ?? []) {
        const before = await getPg().query("SELECT source FROM models WHERE provider_id = $1 AND model_id = $2", [providerId, modelId]);
        await db.createModel({ providerId, planId, modelId, displayName: modelId, source: "fetched" });
        if (before.rows[0]) updated++; else created++;
      }
      await reloadModels();
      return json({ ok: true, created, updated, total: (probe.models ?? []).length, latencyMs: probe.latencyMs });
    }),

    "PATCH /api/models/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const m = await db.getModel(id);
      if (!m) return bad(404, "模型不存在");
      const body = await request.json().catch(() => ({}));
      const patch = {};
      if (body.displayName !== undefined) patch.displayName = String(body.displayName).trim() || m.displayName;
      if (body.enabled !== undefined) patch.enabled = body.enabled === true;
      if (body.isCommon !== undefined) patch.isCommon = body.isCommon === true;
      if (body.contextWindow !== undefined) patch.contextWindow = body.contextWindow ? Number(body.contextWindow) : null;
      if (body.maxOutputTokens !== undefined) patch.maxOutputTokens = body.maxOutputTokens ? Number(body.maxOutputTokens) : null;
      if (body.inputPrice !== undefined) patch.inputPrice = body.inputPrice === null || body.inputPrice === "" ? null : Number(body.inputPrice);
      if (body.outputPrice !== undefined) patch.outputPrice = body.outputPrice === null || body.outputPrice === "" ? null : Number(body.outputPrice);
      if (body.supportsTools !== undefined) patch.supportsTools = body.supportsTools === true;
      if (body.supportsImages !== undefined) patch.supportsImages = body.supportsImages === true;
      if (body.displayOrder !== undefined) patch.displayOrder = Math.max(0, Number(body.displayOrder) || 0);
      // 思考强度：默认强度 null=未配置（对话开启时跟随厂商默认）；支持档位白名单校验
      if (body.thinking !== undefined) {
        patch.thinking = [null, "minimal", "low", "medium", "high", "xhigh", "max"].includes(body.thinking) ? body.thinking : null;
      }
      if (body.thinkingLevels !== undefined) {
        const ALLOWED = ["minimal", "low", "medium", "high", "xhigh", "max"];
        patch.thinkingLevels = (Array.isArray(body.thinkingLevels) ? body.thinkingLevels : []).filter((l) => ALLOWED.includes(l));
      }
      const model = await db.updateModel(id, patch);
      await reloadModels();
      return json({ model });
    }),

    "POST /api/models/batch": requireAdmin(async (request) => {
      const body = await request.json().catch(() => ({}));
      const ids = Array.isArray(body?.ids) ? body.ids.map(Number).filter(Number.isInteger) : [];
      if (!ids.length) return bad(400, "ids 必填");
      if (body?.op !== "enable" && body?.op !== "disable") return bad(400, "op 只支持 enable/disable");
      await db.batchUpdateModels(ids, { enabled: body.op === "enable" });
      await reloadModels();
      return json({ ok: true, count: ids.length });
    }),

    "DELETE /api/models/:id": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      if (!(await db.getModel(id))) return bad(404, "模型不存在");
      await db.deleteModel(id);
      await reloadModels();
      return json({ ok: true });
    }),

    "PUT /api/models/:id/grants": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      if (!(await db.getModel(id))) return bad(404, "模型不存在");
      const body = await request.json().catch(() => ({}));
      const grants = Array.isArray(body?.grants) ? body.grants : null;
      if (!grants) return bad(400, "grants 必填（数组，可空数组）");
      for (const g of grants) {
        if (g?.type !== "role" && g?.type !== "user") return bad(400, "授权类型只支持 role/user");
        if (g.type === "role" && !["admin", "member"].includes(g.grantee)) return bad(400, "角色只支持 admin/member");
      }
      await db.replaceGrants(id, grants);
      const model = await db.getModel(id);
      return json({ model });
    }),

    "GET /api/models/logs": requireAdmin(async (request) => {
      const modelId = request.query.get("model_id");
      const userId = request.query.get("user_id");
      const limit = request.query.get("limit");
      const logs = await db.listLogs({
        modelId: modelId ? Number(modelId) : null,
        userId: userId ? Number(userId) : null,
        limit: limit ? Number(limit) : 50,
      });
      return json({ logs });
    }),

    // 权限查询（学 WorkBuddy 企业版）：输入成员账号 → 他最终可见的模型清单（并集规则 R3）
    "GET /api/models/visibility": requireAdmin(async (request) => {
      const username = (request.query.get("username") || "").trim();
      if (!username) return bad(400, "缺少 username");
      const { rows } = await getPg().query(
        "SELECT id, username, role, enabled FROM users WHERE username = $1", [username],
      );
      const user = rows[0];
      if (!user) return bad(404, "账号不存在");
      const isAdmin = user.role === "admin";
      const models = isAdmin
        ? await db.listModels({})
        : await db.listVisibleModels({ role: user.role, userId: user.id });
      return json({
        user: { id: user.id, username: user.username, role: user.role, enabled: user.enabled },
        isAdmin, // 管理员全量可见（全站可管）
        models: models.map((m) => ({
          id: m.id, ref: m.ref, name: m.displayName, enabled: m.enabled, isCommon: m.isCommon,
          provider: m.providerName,
        })),
      });
    }),
  };
}

/* ================= 个人模型 ================= */
function personalRoutes() {
  return {
    "GET /api/models/mine": async (_request, ctx) => {
      const uid = await userIdOf(ctx);
      if (uid == null) return bad(403, "当前身份无自有账号，不能接入个人模型");
      const providers = await db.listProviders({ scope: "personal", ownerUserId: uid });
      const tree = [];
      for (const p of providers) {
        tree.push({ ...p, plans: await db.listPlans(p.id), models: await db.listModels({ providerId: p.id }) });
      }
      return json({ providers: tree });
    },

    "POST /api/models/mine/providers": async (request, ctx) => {
      const uid = await userIdOf(ctx);
      if (uid == null) return bad(403, "当前身份无自有账号，不能接入个人模型");
      const body = await request.json().catch(() => ({}));
      const v = validateProviderBody({ ...body, code: `u${uid}-${String(body?.code ?? "").trim().toLowerCase()}` });
      if (v.error) return bad(400, v.error);
      const provider = await db.createProvider({ ...v.value, scope: "personal", ownerUserId: uid });
      await reloadModels();
      return json({ provider }, 201);
    },

    "PATCH /api/models/mine/providers/:id": async (request, ctx) => {
      const { provider, error } = await ownProviderOr404(ctx, Number(request.params.id));
      if (error) return error;
      const body = await request.json().catch(() => ({}));
      const v = validateProviderBody(body, { partial: true });
      if (v.error) return bad(400, v.error);
      delete v.value.code; // 个人供应商 code 不可改（含归属前缀）
      const updated = await db.updateProvider(provider.id, v.value);
      await reloadModels();
      return json({ provider: updated });
    },

    "DELETE /api/models/mine/providers/:id": async (request, ctx) => {
      const { provider, error } = await ownProviderOr404(ctx, Number(request.params.id));
      if (error) return error;
      await db.deleteProvider(provider.id);
      await reloadModels();
      return json({ ok: true });
    },

    "POST /api/models/mine/providers/:id/test": async (request, ctx) => {
      const { provider, error } = await ownProviderOr404(ctx, Number(request.params.id));
      if (error) return error;
      const row = (await getPg().query("SELECT * FROM model_providers WHERE id = $1", [provider.id])).rows[0];
      const key = decryptSecret(row.key_cipher);
      if (provider.authType !== "none" && !key) return json({ ok: false, error: "未配置密钥" });
      return json(await probeProvider(provider, null, key));
    },

    "POST /api/models/mine/fetch": async (request, ctx) => {
      const body = await request.json().catch(() => ({}));
      const { provider, error } = await ownProviderOr404(ctx, Number(body?.providerId));
      if (error) return error;
      const row = (await getPg().query("SELECT * FROM model_providers WHERE id = $1", [provider.id])).rows[0];
      const key = decryptSecret(row.key_cipher);
      if (provider.authType !== "none" && !key) return bad(400, "未配置密钥，无法拉取");
      const probe = await probeProvider(provider, null, key);
      if (!probe.ok) return json({ ok: false, error: probe.error, latencyMs: probe.latencyMs }, 502);
      let created = 0;
      for (const modelId of probe.models ?? []) {
        const before = await getPg().query("SELECT 1 FROM models WHERE provider_id = $1 AND model_id = $2", [provider.id, modelId]);
        await db.createModel({ providerId: provider.id, planId: null, modelId, displayName: modelId, source: "fetched" });
        if (!before.rows[0]) created++;
      }
      await reloadModels();
      return json({ ok: true, created, total: (probe.models ?? []).length, latencyMs: probe.latencyMs });
    },
  };
}

export function modelRoutes() {
  return {
    // 管理端：角色 + admin 应用授权双层门槛
    ...gateApp("admin", adminModelRoutes()),
    // 个人模型：登录即可（chord 非 public 路由默认 401）
    ...personalRoutes(),
  };
}

/** 供 chat.mjs 前台列表用：R3 并集可见模型 */
export async function visibleModelList(ctx) {
  const role = await roleOf(ctx);
  const user = await userByPrincipal(ctx);
  return db.listVisibleModels({ role, userId: user?.id ?? null });
}
