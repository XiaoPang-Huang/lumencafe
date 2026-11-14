// 对话数据层（第 1 批）：会话与消息存 SQLite（应用自建 .data/app.sqlite）
// 白皮书 §05：对话记录属框架态，跟 SQLite 走，不进 PG。
// 幂等规矩（白皮书 §08）：请求标识 req_id 唯一约束，超时重试不重复落库。
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dataDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", ".data");
fs.mkdirSync(dataDir, { recursive: true });

export const chatDb = new DatabaseSync(path.join(dataDir, "app.sqlite"));

chatDb.exec(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS conversations (
    id            TEXT PRIMARY KEY,
    owner_key     TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '新会话',
    model         TEXT,
    app           TEXT NOT NULL DEFAULT 'chat',
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    last_msg_at   INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations (owner_key, last_msg_at DESC);

  CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    req_id          TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL DEFAULT 'text',
    status          TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','stopped','failed')),
    created_at      INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, created_at);
`);

// 旧库补列（0002 起 messages.kind / conversations.app 存在；首次启动的库已在建表语句里）
for (const ddl of [
  "ALTER TABLE conversations ADD COLUMN app TEXT NOT NULL DEFAULT 'chat'",
  "ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'",
  "ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat'", // chat=单次调用 agent=pi 接管（第 5 批）
]) {
  try { chatDb.exec(ddl); } catch { /* 列已存在 */ }
}

const now = () => Date.now();
const uuid = () => crypto.randomUUID();

const rowToConv = (r) => ({
  id: r.id, title: r.title, model: r.model, app: r.app, mode: r.mode,
  created_at: r.created_at, updated_at: r.updated_at, last_msg_at: r.last_msg_at,
});
const rowToMsg = (r) => ({
  id: r.id, conversation_id: r.conversation_id, req_id: r.req_id,
  role: r.role, content: r.content, kind: r.kind, status: r.status, created_at: r.created_at,
});

export const conv = {
  list(ownerKey, app = "chat") {
    return chatDb.prepare(
      "SELECT * FROM conversations WHERE owner_key = ? AND app = ? ORDER BY last_msg_at DESC",
    ).all(ownerKey, app).map(rowToConv);
  },
  get(ownerKey, id) {
    const r = chatDb.prepare("SELECT * FROM conversations WHERE owner_key = ? AND id = ?").get(ownerKey, id);
    return r ? rowToConv(r) : null;
  },
  create(ownerKey, { title = "新会话", model = null, app = "chat" } = {}) {
    const id = uuid();
    const t = now();
    chatDb.prepare(
      "INSERT INTO conversations (id, owner_key, title, model, app, created_at, updated_at, last_msg_at) VALUES (?,?,?,?,?,?,?,?)",
    ).run(id, ownerKey, title, model, app, t, t, t);
    return conv.get(ownerKey, id);
  },
  /** 应用专属对话（每人每应用一条，如记账对话） */
  ensureApp(ownerKey, app, title) {
    const existing = chatDb.prepare(
      "SELECT * FROM conversations WHERE owner_key = ? AND app = ? ORDER BY created_at LIMIT 1",
    ).get(ownerKey, app);
    if (existing) return rowToConv(existing);
    return conv.create(ownerKey, { title, app });
  },
  rename(ownerKey, id, title) {
    chatDb.prepare("UPDATE conversations SET title = ?, updated_at = ? WHERE owner_key = ? AND id = ?")
      .run(String(title).slice(0, 60), now(), ownerKey, id);
    return conv.get(ownerKey, id);
  },
  setModel(ownerKey, id, model) {
    chatDb.prepare("UPDATE conversations SET model = ?, updated_at = ? WHERE owner_key = ? AND id = ?")
      .run(model, now(), ownerKey, id);
    return conv.get(ownerKey, id);
  },
  remove(ownerKey, id) {
    chatDb.prepare("DELETE FROM conversations WHERE owner_key = ? AND id = ?").run(ownerKey, id);
  },
  search(ownerKey, q, app = "chat") {
    return chatDb.prepare(
      "SELECT * FROM conversations WHERE owner_key = ? AND app = ? AND title LIKE ? ORDER BY last_msg_at DESC",
    ).all(ownerKey, app, `%${q}%`).map(rowToConv);
  },
  touch(ownerKey, id) {
    chatDb.prepare("UPDATE conversations SET updated_at = ?, last_msg_at = ? WHERE owner_key = ? AND id = ?")
      .run(now(), now(), ownerKey, id);
  },
  /** 首条消息自动生成标题：前 20~30 字 */
  autoTitle(ownerKey, id, firstMessage) {
    const title = firstMessage.replace(/\s+/g, " ").trim().slice(0, 24) || "新会话";
    chatDb.prepare("UPDATE conversations SET title = ? WHERE owner_key = ? AND id = ? AND title = '新会话'")
      .run(title, ownerKey, id);
  },
};

export const msg = {
  history(conversationId) {
    return chatDb.prepare(
      "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid",
    ).all(conversationId).map(rowToMsg);
  },
  /** 按请求标识幂等保存：已存在（超时重试）直接返回旧行 */
  saveUser(conversationId, { reqId, content }) {
    const existing = chatDb.prepare("SELECT * FROM messages WHERE req_id = ?").get(reqId);
    if (existing) return { message: rowToMsg(existing), duplicated: true };
    const id = uuid();
    chatDb.prepare(
      "INSERT INTO messages (id, conversation_id, req_id, role, content, status, created_at) VALUES (?,?,?,?,?,?,?)",
    ).run(id, conversationId, reqId, "user", content, "ok", now());
    return { message: rowToMsg(chatDb.prepare("SELECT * FROM messages WHERE id = ?").get(id)), duplicated: false };
  },
  saveAssistant(conversationId, { reqId, content, status = "ok", kind = "text" }) {
    const id = uuid();
    chatDb.prepare(
      "INSERT INTO messages (id, conversation_id, req_id, role, content, kind, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
    ).run(id, conversationId, reqId, "assistant", content, kind, status, now());
    return rowToMsg(chatDb.prepare("SELECT * FROM messages WHERE id = ?").get(id));
  },
  /** 失败半成品/停止的内容落库并标记 */
  markPartial(messageId, content, status) {
    chatDb.prepare("UPDATE messages SET content = ?, status = ? WHERE id = ?").run(content, status, messageId);
  },
  /** 重新生成/重试：用新回答替换旧的失败半成品（白皮书：不做版本，直接替换） */
  replaceAssistant(oldMessageId, { reqId, content, status = "ok" }) {
    chatDb.prepare("DELETE FROM messages WHERE id = ?").run(oldMessageId);
    return msg.saveAssistant(
      chatDb.prepare("SELECT conversation_id FROM messages WHERE id = ?").get(oldMessageId)?.conversation_id ?? "",
      { reqId, content, status },
    );
  },
  get(id) {
    const r = chatDb.prepare("SELECT * FROM messages WHERE id = ?").get(id);
    return r ? rowToMsg(r) : null;
  },
  /** 会话里最后一条 assistant 消息（重新生成/重试的对象） */
  lastAssistant(conversationId) {
    const r = chatDb.prepare(
      "SELECT * FROM messages WHERE conversation_id = ? AND role = 'assistant' ORDER BY created_at DESC, rowid DESC LIMIT 1",
    ).get(conversationId);
    return r ? rowToMsg(r) : null;
  },
};
