// 对话 agent 模式（第 5 批，白皮书 §08 方案 B + §12 危险动作隔离）
// pi 接管对话：自主多步、工具白名单（只读）、beforeToolCall 角色复核 + 步数护栏、
// 每次工具调用落 audit_log、密钥不进工具闭包。总对话（hub）挂全部只读工具。
import { Agent } from "@earendil-works/pi-agent-core";
import { getPg } from "../db.mjs";
import { conv as chatConv, msg as chatMsg } from "./chat-db.mjs";
import { getModelByRef, streamSimple, DEFAULT_MODEL_REF, primeFaux } from "./llm.mjs";
import { toolsFor } from "./agent-tools.mjs";
import { roleOfPrincipal, gateApp } from "./gateway.mjs";
import { fauxAssistantMessage, fauxText, fauxToolCall } from "@earendil-works/pi-ai/providers/faux";

const GUARD_MAX_STEPS = 10;

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value) => ({ kind: "json", value });
const keyOf = (ctx) => JSON.stringify(ctx.principal);

/** SSE 顺序拉取体（与 chat.mjs 同款） */
function sseBody() {
  const encoder = new TextEncoder();
  const queue = [];
  let ended = false;
  let notify = null;
  return {
    push(text) { queue.push(text); notify?.(); },
    end() { ended = true; notify?.(); },
    async read() {
      while (queue.length === 0 && !ended) {
        await new Promise((r) => (notify = r));
        notify = null;
      }
      return encoder.encode(queue.shift() ?? "");
    },
  };
}
const SSE_HEADERS = {
  "Content-Type": "text/event-stream; charset=utf-8",
  "Cache-Control": "no-cache",
  "X-Accel-Buffering": "no",
};

async function logToolCall(ctx, name, args, blocked, reason = "") {
  try {
    await getPg().query(
      "INSERT INTO audit_log (actor, action, detail) VALUES ($1,$2,$3)",
      [keyOf(ctx), `agent_tool:${blocked ? "blocked" : "called"}`, JSON.stringify({ tool: name, args, reason }).slice(0, 900)],
    );
  } catch { /* 日志失败不阻断主流程 */ }
}

/** 跑一轮 agent，把事件推进 SSE；返回最终回答文本与工具轨迹 */
async function runAgent({ ctx, conversation, userText, body }) {
  const tools = toolsFor(conversation.app, ctx);
  const model = getModelByRef(conversation.model ?? DEFAULT_MODEL_REF);
  if (!model) throw new Error("没有可用模型");

  const trace = []; // 工具轨迹（渲染工具卡片用）
  let steps = 0;
  let finalText = "";

  const agent = new Agent({
    initialState: {
      systemPrompt: [
        "你是流光咖啡馆的智能助手，可以调用给定的只读工具帮用户查账、查论文库。",
        "规矩：只能用给定工具查数据，不要编造数字；查完用一两句中文说人话回答；",
        "工具都只读，改数据请引导用户回对应应用页面操作。",
      ].join(""),
      model,
      tools,
    },
    streamFn: (m, c, o) => streamSimple(m, c, o),
    beforeToolCall: async ({ toolCall }) => {
      steps++;
      const tool = tools.find((x) => x.name === toolCall.name);
      // 角色复核走网关单点（批 2）：ownerOnly 工具要求 admin 角色。
      // ctx 是 HTTP 路由 ctx（runAgent 闭包捕获），ctx.principal 即 chord 解析的登录身份。
      if (tool?.ownerOnly && (await roleOfPrincipal(ctx.principal)) !== "admin") {
        await logToolCall(ctx, toolCall.name, toolCall.arguments, true, "仅管理员可用");
        return { block: true, reason: "这个工具仅管理员可用，已拒绝", terminate: true };
      }
      if (steps > GUARD_MAX_STEPS) {
        await logToolCall(ctx, toolCall.name, toolCall.arguments, true, "超过步数护栏");
        return { block: true, reason: `超过 ${GUARD_MAX_STEPS} 步护栏，已停止`, terminate: true };
      }
      return undefined;
    },
  });

  agent.subscribe((event) => {
    switch (event.type) {
      case "message_update":
        if (event.assistantMessageEvent?.type === "text_delta") {
          finalText += event.assistantMessageEvent.delta;
          body.push(`data: ${JSON.stringify({ delta: event.assistantMessageEvent.delta })}\n\n`);
        }
        break;
      case "tool_execution_start": {
        trace.push({ name: event.toolName, args: event.args });
        body.push(`data: ${JSON.stringify({ tool: event.toolName, args: event.args })}\n\n`);
        break;
      }
      case "tool_execution_end": {
        const last = [...trace].reverse().find((x) => x.result === undefined);
        const text = event.result?.content?.map((c) => c.text).join("").slice(0, 300) ?? "";
        if (last) {
          last.result = event.isError ? `失败：${text}` : text;
          body.push(`data: ${JSON.stringify({ tool_end: last.name, ok: !event.isError, summary: last.result })}\n\n`);
        }
        logToolCall(ctx, event.toolName ?? "?", event.args ?? {}, false).catch(() => {});
        break;
      }
    }
  });

  await agent.prompt(userText);
  return { finalText, trace };
}

