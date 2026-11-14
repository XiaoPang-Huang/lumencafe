// LLM 接入层（第 1 批）：pi-ai 单次流式调用
// 渠道规矩（2026-11-14 拍板）：多家可配，密钥只进 .env；DeepSeek 官方第一家。
// 有 DEEPSEEK_API_KEY 走真模型；没有则用 faux 假模型（开发/无 key 也能跑通全链路），页面会显示提示。
import { createModels, fauxAssistantMessage } from "@earendil-works/pi-ai";
import { deepseekProvider } from "@earendil-works/pi-ai/providers/deepseek";
import { fauxProvider, fauxText } from "@earendil-works/pi-ai/providers/faux";

const models = createModels();
let faux = null;

if (process.env.DEEPSEEK_API_KEY) {
  models.setProvider(deepseekProvider());
} else {
  faux = fauxProvider({ provider: "lumencafe-faux", models: [{ id: "faux-chat", name: "本地假模型（未配置 DEEPSEEK_API_KEY）" }] });
  models.setProvider(faux.provider);
}

export const hasRealLlm = Boolean(process.env.DEEPSEEK_API_KEY);

/** 供 agent 模式复用同一个 models 集合（agent 底座：白皮书第 5 批） */
export function getModelByRef(ref) {
  const all = models.getModels();
  if (!ref) return all[0] ?? null;
  const [provider, modelId] = String(ref).split("/");
  return models.getModel(provider, modelId) ?? all[0] ?? null;
}

export const streamSimple = (model, context, options) => models.streamSimple(model, context, options);

/** 测试辅助：无 key 时给 faux 预排剧本（E2E 确定性驱动 agent 多步） */
export function primeFaux(steps) {
  if (faux) faux.appendResponses(steps);
}

/** 前端模型选择器用：当前可用的模型清单 */
export function listModels() {
  return models.getModels().map((m) => ({
    id: `${m.provider}/${m.id}`,
    provider: m.provider,
    modelId: m.id,
    name: m.name ?? m.id,
    reasoning: Boolean(m.reasoning),
  }));
}

function resolveModel(ref) {
  // ref 形如 "deepseek/deepseek-flash"；不带斜杠时用默认
  const [provider, modelId] = String(ref ?? "").includes("/")
    ? String(ref).split("/")
    : [null, null];
  if (provider && modelId) return models.getModel(provider, modelId) ?? null;
  const all = models.getModels();
  return all[0] ?? null;
}

export const DEFAULT_MODEL_REF = hasRealLlm ? "deepseek/deepseek-flash" : "lumencafe-faux/faux-chat";

/**
 * 假模型的「固定剧本」（仅未配置 key 时用）：
 * - 记账助手的 JSON 解析请求 → 按简单规则回 JSON，保证记账链路可演示
 * - 其他 → 复读机 + Markdown 样例
 */
function fauxCanned(systemPrompt, userText) {
  const isParseCall = systemPrompt.includes("意图二选一"); // 记账的 JSON 解析调用
  const isAnswerCall = !isParseCall && systemPrompt.includes("记账助手"); // 统计结果说人话
  if (isParseCall) {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const monthStart = today.slice(0, 8) + "01";
    const amount = userText.match(/(\d+(?:\.\d+)?)\s*(?:元|块|块钱)/);
    if (amount) {
      const fen = Math.round(parseFloat(amount[1]) * 100);
      const category = /饭|餐|吃|奶茶|咖啡/.test(userText) ? "餐饮" : /车|地铁|滴滴|油/.test(userText) ? "交通" : /买|购/.test(userText) ? "购物" : "其他支出";
      return JSON.stringify({
        intent: "record", amount_fen: fen, type: "expense", category,
        occurred_on: today, shared: /两人|全家|家庭|共同/.test(userText),
        note: "", confidence: 0.5,
      });
    }
    if (/多少|花了|支出|收入|统计/.test(userText)) {
      return JSON.stringify({
        intent: "stats", from: monthStart, to: today,
        category: /饭|餐|吃/.test(userText) ? "餐饮" : null,
        type: /收入|赚/.test(userText) ? "income" : "expense",
        view: /两人|全家|家庭/.test(userText) ? "family" : "personal",
      });
    }
    return JSON.stringify({ intent: "record", amount_fen: null });
  }
  if (isAnswerCall) {
    const m = userText.match(/合计\s*([\d.]+)\s*元，共\s*(\d+)\s*笔/);
    if (m) return `（假模型回答）这段时间一共花了 ${m[1]} 元，共 ${m[2]} 笔。配置 DEEPSEEK_API_KEY 后是真实回答。`;
    return "（假模型回答）没查到这笔数。配置 DEEPSEEK_API_KEY 后是真实回答。";
  }
  // 论文问答：引用候选段落里的前两个 block 号，保证出处链路可演示
  if (systemPrompt.includes("论文阅读助手")) {
    const ids = [...new Set([...userText.matchAll(/【段落(\d+)】/g)].map((x) => Number(x[1])))].slice(0, 2);
    if (ids.length) return `根据〔${ids.join("〕和〔")}〕的说明：（假模型回答）相关段落见引用，点右侧出处可跳回原文。`;
    return "（假模型回答）候选段落里没有直接答案。";
  }
  if (systemPrompt.includes("论文翻译助手")) return `【机翻·未配置模型】${userText.slice(0, 200)}`;
  // 论文推送 digest：点名今日命中与篇目
  if (systemPrompt.includes("论文推送助手")) {
    const titles = [...userText.matchAll(/标题：(.+)/g)].map((m) => m[1].trim());
    return `今日命中 ${titles.length} 篇：${titles.slice(0, 3).join("；")}${titles.length > 3 ? " 等" : ""}。（假模型摘要，配置 DEEPSEEK_API_KEY 后为真实摘要）`;
  }
  return `（假模型，未配置 DEEPSEEK_API_KEY）你说：${userText}\n\n配置 key 后走 DeepSeek 真模型。支持 Markdown：\n\n\`\`\`js\nconsole.log("hello");\n\`\`\`\n\n- 列表项一\n- 列表项二`;
}

/**
 * 单次流式对话。messages: [{role, content}]；onDelta(文本增量)。
 * 返回完整文本。signal 用于中止（用户停止）。
 * 失败直接抛错，由调用方按白皮书三态处理。
 */
export async function streamChat({ modelRef, systemPrompt, messages, onDelta, signal }) {
  const model = resolveModel(modelRef) ?? models.getModels()[0];
  if (!model) throw new Error("没有可用模型");

  // faux：每次请求补一条假回复，无 key 也能演示流式
  if (faux) {
    const last = [...messages].reverse().find((m) => m.role === "user");
    const canned = fauxCanned(systemPrompt ?? "", last?.content ?? "");
    faux.appendResponses([fauxAssistantMessage([fauxText(canned)])]);
  }

  const context = {
    systemPrompt: systemPrompt ?? "你是流光咖啡馆的 AI 助手，回答简洁、准确，用中文。",
    messages: messages.map((m) => ({ role: m.role, content: m.content, timestamp: Date.now() })),
  };

  let full = "";
  const stream = models.stream(model, context);
  for await (const event of stream) {
    if (signal?.aborted) {
      await stream.return?.();
      break;
    }
    if (event.type === "text_delta") {
      full += event.delta;
      onDelta?.(event.delta);
    } else if (event.type === "error") {
      throw new Error(event.message ?? "模型调用失败");
    }
  }
  return full;
}
