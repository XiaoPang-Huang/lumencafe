// LLM 接入层 v2（模型 & API 管理，需求-模型API管理-v1.md §6）
// DB 驱动：供应商/套餐/模型全部来自 PG，经 pi-ai createProvider 动态注册；
// 套餐级 RPM/日额度限流、连续失败熔断、llm_call_logs 异步记账。
// 无可用渠道时回退 faux 假模型（开发/无 key 全链路可跑），页面显示提示。
import { createModels, createProvider } from "@earendil-works/pi-ai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { anthropicMessagesApi } from "@earendil-works/pi-ai/api/anthropic-messages.lazy";
import { DEEPSEEK_MODELS } from "@earendil-works/pi-ai/providers/deepseek.models";
import { fauxProvider, fauxText, fauxAssistantMessage } from "@earendil-works/pi-ai/providers/faux";
import { getPg } from "../db.mjs";
import { decryptSecret, encryptSecret, keyHint } from "./secret.mjs";
import { logCall, countTodayCalls } from "./model-db.mjs";

/* ---------- 注册表（内存常驻，reloadModels 重建） ---------- */
// byRef: ref("code/model_id") → { piModel, db }；db 含 provider/plan/model 行快照
let models = createModels();
let byRef = new Map();
let faux = null;
let bootstrapped = false;

const API_OF = { openai: "openai-completions", anthropic: "anthropic-messages" };

/** DEEPSEEK_API_KEY 环境变量种子：库中无任何 system 供应商时，自动建 DeepSeek 官方供应商（幂等） */
async function seedFromEnv(pg) {
  if (!process.env.DEEPSEEK_API_KEY) return;
  const { rows } = await pg.query("SELECT count(*)::int AS n FROM model_providers WHERE scope = 'system'");
  if (rows[0].n > 0) return;
  const { rows: p } = await pg.query(
    `INSERT INTO model_providers (name, code, protocol, base_url, auth_type, key_cipher, key_hint, scope)
     VALUES ('DeepSeek','deepseek','openai','https://api.deepseek.com','bearer',$1,$2,'system') RETURNING id`,
    [encryptSecret(process.env.DEEPSEEK_API_KEY), keyHint(process.env.DEEPSEEK_API_KEY)],
  );
  const providerId = p[0].id;
  for (const m of Object.values(DEEPSEEK_MODELS)) {
    // 官方种子默认可用：is_common=true（R3 并集的第一来源；管理员可在后台改）；
    // 思考档位取 pi 目录的 thinkingLevelMap（映射 null 的档不支持）；默认强度留空，开启时跟随厂商默认
    const supportedLevels = m.thinkingLevelMap ? THINKING_LEVELS.filter((l) => m.thinkingLevelMap[l] != null) : [];
    await pg.query(
      `INSERT INTO models (plan_id, provider_id, model_id, ref, display_name, source, is_common, context_window, max_output_tokens, input_price, output_price, thinking_levels)
       VALUES (NULL,$1,$2,$3,$4,'manual',TRUE,$5,$6,$7,$8,$9)
       ON CONFLICT (provider_id, model_id) DO NOTHING`,
      [providerId, m.id, `deepseek/${m.id}`, m.name, m.contextWindow ?? null, m.maxTokens ?? null,
       m.cost?.input ?? null, m.cost?.output ?? null, supportedLevels.join(",")],
    );
  }
  console.log("[llm] 已从 DEEPSEEK_API_KEY 种子 DeepSeek 官方供应商（模型 & API 管理可见）");
}

/* 思考强度（学 WorkBuddy 模型配置）：thinking=默认强度（null=未配置，跟随厂商默认）；
   thinkingLevels=支持的档位 CSV。pi 值域 minimal/low/medium/high/xhigh/max，
   映射按同名字符串直传（DeepSeek/Claude 系兼容），不支持的档位映射 null。 */
const THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh", "max"];
const THINKING_LABELS = { minimal: "最轻", low: "低", medium: "中", high: "高", xhigh: "超高", max: "极致" };
export { THINKING_LEVELS, THINKING_LABELS };

