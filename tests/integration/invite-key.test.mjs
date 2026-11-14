// 批 5 集成测试：自动发钥匙——邀请链接生成/消费/一次性语义、与密码登录并存、推送态
// （push 的 ok/failed 通道细节由 tests/unit/notify-channels.test.mjs 覆盖，这里验 API 映射与邀请全链路）
import test from "node:test";
import assert from "node:assert/strict";
import { startServer, ownerSession, loginAs, Client } from "../helpers.mjs";

let server, admin;

test.before(async () => {
  server = await startServer("invitekey"); // 不传 webhook → pushed 应为 "none"
  const owner = await ownerSession(server);
  await owner.post("/api/auth/bootstrap", { username: "admin1", displayName: "管理员", password: "admin-pass-1" });
  admin = await loginAs(server, "admin1", "admin-pass-1");
});

test.after(async () => {
  await server.stop();
});

test("建 member + 邀请链接 + 推送（无通道 → pushed=none，链接照出）", async () => {
  const r = await admin.post("/api/admin/users", {
    username: "dave", displayName: "戴夫", password: "dave-pass-1", role: "member", invite: true, push: true,
  });
  assert.equal(r.status, 201);
  assert.match(r.json.inviteUrl, new RegExp(`^${server.baseUrl.replace(/\./g, "\\.")}/_chord/invite#\\S+`));
  assert.equal(r.json.pushed, "none");
});

test("邀请链接消费：免密进系统，principal 是 {kind:member,name}", async () => {
  const created = await admin.post("/api/admin/users", { username: "eve", password: "eve-pass-1", role: "member", invite: true });
  const link = new URL(created.json.inviteUrl);
  const path = link.pathname;
  const token = link.hash.slice(1);

  const anon = new Client(server.baseUrl);
  assert.equal((await anon.get(path)).status, 200);
  const consume = await anon.post(path, { token });
  assert.equal(consume.status, 200);
  assert.ok(anon.cookie, "消费后应发会话 cookie");

  const me = await anon.get("/api/session");
  assert.deepEqual(me.json.principal, { kind: "member", name: "eve" });
  // 免密成员的权限与 member 一致：管理接口 403、业务接口 200
  assert.equal((await anon.get("/api/admin/probe")).status, 403);
  assert.equal((await anon.get("/api/money/entries")).status, 200);
});

test("邀请链接一次性：二次消费 403", async () => {
  const created = await admin.post("/api/admin/users", { username: "fred", password: "fred-pass-1", role: "member", invite: true });
  const link = new URL(created.json.inviteUrl);
  const path = link.pathname;
  const token = link.hash.slice(1);
  const first = new Client(server.baseUrl);
  await first.get(path);
  assert.equal((await first.post(path, { token })).status, 200);
  const second = new Client(server.baseUrl);
  await second.get(path);
  assert.equal((await second.post(path, { token })).status, 403);
});

test("并存：被邀请成员仍可用用户名+密码登录", async () => {
  const dave = await loginAs(server, "dave", "dave-pass-1");
  assert.equal((await dave.get("/api/session")).json.user.username, "dave");
});

test("邀请仅适用于成员账号：admin + invite → 400", async () => {
  const r = await admin.post("/api/admin/users", { username: "gina", password: "gina-pass-1", role: "admin", invite: true });
  assert.equal(r.status, 400);
  assert.equal(r.message, "邀请链接仅适用于成员账号");
});

test("不带 invite/push 的响应保持批 4 形态（无多余字段）", async () => {
  const r = await admin.post("/api/admin/users", { username: "henry", password: "henry-pass-1", role: "member" });
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.json), ["user"]);
});