export function agentRoutes() {
  // 批 3：agent 总对话与对话工具归 chat 应用门槛；public 条目（dev hook）不包装
  return gateApp("chat", {
    // 开发/验收辅助：给 faux 预排剧本（仅 DEV_HOOKS=1 时开放；开发环境公开，生产不开此开关）
    "POST /api/dev/prime-faux": {
      public: true,
      handler: async (request) => {
        if (process.env.DEV_HOOKS !== "1") return bad(404, "not found");
        const body = await request.json().catch(() => null);
        const steps = (body?.steps ?? []).map((s) =>
          s.type === "tool"
            ? fauxAssistantMessage([fauxToolCall(s.name, s.args ?? {})])
            : fauxAssistantMessage([fauxText(String(s.text ?? ""))]),
        );
        primeFaux(steps);
        return json({ primed: steps.length });
      },
    },

    // 总对话（§09 方案 C）：每人一条，恒 agent 模式，挂全部只读工具
    "GET /api/chat/hub": async (_r, ctx) =>
      json({ conversation: chatConv.ensureApp(keyOf(ctx), "hub", "总对话") }),

    // agent 模式对话（SSE：文本增量 + 工具卡片事件）
    "POST /api/chat/agent": async (request, ctx) => {
      const bodyJson = await request.json().catch(() => null);
      const userId = keyOf(ctx);
      const c = bodyJson?.conversation_id ? chatConv.get(userId, bodyJson.conversation_id) : null;
      if (!c) return bad(404, "会话不存在");
      const content = String(bodyJson?.content ?? "").trim();
      const reqId = bodyJson?.req_id;
      if (!content || typeof reqId !== "string" || !reqId) return bad(400, "缺少内容或请求标识");

      const saved = chatMsg.saveUser(c.id, { reqId, content });
      chatConv.touch(userId, c.id);

      const body = sseBody();
      (async () => {
        try {
          const { finalText, trace } = await runAgent({ ctx, conversation: c, userText: content, body });
          // 结构化保存：前端渲染回答 + 持久工具卡片（kind=agent）
          chatMsg.saveAssistant(c.id, {
            reqId: `agent-${reqId}`,
            content: JSON.stringify({ answer: finalText || "（没有输出）", trace }),
            kind: "agent",
          });
          body.push(`data: ${JSON.stringify({ done: true })}\n\n`);
        } catch (error) {
          console.error("[agent] 运行失败:", error.message);
          chatMsg.saveAssistant(c.id, { reqId: `agent-${reqId}`, content: "生成失败，请重试。", status: "failed" });
          body.push(`data: ${JSON.stringify({ error: "生成失败" })}\n\n`);
        } finally {
          chatConv.touch(userId, c.id);
          body.end();
        }
      })();

      return { kind: "bytes", mime: "text/event-stream; charset=utf-8", read: body.read, headers: SSE_HEADERS };
    },

    // 会话模式切换（chat=单次调用 / agent=pi 接管）；总对话恒为 agent
    "POST /api/chat/conversations/:id/mode": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const userId = keyOf(ctx);
      const c = chatConv.get(userId, request.params.id);
      if (!c) return bad(404, "会话不存在");
      if (c.app === "hub") return bad(400, "总对话恒为 agent 模式");
      const mode = body?.mode === "agent" ? "agent" : "chat";
      const { chatDb } = await import("./chat-db.mjs");
      chatDb.prepare("UPDATE conversations SET mode = ?, updated_at = ? WHERE id = ?").run(mode, Date.now(), c.id);
      return json({ ok: true, mode });
    },
  });
}