function buildPiModel(dbModel, provider, plan) {
  const api = API_OF[provider.protocol];
  const thinking = dbModel.thinking ?? null;
  const supported = (dbModel.thinkingLevels?.length ? dbModel.thinkingLevels : ["low", "medium", "high", "xhigh", "max"]);
  const supportsThinking = Boolean(thinking || dbModel.thinkingLevels?.length);
  const thinkingLevelMap = supportsThinking
    ? Object.fromEntries(THINKING_LEVELS.map((l) => [l, supported.includes(l) ? l : null]))
    : undefined;
  return {
    id: dbModel.modelId,
    name: dbModel.displayName,
    api,
    provider: `db-${provider.code}`,
    baseUrl: plan?.baseUrl || provider.baseUrl,
    reasoning: supportsThinking,
    ...(thinkingLevelMap ? { thinkingLevelMap } : {}),
    input: dbModel.supportsImages ? ["text", "image"] : ["text"], // 图片输入能力（0010；多模态标记）
    cost: {
      input: Number(dbModel.inputPrice ?? 0),
      output: Number(dbModel.outputPrice ?? 0),
      cacheRead: 0,
      cacheWrite: 0,
    },
    contextWindow: dbModel.contextWindow ?? 131072,
    maxTokens: dbModel.maxOutputTokens ?? 8192,
  };
}

/** 读库重建注册表（启动 + 配置变更后调用；毫秒级，同步替换引用） */
export async function reloadModels() {
  const pg = getPg();
  if (!bootstrapped) { await seedFromEnv(pg); bootstrapped = true; }

  const next = createModels();
  const nextByRef = new Map();
  let nextFaux = null;

  const { rows: providers } = await pg.query(
    "SELECT * FROM model_providers WHERE enabled = TRUE AND protocol IN ('openai','anthropic') ORDER BY id",
  );
  for (const prow of providers) {
    const { rows: modelRows } = await pg.query(
      `SELECT m.*, pl.base_url AS plan_base_url, pl.key_cipher AS plan_key, pl.enabled AS plan_enabled,
              pl.rpm_limit, pl.daily_limit, pl.id AS plan_id
       FROM models m LEFT JOIN model_plans pl ON pl.id = m.plan_id
       WHERE m.provider_id = $1 AND m.enabled = TRUE ORDER BY m.display_order, m.id`,
      [prow.id],
    );
    const usable = modelRows.filter((m) => m.plan_id == null || m.plan_enabled);
    if (!usable.length) continue;
    const providerKey = decryptSecret(prow.key_cipher);
    if (prow.auth_type !== "none" && !providerKey) {
      console.warn(`[llm] 供应商 ${prow.code} 未配置密钥，跳过`);
      continue;
    }
    const baseUrl = usable[0]?.plan_base_url || prow.base_url;
    const planKey = usable[0]?.plan_key ? decryptSecret(usable[0].plan_key) : null;
    const effectiveKey = planKey || providerKey;
    const provider = createProvider({
      id: `db-${prow.code}`,
      name: prow.name,
      baseUrl,
      auth: {
        apiKey: {
          name: `${prow.name} API key`,
          login: async () => ({ type: "api_key", key: "" }),
          resolve: async () => ({ auth: { apiKey: effectiveKey ?? "" }, source: "db" }),
        },
      },
      models: usable.map((m) => buildPiModel({
        modelId: m.model_id, displayName: m.display_name,
        inputPrice: m.input_price, outputPrice: m.output_price,
        contextWindow: m.context_window, maxOutputTokens: m.max_output_tokens,
        thinking: m.thinking, thinkingLevels: m.thinking_levels ? String(m.thinking_levels).split(",") : [],
        supportsImages: m.supports_images === true,
      }, { protocol: prow.protocol, code: prow.code, baseUrl: prow.base_url }, { baseUrl: m.plan_base_url })),
      api: prow.protocol === "anthropic" ? anthropicMessagesApi() : openAICompletionsApi(),
    });
    next.setProvider(provider);
    for (const m of usable) {
      const piModel = provider.getModels().find((x) => x.id === m.model_id);
      nextByRef.set(m.ref, {
        piModel,
        db: {
          modelId: m.id, planId: m.plan_id, providerId: prow.id,
          isCommon: m.is_common === true,
          displayOrder: m.display_order ?? 0,
          supportsImages: m.supports_images === true,
          thinking: m.thinking ?? null,
          thinkingLevels: m.thinking_levels ? String(m.thinking_levels).split(",") : [],
          rpmLimit: m.rpm_limit ?? 0, dailyLimit: m.daily_limit ?? 0,
          inputPrice: m.input_price != null ? Number(m.input_price) : null,
          outputPrice: m.output_price != null ? Number(m.output_price) : null,
          providerCode: prow.code,
        },
      });
    }
  }

  if (!nextByRef.size) {
    nextFaux = fauxProvider({ provider: "lumencafe-faux", models: [{ id: "faux-chat", name: "本地假模型（未配置模型渠道）" }] });
    next.setProvider(nextFaux.provider);
    nextByRef.set("lumencafe-faux/faux-chat", {
      piModel: nextFaux.provider.getModels()[0],
      db: null, // null = faux，不计费不熔断
    });
    console.warn("[llm] 无可用模型渠道，回退 faux 假模型");
  }

  models = next;
  byRef = nextByRef;
  faux = nextFaux;
  console.log(`[llm] 模型注册表已加载：${byRef.size} 个模型（faux=${Boolean(faux)}）`);
}

