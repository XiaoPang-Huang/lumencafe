// 对话应用路由（第 1 批，白皮书 §08 时序图实现）
// 链路：先保存用户消息（请求标识幂等）→ 返回保存确认 → 再发起流式生成
import { chatDb, conv, msg, chatUploads } from "./chat-db.mjs";
import { streamChat, defaultModelRef, hasRealLlm } from "./llm.mjs";
import { visibleModelList } from "./models.mjs";
import { userByPrincipal } from "./auth.mjs";
import { gateApp } from "./gateway.mjs";
import { storage } from "./storage.mjs";

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
  // 批 3：对话应用门槛（网关单点，无授权 403「无权访问该应用」）
  return gateApp("chat", {
    // 模型列表（模型 & API 管理）：按 R3 并集过滤当前用户可见模型
    "GET /api/chat/models": async (_request, ctx) => {
      const visible = await visibleModelList(ctx);
      return json({
        models: visible.map((m) => ({
          id: m.ref, provider: m.providerCode, modelId: m.modelId,
          name: m.displayName, reasoning: m.thinking != null || m.thinkingLevels?.length > 0,
          thinking: m.thinking, thinkingLevels: m.thinkingLevels, // 管理能力；对话浮卡档位严格取 thinkingLevels
          supportsImages: m.supportsImages === true, // 图片输入能力（多模态标记）
          // 详情卡如实展示（三级浮出拍板）：已配置的才显示，不造假
          inputPrice: m.inputPrice ?? null, outputPrice: m.outputPrice ?? null,
          contextWindow: m.contextWindow ?? null, maxOutputTokens: m.maxOutputTokens ?? null,
        })),
        default_model: visible[0]?.ref ?? defaultModelRef(),
        real: hasRealLlm(),
      });
    },

    "GET /api/chat/conversations": async (request, ctx) => {
      const ownerKey = ownerKeyOf(ctx);
      const q = request.query.get("q")?.trim();
      return json({ conversations: q ? conv.search(ownerKey, q) : conv.list(ownerKey) });
    },

    "POST /api/chat/conversations": async (request, ctx) => {
      const body = await request.json().catch(() => ({}));
      const THINKING = [null, "off", "minimal", "low", "medium", "high", "xhigh", "max"];
      const thinking = THINKING.includes(body?.thinking) ? body.thinking : null;
      return json({ conversation: conv.create(ownerKeyOf(ctx), { title: body?.title, model: body?.model ?? null, mode: body?.mode, thinking }) }, 201);
    },

    "PATCH /api/chat/conversations/:id": async (request, ctx) => {
      const ownerKey = ownerKeyOf(ctx);
      const id = request.params.id;
      const body = await request.json().catch(() => ({}));
      if (!conv.get(ownerKey, id)) return bad(404, "会话不存在");
      let c = conv.get(ownerKey, id);
      if (typeof body?.title === "string") c = conv.rename(ownerKey, id, body.title);
      if (typeof body?.model === "string") c = conv.setModel(ownerKey, id, body.model);
      if (body?.thinking !== undefined) {
        // "off"=显式关闭；null=开启并跟随模型/厂商默认；其余为旧会话 pi 档位（保留兼容）
        const THINKING = [null, "off", "minimal", "low", "medium", "high", "xhigh", "max"];
        const thinking = THINKING.includes(body.thinking) ? body.thinking : null;
        c = conv.setThinking(ownerKey, id, thinking);
      }
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
    // 对话附件：上传（原始字节直传：?name=文件名，body ≤20MB；chord 请求无 formData，body() 读原始流）
    // 与下载（owner 隔离；图片内联显示，文件触发下载）
    "POST /api/chat/uploads": async (request, ctx) => {
      const LIMIT = 20 * 1024 * 1024;
      const name = (request.query.get("name") || "file").slice(0, 200) || "file";
      const mime = request.headers.get("content-type") || "application/octet-stream";
      const chunks = [];
      let size = 0;
      try {
        for await (const chunk of request.body(LIMIT + 1)) {
          size += chunk.length;
          if (size > LIMIT) return bad(400, "文件超过 20MB 上限");
          chunks.push(chunk);
        }
      } catch (err) {
        if (err?.status === 413) return bad(400, "文件超过 20MB 上限");
        throw err;
      }
      if (!size) return bad(400, "文件内容为空");
      const id = crypto.randomUUID();
      const safe = name.replace(/[^\w.\-一-龥]/g, "_").slice(-80) || "file";
      const storageKey = `chat-uploads/${id}_${safe}`;
      await storage.put(storageKey, Buffer.concat(chunks.map((c) => Buffer.from(c))));
      const meta = chatUploads.save(ownerKeyOf(ctx), { name, mime, size, storageKey });
      return json({ upload: { ...meta, url: `/api/chat/uploads/${meta.id}` } }, 201);
    },

    "GET /api/chat/uploads/:id": async (request, ctx) => {
      const up = chatUploads.get(ownerKeyOf(ctx), request.params.id);
      if (!up) return bad(404, "附件不存在");
      const bytes = await storage.get(up.storageKey);
      if (!bytes) return bad(404, "附件文件缺失");
      const inline = up.mime.startsWith("image/") || up.mime === "application/pdf";
      let sent = false;
      return {
        kind: "bytes", mime: up.mime,
        read: () => {
          if (sent) return new Uint8Array(0); // 空块收尾（SSE 同款协议）
          sent = true;
          return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
        },
        headers: {
          "Content-Type": up.mime,
          ...(inline ? {} : { "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(up.name)}` }),
          "X-Content-Type-Options": "nosniff",
        },
      };
    },

    "POST /api/chat/messages": async (request, ctx) => {
      const body = await request.json().catch(() => null);
      const ownerKey = ownerKeyOf(ctx);
      const c = body?.conversation_id ? conv.get(ownerKey, body.conversation_id) : null;
      if (!c) return bad(404, "会话不存在");
      if (typeof body?.content !== "string" || !body.content.trim() || typeof body?.req_id !== "string" || !body.req_id) {
        return bad(400, "消息内容或请求标识缺失");
      }
      // 附件：校验归属后把引用追加进内容（图片走 Markdown 图，文件走链接；AI 侧以文本引用感知）
      let content = body.content;
      if (Array.isArray(body.attachments) && body.attachments.length) {
        const refs = [];
        for (const a of body.attachments.slice(0, 9)) {
          const up = chatUploads.get(ownerKey, String(a?.id ?? ""));
          if (!up) return bad(404, `附件不存在或无权使用：${a?.name ?? a?.id ?? "?"}`);
          const url = `/api/chat/uploads/${up.id}`;
          refs.push(up.mime.startsWith("image/") ? `![${up.name}](${url})` : `[${up.name}](${url})`);
        }
        content = `${content}\n\n${refs.join("\n")}`;
      }
      const { message, duplicated } = msg.saveUser(c.id, { reqId: body.req_id, content });
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
        const t0 = Date.now();
        try {
          const contextMessages = msg.history(c.id)
            .filter((m) => m.role !== "assistant" || m.id !== pending.id)
            .map((m) => ({ role: m.role, content: m.content }));
          full = await streamChat({
            modelRef: c.model ?? defaultModelRef(),
            messages: contextMessages,
            signal,
            onDelta: (delta) => body_sse.push(`data: ${JSON.stringify({ delta })}\n\n`),
            meta: { userId: (await userByPrincipal(ctx))?.id ?? 0, app: "chat", conversationId: c.id },
            thinking: c.thinking ?? null, // NULL=开启并跟随模型/厂商默认；off=关闭；旧档位兼容
          });
          msg.markPartial(pending.id, full, "ok", Date.now() - t0);
          body_sse.push(`data: ${JSON.stringify({ done: true, message_id: pending.id })}\n\n`);
        } catch (error) {
          const stopped = signal?.aborted;
          msg.markPartial(pending.id, full, stopped ? "stopped" : "failed", Date.now() - t0);
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
  });
}
