// 模型 & API 管理数据层（需求-模型API管理-v1.md §4/§5）
// 规矩：SQL 直白写在这里；密钥只存密文+提示，解密只发生在调用前（llm.mjs / 连通测试）。
import { getPg } from "../db.mjs";
import { encryptSecret, decryptSecret, keyHint } from "./secret.mjs";

const pg = () => getPg();
const now = () => new Date().toISOString();

/* ---------- 行转换 ---------- */
const toProvider = (r) => ({
  id: r.id, name: r.name, code: r.code, protocol: r.protocol, baseUrl: r.base_url,
  authType: r.auth_type, authConfig: r.auth_config ?? {},
  hasKey: Boolean(r.key_cipher), keyHint: r.key_hint,
  enabled: r.enabled, scope: r.scope, ownerUserId: r.owner_user_id ?? null,
  remark: r.remark, createdAt: r.created_at, updatedAt: r.updated_at,
});
const toPlan = (r) => ({
  id: r.id, providerId: r.provider_id, name: r.name, planType: r.plan_type,
  baseUrl: r.base_url, hasKey: Boolean(r.key_cipher), keyHint: r.key_hint,
  rpmLimit: r.rpm_limit, dailyLimit: r.daily_limit,
  enabled: r.enabled, remark: r.remark, createdAt: r.created_at, updatedAt: r.updated_at,
});
const toModel = (r) => ({
  id: r.id, planId: r.plan_id, providerId: r.provider_id, modelId: r.model_id,
  ref: r.ref, displayName: r.display_name, enabled: r.enabled, isCommon: r.is_common,
  contextWindow: r.context_window, maxOutputTokens: r.max_output_tokens,
  inputPrice: r.input_price != null ? Number(r.input_price) : null,
  outputPrice: r.output_price != null ? Number(r.output_price) : null,
  supportsTools: r.supports_tools, source: r.source, fetchedAt: r.fetched_at,
  createdAt: r.created_at, updatedAt: r.updated_at,
  // join 而来
  providerName: r.provider_name ?? null, providerCode: r.provider_code ?? null,
  providerEnabled: r.provider_enabled ?? null, protocol: r.protocol ?? null,
  planEnabled: r.plan_enabled ?? null, planIdJoin: r.plan_id,
  grants: r.grant_list ?? null,
});

