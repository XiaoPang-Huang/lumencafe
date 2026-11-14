// 对话模块集成测试：会话懒创建配套（A1）——创建带 model/mode、列表/改名/删除
import test from "node:test";
import assert from "node:assert/strict";
import { startServer, ownerSession, loginAs, insertUser, Client } from "../helpers.mjs";

let server;
let admin;

test.before(async () => {
  server = await startServer("chatconv");
  const owner = await ownerSession(server);
  await owner.post("/api/auth/bootstrap", { username: "boss", password: "boss-pass-1" });
  admin = await loginAs(server, "boss", "boss-pass-1");
});

test.after(async () => {
  await server.stop();
});

test("创建会话：默认 mode=chat；带 model/mode 创建随首条落库（A1 懒创建配套）", async () => {
  const r1 = await admin.post("/api/chat/conversations", {});
  assert.equal(r1.status, 201);
  assert.equal(r1.json.conversation.mode, "chat");
  assert.equal(r1.json.conversation.model, null);

  const r2 = await admin.post("/api/chat/conversations", { model: "deepseek-chat", mode: "agent" });
  assert.equal(r2.status, 201);
  assert.equal(r2.json.conversation.mode, "agent");
  assert.equal(r2.json.conversation.model, "deepseek-chat");

  // 非法 mode 归一为 chat（不入库脏值）
  const r3 = await admin.post("/api/chat/conversations", { mode: "evil" });
  assert.equal(r3.json.conversation.mode, "chat");
});

test("列表只含自己的会话；改名/删除生效", async () => {
  await insertUser(server.databaseUrl, { username: "member1", password: "member-pass-1" });
  const member = await loginAs(server, "member1", "member-pass-1");
  const mine = await member.post("/api/chat/conversations", {});
  const list = await member.get("/api/chat/conversations");
  assert.equal(list.json.conversations.length, 1);
  assert.equal(list.json.conversations[0].id, mine.json.conversation.id);

  const renamed = await member.patch(`/api/chat/conversations/${mine.json.conversation.id}`, { title: "我的会话" });
  assert.equal(renamed.json.conversation.title, "我的会话");

  await member.req("DELETE", `/api/chat/conversations/${mine.json.conversation.id}`);
  assert.equal((await member.get("/api/chat/conversations")).json.conversations.length, 0);
});

test("搜索：q 过滤标题（A2 后端侧）", async () => {
  await admin.post("/api/chat/conversations", { title: "向量数据库笔记" });
  await admin.post("/api/chat/conversations", { title: "周报草稿" });
  const hit = await admin.get("/api/chat/conversations?q=向量");
  assert.ok(hit.json.conversations.some((c) => c.title === "向量数据库笔记"));
  assert.ok(!hit.json.conversations.some((c) => c.title === "周报草稿"));
});

test("匿名访问对话接口 401", async () => {
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.get("/api/chat/conversations")).status, 401);
  assert.equal((await anon.post("/api/chat/conversations", {})).status, 401);
});