/** 启动入口：server 启动流程外按需调用（首次 resolveModel 时懒加载） */
let loading = null;
export function ensureModels() {
  if (!loading) loading = reloadModels().catch((e) => console.error("[llm] 注册表加载失败：", e.message));
  return loading;
}

/* ---------- 限流与熔断（内存态，按 plan 粒度；无 plan 按 provider） ---------- */
const rateWindows = new Map(); // key → number[] 最近一分钟时间戳
const breakers = new Map();    // key → { fails, openUntil }
const BREAK_FAILS = 5;
const BREAK_MS = 60_000;

const guardKey = (db) => (db.planId != null ? `plan:${db.planId}` : `prov:${db.providerId}`);

async function checkRate(db) {
  if (!db) return; // faux 不限制
  const key = guardKey(db);
  const now = Date.now();
  const win = (rateWindows.get(key) ?? []).filter((t) => now - t < 60_000);
  if (db.rpmLimit > 0 && win.length >= db.rpmLimit) {
    throw Object.assign(new Error("渠道繁忙（超出每分钟调用上限），请稍后再试"), { code: "rate_limited" });
  }
  if (db.dailyLimit > 0 && db.planId != null) {
    const used = await countTodayCalls(db.planId);
    if (used >= db.dailyLimit) {
      throw Object.assign(new Error("渠道今日额度已用完"), { code: "daily_exhausted" });
    }
  }
  win.push(now);
  rateWindows.set(key, win);
}

function checkBreaker(db) {
  if (!db) return;
  const b = breakers.get(guardKey(db));
  if (b && b.openUntil > Date.now()) {
    throw Object.assign(new Error("渠道暂时不可用（连续失败已熔断），稍后再试"), { code: "breaker_open" });
  }
}

function recordFail(db) {
  if (!db) return;
  const key = guardKey(db);
  const b = breakers.get(key) ?? { fails: 0, openUntil: 0 };
  b.fails += 1;
  if (b.fails >= BREAK_FAILS) { b.openUntil = Date.now() + BREAK_MS; b.fails = 0; }
  breakers.set(key, b);
}
const recordOk = (db) => { if (db) breakers.delete(guardKey(db)); };

/* ---------- 对外 API（保持 v1 调用面兼容） ---------- */

/** 是否有真实渠道（false = faux 兜底中） */
export function hasRealLlm() { return !faux; }

/** 默认模型 ref：第一个通用模型，否则第一个可用，faux 兜底 */
export function defaultModelRef() {
  const entries = [...byRef.entries()];
  if (!entries.length) return "lumencafe-faux/faux-chat";
  return entries.find(([, v]) => v.db?.isCommon)?.[0] ?? entries[0][0];
}

/** 解析 ref → pi-ai 模型对象（agent 模式直接消费） */
export function getModelByRef(ref) {
  const entry = byRef.get(String(ref ?? "")) ?? byRef.get(defaultModelRef());
  return entry?.piModel ?? null;
}

/** 注册表元数据（思考强度等 DB 配置快照；供调用方做档位解析） */
export function getModelMeta(ref) {
  return byRef.get(String(ref ?? ""))?.db ?? null;
}

/**
 * 生效思考设置："off"=显式关闭；具体档位=模型默认或旧会话覆盖；
 * null=开启但未指定强度，必须跟随厂商默认，不能擅自选择最低/第一档。
 */
export function resolveThinkingLevel(conversationThinking, modelMeta) {
  if (conversationThinking === "off") return "off";
  if (!modelMeta) return null;
  const level = conversationThinking || modelMeta.thinking;
  if (!level) return null;
  const supported = modelMeta.thinkingLevels?.length ? modelMeta.thinkingLevels : ["low", "medium", "high", "xhigh", "max"];
  return supported.includes(level) ? level : null;
}

/** 按当前注册表解析会话思考设置。 */
export function resolveThinking(conversationThinking, ref) {
  const entry = byRef.get(String(ref ?? "")) ?? byRef.get(defaultModelRef());
  return resolveThinkingLevel(conversationThinking, entry?.db ?? null);
}

export const streamSimple = (model, context, options) => models.streamSimple(model, context, options);