/* ---------- providers ---------- */
export async function listProviders({ scope = null, ownerUserId = null } = {}) {
  const conds = []; const params = [];
  if (scope) { params.push(scope); conds.push(`scope = $${params.length}`); }
  if (ownerUserId != null) { params.push(ownerUserId); conds.push(`owner_user_id = $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";
  const { rows } = await pg().query(`SELECT * FROM model_providers ${where} ORDER BY id`, params);
  return rows.map(toProvider);
}

export async function getProvider(id) {
  const { rows } = await pg().query("SELECT * FROM model_providers WHERE id = $1", [id]);
  return rows[0] ? toProvider(rows[0]) : null;
}

export async function createProvider({ name, code, protocol, baseUrl, authType, authConfig, key, scope, ownerUserId, remark }) {
  const { rows } = await pg().query(
    `INSERT INTO model_providers (name, code, protocol, base_url, auth_type, auth_config, key_cipher, key_hint, scope, owner_user_id, remark)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *`,
    [name, code, protocol, baseUrl, authType ?? "bearer", JSON.stringify(authConfig ?? {}), encryptSecret(key ?? ""), key ? keyHint(key) : "", scope ?? "system", ownerUserId ?? null, remark ?? ""],
  );
  return toProvider(rows[0]);
}

export async function updateProvider(id, patch) {
  const sets = []; const params = [];
  const push = (col, val) => { params.push(val); sets.push(`${col} = $${params.length}`); };
  if (patch.name !== undefined) push("name", patch.name);
  if (patch.protocol !== undefined) push("protocol", patch.protocol);
  if (patch.baseUrl !== undefined) push("base_url", patch.baseUrl);
  if (patch.authType !== undefined) push("auth_type", patch.authType);
  if (patch.authConfig !== undefined) push("auth_config", JSON.stringify(patch.authConfig));
  if (patch.key !== undefined) { push("key_cipher", encryptSecret(patch.key)); push("key_hint", patch.key ? keyHint(patch.key) : ""); }
  if (patch.enabled !== undefined) push("enabled", patch.enabled);
  if (patch.remark !== undefined) push("remark", patch.remark);
  if (!sets.length) return getProvider(id);
  params.push(id);
  const { rows } = await pg().query(
    `UPDATE model_providers SET ${sets.join(", ")}, updated_at = $${params.length + 1} WHERE id = $${params.length} RETURNING *`,
    [...params, now()],
  );
  return rows[0] ? toProvider(rows[0]) : null;
}

export async function deleteProvider(id) {
  await pg().query("DELETE FROM model_providers WHERE id = $1", [id]);
}

/** 取调用所需密钥：套餐级优先，其次供应商级；解密失败返回 null */
export async function resolveKey(providerRow, planRow = null) {
  const cipher = planRow?.key_cipher || providerRow?.key_cipher || "";
  if (!cipher) return null;
  return decryptSecret(cipher);
}

/* ---------- plans ---------- */
export async function listPlans(providerId) {
  const { rows } = await pg().query("SELECT * FROM model_plans WHERE provider_id = $1 ORDER BY id", [providerId]);
  return rows.map(toPlan);
}

export async function getPlan(id) {
  const { rows } = await pg().query("SELECT * FROM model_plans WHERE id = $1", [id]);
  return rows[0] ? toPlan(rows[0]) : null;
}

export async function createPlan({ providerId, name, planType, baseUrl, key, rpmLimit, dailyLimit, remark }) {
  const { rows } = await pg().query(
    `INSERT INTO model_plans (provider_id, name, plan_type, base_url, key_cipher, key_hint, rpm_limit, daily_limit, remark)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
    [providerId, name, planType ?? "official", baseUrl ?? "", encryptSecret(key), key ? keyHint(key) : "", rpmLimit ?? 0, dailyLimit ?? 0, remark ?? ""],
  );
  return toPlan(rows[0]);
}

export async function updatePlan(id, patch) {
  const sets = []; const params = [];
  const push = (col, val) => { params.push(val); sets.push(`${col} = $${params.length}`); };
  if (patch.name !== undefined) push("name", patch.name);
  if (patch.planType !== undefined) push("plan_type", patch.planType);
  if (patch.baseUrl !== undefined) push("base_url", patch.baseUrl);
  if (patch.key !== undefined) { push("key_cipher", encryptSecret(patch.key)); push("key_hint", patch.key ? keyHint(patch.key) : ""); }
  if (patch.rpmLimit !== undefined) push("rpm_limit", patch.rpmLimit);
  if (patch.dailyLimit !== undefined) push("daily_limit", patch.dailyLimit);
  if (patch.enabled !== undefined) push("enabled", patch.enabled);
  if (patch.remark !== undefined) push("remark", patch.remark);
  if (!sets.length) return getPlan(id);
  params.push(id);
  const { rows } = await pg().query(
    `UPDATE model_plans SET ${sets.join(", ")}, updated_at = $${params.length + 1} WHERE id = $${params.length} RETURNING *`,
    [...params, now()],
  );
  return rows[0] ? toPlan(rows[0]) : null;
}

export async function deletePlan(id) {
  await pg().query("DELETE FROM model_plans WHERE id = $1", [id]);
}

/* ---------- models ---------- */
const MODEL_JOIN = `
  SELECT m.*, p.name AS provider_name, p.code AS provider_code, p.enabled AS provider_enabled,
         p.protocol, pl.enabled AS plan_enabled,
         (SELECT json_agg(json_build_object('type', g.grantee_type, 'grantee', g.grantee))
            FROM model_grants g WHERE g.model_id = m.id) AS grant_list
  FROM models m
  JOIN model_providers p ON p.id = m.provider_id
  LEFT JOIN model_plans pl ON pl.id = m.plan_id
`;

export async function listModels({ providerId = null, scope = null, ownerUserId = null } = {}) {
  const conds = []; const params = [];
  if (providerId != null) { params.push(providerId); conds.push(`m.provider_id = $${params.length}`); }
  if (scope) { params.push(scope); conds.push(`p.scope = $${params.length}`); }
  if (ownerUserId != null) { params.push(ownerUserId); conds.push(`p.owner_user_id = $${params.length}`); }
  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";
  const { rows } = await pg().query(`${MODEL_JOIN} ${where} ORDER BY m.provider_id, m.id`, params);
  return rows.map(toModel);
}

export async function getModel(id) {
  const { rows } = await pg().query(`${MODEL_JOIN} WHERE m.id = $1`, [id]);
  return rows[0] ? toModel(rows[0]) : null;
}

export async function getModelByRef(ref) {
  const { rows } = await pg().query(`${MODEL_JOIN} WHERE m.ref = $1`, [ref]);
  return rows[0] ? toModel(rows[0]) : null;
}

export async function createModel({ providerId, planId, modelId, displayName, source }) {
  const provider = await getProvider(providerId);
  if (!provider) throw Object.assign(new Error("供应商不存在"), { status: 404 });
  const ref = `${provider.code}/${modelId}`;
  const { rows } = await pg().query(
    `INSERT INTO models (plan_id, provider_id, model_id, ref, display_name, source, fetched_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7)
     ON CONFLICT (provider_id, model_id) DO UPDATE SET
       display_name = EXCLUDED.display_name, source = EXCLUDED.source, fetched_at = EXCLUDED.fetched_at, updated_at = now()
     RETURNING *`,
    [planId ?? null, providerId, modelId, ref, displayName ?? modelId, source ?? "manual", source === "fetched" ? now() : null],
  );
  return getModel(rows[0].id);
}

export async function updateModel(id, patch) {
  const sets = []; const params = [];
  const push = (col, val) => { params.push(val); sets.push(`${col} = $${params.length}`); };
  if (patch.displayName !== undefined) push("display_name", patch.displayName);
  if (patch.enabled !== undefined) push("enabled", patch.enabled);
  if (patch.isCommon !== undefined) push("is_common", patch.isCommon);
  if (patch.contextWindow !== undefined) push("context_window", patch.contextWindow);
  if (patch.maxOutputTokens !== undefined) push("max_output_tokens", patch.maxOutputTokens);
  if (patch.inputPrice !== undefined) push("input_price", patch.inputPrice);
  if (patch.outputPrice !== undefined) push("output_price", patch.outputPrice);
  if (patch.supportsTools !== undefined) push("supports_tools", patch.supportsTools);
  if (!sets.length) return getModel(id);
  params.push(id);
  const { rows } = await pg().query(
    `UPDATE models SET ${sets.join(", ")}, updated_at = $${params.length + 1} WHERE id = $${params.length} RETURNING id`,
    [...params, now()],
  );
  return rows[0] ? getModel(id) : null;
}

export async function batchUpdateModels(ids, { enabled }) {
  await pg().query("UPDATE models SET enabled = $1, updated_at = $2 WHERE id = ANY($3)", [enabled, now(), ids]);
}

export async function deleteModel(id) {
  await pg().query("DELETE FROM models WHERE id = $1", [id]);
}

/** R3 并集：通用 ∪ 角色被授 ∪ 账号被授 ∪ 个人自接；链上供应商/套餐/模型全启用 */
export async function listVisibleModels({ role = null, userId = null }) {
  const { rows } = await pg().query(
    `${MODEL_JOIN}
     WHERE m.enabled = TRUE AND p.enabled = TRUE AND (pl.id IS NULL OR pl.enabled = TRUE)
       AND ( m.is_common = TRUE
          OR p.scope = 'personal' AND p.owner_user_id = $1
          OR EXISTS (SELECT 1 FROM model_grants g WHERE g.model_id = m.id
                     AND ((g.grantee_type = 'role' AND g.grantee = $2)
                       OR (g.grantee_type = 'user' AND g.grantee = $3)))
       )
     ORDER BY m.is_common DESC, p.id, m.id`,
    [userId, role, userId != null ? String(userId) : ""],
  );
  return rows.map(toModel);
}

/* ---------- grants ---------- */
export async function replaceGrants(modelId, grants) {
  await pg().query("DELETE FROM model_grants WHERE model_id = $1", [modelId]);
  for (const g of grants) {
    await pg().query(
      "INSERT INTO model_grants (model_id, grantee_type, grantee) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
      [modelId, g.type === "role" ? "role" : "user", String(g.grantee)],
    );
  }
}

/* ---------- call logs ---------- */
export async function logCall(entry) {
  await pg().query(
    `INSERT INTO llm_call_logs (model_id, plan_id, provider_id, user_id, app, conversation_id,
       prompt_tokens, completion_tokens, cost_fen, latency_ms, status, error_code, error_msg)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`,
    [entry.modelId ?? null, entry.planId ?? null, entry.providerId ?? null, entry.userId,
     entry.app ?? "chat", entry.conversationId ?? "",
     entry.promptTokens ?? null, entry.completionTokens ?? null, entry.costFen ?? 0,
     entry.latencyMs ?? 0, entry.status, entry.errorCode ?? "", String(entry.errorMsg ?? "").slice(0, 500)],
  ).catch((err) => console.error("[models] 调用日志写入失败：", err.message));
}

export async function listLogs({ modelId = null, userId = null, limit = 50 } = {}) {
  const conds = []; const params = [];
  if (modelId != null) { params.push(modelId); conds.push(`l.model_id = $${params.length}`); }
  if (userId != null) { params.push(userId); conds.push(`l.user_id = $${params.length}`); }
  params.push(Math.min(Math.max(Number(limit) || 50, 1), 200));
  const where = conds.length ? `WHERE ${conds.join(" AND ")}` : "";
  const { rows } = await pg().query(
    `SELECT l.*, u.username, m.display_name AS model_name, m.ref AS model_ref
     FROM llm_call_logs l
     LEFT JOIN users u ON u.id = l.user_id
     LEFT JOIN models m ON m.id = l.model_id
     ${where} ORDER BY l.id DESC LIMIT $${params.length}`,
    params,
  );
  return rows.map((r) => ({
    id: Number(r.id), modelId: r.model_id, modelName: r.model_name ?? "（已删除）", modelRef: r.model_ref ?? "",
    userId: r.user_id, username: r.username ?? "?", app: r.app, conversationId: r.conversation_id,
    promptTokens: r.prompt_tokens, completionTokens: r.completion_tokens, costFen: r.cost_fen,
    latencyMs: r.latency_ms, status: r.status, errorCode: r.error_code, errorMsg: r.error_msg,
    createdAt: r.created_at,
  }));
}

/** 当日成功调用次数（日额度判定用） */
export async function countTodayCalls(planId) {
  const { rows } = await pg().query(
    `SELECT count(*)::int AS n FROM llm_call_logs
     WHERE plan_id = $1 AND status = 'ok' AND created_at >= date_trunc('day', now())`,
    [planId],
  );
  return rows[0]?.n ?? 0;
}
