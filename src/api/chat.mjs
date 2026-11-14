// 对话应用路由（第 1 批，白皮书 §08 时序图实现）
// 链路：先保存用户消息（请求标识幂等）→ 返回保存确认 → 再发起流式生成
import { chatDb, conv, msg } from "./chat-db.mjs";
import { streamChat, listModels, DEFAULT_MODEL_REF, hasRealLlm } from "./llm.mjs";

const ownerKeyOf = (ctx) => JSON.stringify(ctx.principal);
const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });

/** SSE 顺序拉取体：push 文本增量，end 收尾；read 被顺序调用直到空块 */
function sseBody() {
  const encoder = new TextEncoder();
  const queue = [];
  let ended = false;
  let notify = null;
  return {
    push(text) {
      queue.push(text);
      notify?.();
    },
    end() {
      ended = true;
      notify?.();
    },
    async read() {
      while (queue.length === 0 && !ended) {
        await new Promise((resolve) => (notify = resolve));
        notify = null;
      }
      const text = queue.shift() ?? "";
      return encoder.encode(text);
    },
  };
}

const SSE_HEADERS = {
  "Content-Type": "text/event-stream; charset=utf-8",
  "Cache-Control": "no-cache",
  "X-Accel-Buffering": "no",
};

export function chatRoutes() {
  return {
    "GET /api/chat/models": async () =>
      json({ models: listModels(), default_model: DEFAULT_MODEL_REF, real: hasRealLlm }),

    "GET /api/chat/conversations": async (request, ctx) => {
      const ownerKey = ownerKeyOf(ctx);
      const q = request.query.get("q")?.trim();
      return json({ conversations: q ? conv.search(ownerKey, q) : conv.list(ownerKey) });
    },

    "POST /api/chat/conversations": async (request, ctx) => {
      const body = await request.json().catch(() => ({}));
      return json({ conversation: conv.create(ownerKeyOf(ctx), { title: body?.title, model: body?.model ?? null }) }, 201);
    },

    "PATCH /api/chat/conversations/:id": async (request, ctx) => {
      const ownerKey = ownerKeyOf(ctx);
      const id = request.params.id;
      const body = await request.json().catch(() => ({}));
      if (!conv.get(ownerKey, id)) return bad(404, "会话不存在");
      let c = conv.get(ownerKey, id);
      if (typeof body?.title === "string") c = conv.rename(ownerKey, id, body.title);
      if (typeof body?.model === "string") c = conv.setModel(ownerKey, id, body.model);
      return json({ conversation: c });
    },

    "DELETE /api/chat/conversations/:id": async (request, ctx) => {
      conv.remove(ownerKeyOf(ctx), request.params.id);
      return json({ ok: true });
    },

    "GET /api/chat/conversations/:id/messages": async (request, ctx) => {
      const c = conv.get(ownerKeyOf(ctx), request.params.id);
      if (!c) return bad(404, "会话不存在");
      return json({ conversation: c, messages: msg.history(c.id) });
    },

    // 第一步：幂等保存用户消息，返回保存确认（时序图：保存确认后再生成）
    "POST /api/chat/messages": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const ownerKey = ownerKeyOf(ctx);
      const c = body?.conversation_id ? conv.get(ownerKey, body.conversation_id) : null;
      if (!c) return bad(404, "会话不存在");
      if (typeof body?.content !== "string" || !body.content.trim() || typeof body?.req_id !== "string" || !body.req_id) {
        return bad(400, "消息内容或请求标识缺失");
      }
      const { message, duplicated } = msg.saveUser(c.id, { reqId: body.req_id, content: body.content });
      conv.touch(ownerKey, c.id);
      conv.autoTitle(ownerKey, c.id, body.content); // 首条消息取前 20~30 字作标题
      return json({ message, duplicated, conversation: conv.get(ownerKey, c.id) });
    },

    // 第二步：流式生成。regenerate=1 或 retry_message_id=<assistant消息id> → 替换旧回答
    "POST /api/chat/generate": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const ownerKey = ownerKeyOf(ctx);
      const c = body?.conversation_id ? conv.get(ownerKey, body.conversation_id) : null;
      if (!c) return bad(404, "会话不存在");

      const history = msg.history(c.id);
      const lastUser = [...history].reverse().find((m) => m.role === "user");
      if (!lastUser) return bad(400, "没有可回答的用户消息");

      // 重新生成/重试：删掉旧失败/停止的回答，用新回答替换（白皮书：不做版本分支）
      let replaceNote = null;
      if (body?.regenerate === 1 || typeof body?.retry_message_id === "string") {
        const target = typeof body?.retry_message_id === "string"
          ? msg.get(body.retry_message_id)
          : msg.lastAssistant(c.id);
        if (target?.role === "assistant") {
          chatDb.prepare("DELETE FROM messages WHERE id = ?").run(target.id);
          replaceNote = { replaced: target.id };
        }
      }

      // 先落一条占位 assistant 行（流式/停止/失败都要能落库）
      const pending = msg.saveAssistant(c.id, {
        reqId: `gen-${crypto.randomUUID()}`,
        content: "",
        status: "ok",
      });

      const body_sse = sseBody();
      const signal = ctx.abortSignal ?? undefined;

      (async () => {
        let full = "";
        try {
          const contextMessages = msg.history(c.id)
            .filter((m) => m.role !== "assistant" || m.id !== pending.id)
            .map((m) => ({ role: m.role, content: m.content }));
          full = await streamChat({
            modelRef: c.model ?? DEFAULT_MODEL_REF,
            messages: contextMessages,
            signal,
            onDelta: (delta) => body_sse.push(`data: ${JSON.stringify({ delta })}\n\n`),
          });
          msg.markPartial(pending.id, full, "ok");
          body_sse.push(`data: ${JSON.stringify({ done: true, message_id: pending.id })}\n\n`);
        } catch (error) {
          const stopped = signal?.aborted;
          msg.markPartial(pending.id, full, stopped ? "stopped" : "failed");
          if (!stopped) {
            console.error("[chat] 生成失败:", error.message);
            body_sse.push(`data: ${JSON.stringify({ error: "生成失败", message_id: pending.id })}\n\n`);
          }
        } finally {
          conv.touch(ownerKey, c.id);
          body_sse.end();
        }
      })();

      return {
        kind: "bytes",
        mime: "text/event-stream; charset=utf-8",
        read: body_sse.read,
        headers: SSE_HEADERS,
      };
    },
  };
}