/**
 * 转换成 pi-ai 1.5.2 streamSimple 参数。
 * - 有档位：传 reasoning:<level>，真正开启并指定强度；
 * - off：不传 reasoning，pi 适配器据此发送厂商关闭字段；
 * - null：以 reasoning:false 的模型副本调用，阻止 pi 自动补关闭字段，保留厂商默认。
 */
export function thinkingStreamArgs(model, options = {}, thinkingLevel = null) {
  const cleanOptions = { ...options };
  delete cleanOptions.reasoning;
  delete cleanOptions.thinkingLevel;
  if (thinkingLevel === null || thinkingLevel === undefined) {
    return { model: { ...model, reasoning: false }, options: cleanOptions };
  }
  if (thinkingLevel === "off") return { model, options: cleanOptions };
  return { model, options: { ...cleanOptions, reasoning: thinkingLevel } };
}

/** 对话统一入口：generate 与 agent 共用，避免把 pi 的 reasoning 误写成 thinkingLevel。 */
export function streamWithThinking(model, context, options = {}, thinkingLevel = null) {
  const args = thinkingStreamArgs(model, options, thinkingLevel);
  return models.streamSimple(args.model, context, args.options);
}

/** 全部已注册模型（管理/调试用；前台可见列表走 models.mjs visibleModelList） */
export function listModels() {
  return [...byRef.keys()].map((ref) => {
    const [, modelId] = ref.split("/");
    return { id: ref, provider: ref.split("/")[0], modelId, name: modelId, reasoning: false };
  });
}

/** 测试辅助：faux 预排剧本（E2E 确定性驱动 agent 多步） */
export function primeFaux(steps) {
  if (faux) faux.appendResponses(steps);
}

/* ---------- 假模型剧本（无渠道时保证链路可演示） ---------- */
function fauxCanned(systemPrompt, userText) {
  const isParseCall = systemPrompt.includes("意图二选一");
  const isAnswerCall = !isParseCall && systemPrompt.includes("记账助手");
  if (isParseCall) {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const monthStart = today.slice(0, 8) + "01";
    const amount = userText.match(/(\d+(?:\.\d+)?)\s*(?:元|块|块钱)/);
    if (amount) {
      const fen = Math.round(parseFloat(amount[1]) * 100);
      const category = /饭|餐|吃|奶茶|咖啡/.test(userText) ? "餐饮" : /车|地铁|滴滴|油/.test(userText) ? "交通" : /买|购/.test(userText) ? "购物" : "其他支出";
      return JSON.stringify({ intent: "record", amount_fen: fen, type: "expense", category, occurred_on: today, shared: /两人|全家|家庭|共同/.test(userText), note: "", confidence: 0.5 });
    }
    if (/多少|花了|支出|收入|统计/.test(userText)) {
      return JSON.stringify({ intent: "stats", from: monthStart, to: today, category: /饭|餐|吃/.test(userText) ? "餐饮" : null, type: /收入|赚/.test(userText) ? "income" : "expense", view: /两人|全家|家庭/.test(userText) ? "family" : "personal" });
    }
    return JSON.stringify({ intent: "record", amount_fen: null });
  }
  if (isAnswerCall) {
    const m = userText.match(/合计\s*([\d.]+)\s*元，共\s*(\d+)\s*笔/);
    return m ? `（假模型回答）这段时间一共花了 ${m[1]} 元，共 ${m[2]} 笔。在「模型 & API 管理」配置渠道后是真实回答。`
      : "（假模型回答）没查到这笔数。在「模型 & API 管理」配置渠道后是真实回答。";
  }
  if (systemPrompt.includes("论文阅读助手")) {
    const ids = [...new Set([...userText.matchAll(/【段落(\d+)】/g)].map((x) => Number(x[1])))].slice(0, 2);
    return ids.length ? `根据〔${ids.join("〕和〔")}〕的说明：（假模型回答）相关段落见引用，点右侧出处可跳回原文。` : "（假模型回答）候选段落里没有直接答案。";
  }
  if (systemPrompt.includes("论文翻译助手")) return `【机翻·未配置模型】${userText.slice(0, 200)}`;
  if (systemPrompt.includes("论文推送助手")) {
    const titles = [...userText.matchAll(/标题：(.+)/g)].map((m) => m[1].trim());
    return `今日命中 ${titles.length} 篇：${titles.slice(0, 3).join("；")}${titles.length > 3 ? " 等" : ""}。（假模型摘要，配置渠道后为真实摘要）`;
  }
  return `（假模型，未配置模型渠道）你说：${userText}\n\n到「模型 & API 管理」接入供应商后走真实模型。支持 Markdown：\n\n\`\`\`js\nconsole.log("hello");\n\`\`\`\n\n- 列表项一\n- 列表项二`;
}

