// 对话思考开关 → pi-ai 1.5.2 调用语义回归测试。
import test from "node:test";
import assert from "node:assert/strict";
import { streamSimple as streamOpenAI } from "@earendil-works/pi-ai/api/openai-completions";
import { streamSimple as streamAnthropic } from "@earendil-works/pi-ai/api/anthropic-messages";
import { resolveThinkingLevel, thinkingStreamArgs } from "../../src/api/llm.mjs";

function piModel(api, baseUrl) {
  return {
    id: "test-reasoning",
    name: "Test reasoning model",
    api,
    provider: "db-test",
    baseUrl,
    reasoning: true,
    thinkingLevelMap: { low: "low", high: "high" },
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 8192,
    maxTokens: 2048,
  };
}

/** 在真实 pi 适配器发网请求前截获最终请求体，验证 reasoning 到厂商字段的映射。 */
async function capturePayload(streamSimple, model, thinkingLevel) {
  const args = thinkingStreamArgs(model, {}, thinkingLevel);
  let payload = null;
  const stream = streamSimple(args.model, {
    messages: [{ role: "user", content: "ping", timestamp: Date.now() }],
  }, {
    ...args.options,
    apiKey: "test-key",
    onPayload(value) {
      payload = structuredClone(value);
      throw new Error("payload captured; network intentionally skipped");
    },
  });
  for await (const event of stream) {
    if (event.type === "error") break;
  }
  assert.ok(payload, "pi 适配器没有生成请求体");
  return payload;
}

test("会话 NULL 优先模型默认；未配置默认时跟随厂商，不擅自选档", () => {
  assert.equal(resolveThinkingLevel(null, { thinking: "high", thinkingLevels: ["low", "high"] }), "high");
  assert.equal(resolveThinkingLevel(null, { thinking: null, thinkingLevels: ["low", "high"] }), null);
  assert.equal(resolveThinkingLevel(null, { thinking: "medium", thinkingLevels: ["low"] }), null);
});

test("显式 off 与旧会话具体档位保持兼容", () => {
  assert.equal(resolveThinkingLevel("off", { thinking: "high", thinkingLevels: ["high"] }), "off");
  assert.equal(resolveThinkingLevel("low", { thinking: "high", thinkingLevels: ["low", "high"] }), "low");
});

test("pi streamSimple 使用 reasoning；开启/关闭/厂商默认三种参数形态正确", () => {
  const model = { id: "reasoning-model", reasoning: true };
  const signal = new AbortController().signal;

  const enabled = thinkingStreamArgs(model, { signal, reasoning: "off", thinkingLevel: "low" }, "high");
  assert.equal(enabled.model, model);
  assert.equal(enabled.options.reasoning, "high");
  assert.equal(enabled.options.thinkingLevel, undefined);
  assert.equal(enabled.options.signal, signal);

  const disabled = thinkingStreamArgs(model, { signal, reasoning: "high" }, "off");
  assert.equal(disabled.model, model);
  assert.equal(disabled.options.reasoning, undefined);
  assert.equal(disabled.options.signal, signal);

  const providerDefault = thinkingStreamArgs(model, { signal, reasoning: "high" }, null);
  assert.notEqual(providerDefault.model, model);
  assert.equal(providerDefault.model.reasoning, false);
  assert.equal(providerDefault.options.reasoning, undefined);
  assert.equal(providerDefault.options.signal, signal);
});

test("DeepSeek 适配器收到 reasoning 档位，厂商默认与 off 不被混用", async () => {
  const model = piModel("openai-completions", "https://api.deepseek.com");

  const enabled = await capturePayload(streamOpenAI, model, "high");
  assert.deepEqual(enabled.thinking, { type: "enabled" });
  assert.equal(enabled.reasoning_effort, "high");

  const providerDefault = await capturePayload(streamOpenAI, model, null);
  assert.equal(Object.hasOwn(providerDefault, "thinking"), false);
  assert.equal(Object.hasOwn(providerDefault, "reasoning_effort"), false);

  const disabled = await capturePayload(streamOpenAI, model, "off");
  assert.deepEqual(disabled.thinking, { type: "disabled" });
  assert.equal(Object.hasOwn(disabled, "reasoning_effort"), false);
});

test("OpenAI 与 Anthropic 适配器也区分默认强度和厂商默认", async () => {
  const openai = piModel("openai-completions", "https://api.openai.com");
  const openaiEnabled = await capturePayload(streamOpenAI, openai, "high");
  assert.equal(openaiEnabled.reasoning_effort, "high");
  const openaiDefault = await capturePayload(streamOpenAI, openai, null);
  assert.equal(Object.hasOwn(openaiDefault, "reasoning_effort"), false);

  const anthropic = piModel("anthropic-messages", "https://api.anthropic.com");
  const anthropicEnabled = await capturePayload(streamAnthropic, anthropic, "high");
  assert.equal(anthropicEnabled.thinking.type, "enabled");
  assert.ok(anthropicEnabled.thinking.budget_tokens > 0);
  const anthropicDefault = await capturePayload(streamAnthropic, anthropic, null);
  assert.equal(Object.hasOwn(anthropicDefault, "thinking"), false);
  const anthropicDisabled = await capturePayload(streamAnthropic, anthropic, "off");
  assert.deepEqual(anthropicDisabled.thinking, { type: "disabled" });
});
