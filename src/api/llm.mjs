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
 * 单次流式对话。messages: [{role, content}]；onDelta(文本增量)。
 * 返回完整文本。signal 用于中止（用户停止）。
 * 失败直接抛错，由调用方按白皮书三态处理。
 */
export async function streamChat({ modelRef, systemPrompt, messages, onDelta, signal }) {
  const model = resolveModel(modelRef) ?? models.getModels()[0];
  if (!model) throw new Error("没有可用模型");

  // faux：每次请求补一条「复读机」回复，无 key 也能演示流式
  if (faux) {
    const last = [...messages].reverse().find((m) => m.role === "user");
    const reply = `（假模型，未配置 DEEPSEEK_API_KEY）你说：${last?.content ?? ""}\n\n配置 key 后走 DeepSeek 真模型。支持 Markdown：\n\n\`\`\`js\nconsole.log("hello");\n\`\`\`\n\n- 列表项一\n- 列表项二`;
    faux.appendResponses([fauxAssistantMessage([fauxText(reply)])]);
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