/**
 * 单次流式对话（v2：限流 + 熔断 + 调用日志）。
 * messages: [{role, content}]；onDelta(文本增量)；signal 中止。
 * meta: { userId, app, conversationId } 用于记账（可省略）。
 * 失败直接抛错（白皮书三态由调用方处理）；限流/熔断错误带 .code。
 */
export async function streamChat({ modelRef, systemPrompt, messages, onDelta, signal, meta = {}, thinking = null }) {
  await ensureModels();
  const ref = byRef.has(modelRef) ? modelRef : defaultModelRef();
  const entry = byRef.get(ref);
  if (!entry?.piModel) throw new Error("没有可用模型");
  // 思考开关：会话覆盖或模型默认；null=厂商默认，off=显式关闭，具体档位兼容旧会话
  const thinkingLevel = resolveThinking(thinking, ref);

  // faux：补剧本走假回复，记 0 费日志
  if (!entry.db) {
    const last = [...messages].reverse().find((m) => m.role === "user");
    faux.appendResponses([fauxAssistantMessage([fauxText(fauxCanned(systemPrompt ?? "", last?.content ?? ""))])]);
    const t0 = Date.now();
    const result = await runStream(entry.piModel, systemPrompt, messages, onDelta, signal, thinkingLevel);
    await logCall({
      modelId: null, planId: null, providerId: null,
      userId: meta.userId ?? 0, app: meta.app ?? "chat", conversationId: meta.conversationId ?? "",
      promptTokens: null, completionTokens: null, costFen: 0,
      latencyMs: Date.now() - t0, status: result.aborted ? "stopped" : "ok",
    });
    return result.text;
  }

  const db = entry.db;
  checkBreaker(db);
  await checkRate(db);

  const t0 = Date.now();
  try {
    const result = await runStream(entry.piModel, systemPrompt, messages, onDelta, signal, thinkingLevel);
    recordOk(db);
    const usage = result.usage;
    const costFen = usage && db.inputPrice != null && db.outputPrice != null
      ? Math.round((usage.input / 1e6 * db.inputPrice + usage.output / 1e6 * db.outputPrice) * 100)
      : 0;
    await logCall({
      modelId: db.modelId, planId: db.planId, providerId: db.providerId,
      userId: meta.userId ?? 0, app: meta.app ?? "chat", conversationId: meta.conversationId ?? "",
      promptTokens: usage?.input ?? null, completionTokens: usage?.output ?? null,
      costFen, latencyMs: Date.now() - t0,
      status: result.aborted ? "stopped" : "ok",
    });
    return result.text;
  } catch (err) {
    if (err.name === "AbortError" || signal?.aborted) {
      await logCall({
        modelId: db.modelId, planId: db.planId, providerId: db.providerId,
        userId: meta.userId ?? 0, app: meta.app ?? "chat", conversationId: meta.conversationId ?? "",
        latencyMs: Date.now() - t0, status: "stopped",
      });
      throw err;
    }
    recordFail(db);
    await logCall({
      modelId: db.modelId, planId: db.planId, providerId: db.providerId,
      userId: meta.userId ?? 0, app: meta.app ?? "chat", conversationId: meta.conversationId ?? "",
      latencyMs: Date.now() - t0, status: "failed",
      errorCode: err.code ?? "call_failed", errorMsg: err.message,
    });
    throw err;
  }
}

/** 底层流式执行：返回 { text, usage, aborted }；thinkingLevel=null 跟随厂商，off 显式关闭。 */
async function runStream(piModel, systemPrompt, messages, onDelta, signal, thinkingLevel = null) {
  const context = {
    systemPrompt: systemPrompt ?? "你是流光咖啡馆的 AI 助手，回答简洁、准确，用中文。",
    messages: messages.map((m) => ({ role: m.role, content: m.content, timestamp: Date.now() })),
  };
  let full = "";
  let usage = null;
  let aborted = false;
  const stream = streamWithThinking(piModel, context, { signal }, thinkingLevel);
  for await (const event of stream) {
    if (signal?.aborted) {
      aborted = true;
      await stream.return?.();
      break;
    }
    if (event.type === "text_delta") {
      full += event.delta;
      onDelta?.(event.delta);
    } else if (event.type === "done") {
      usage = event.message?.usage ?? null;
    } else if (event.type === "error") {
      throw new Error(event.error?.message ?? event.message ?? "模型调用失败");
    }
  }
  return { text: full, usage, aborted };
}
