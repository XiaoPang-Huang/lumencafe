// 批 2/3 集成测试：网关单点 + 权限矩阵——401/403 矩阵、应用开关、缺行拒绝
import test from "node:test";
import assert from "node:assert/strict";
import { startServer, ownerSession, loginAs, insertUser, sql, Client } from "../helpers.mjs";

let server, owner, admin, alice;

test.before(async () => {
  server = await startServer("rbac");
  owner = await ownerSession(server);
  await owner.post("/api/auth/bootstrap", { username: "admin1", displayName: "管理员", password: "admin-pass-1" });
  await insertUser(server.databaseUrl, { username: "alice", password: "alice-pass-1" });
  admin = await loginAs(server, "admin1", "admin-pass-1");
  alice = await loginAs(server, "alice", "alice-pass-1");
});

test.after(async () => {
  await server.stop();
});

test("probe 门槛矩阵：匿名 401 / member 403 / admin 200", async () => {
  assert.equal((await new Client(server.baseUrl).get("/api/admin/probe")).status, 401);
  const a = await alice.get("/api/admin/probe");
  assert.equal(a.status, 403);
  assert.equal(a.message, "无权访问该应用"); // probe 外层是 gateApp("admin")，先到应用门
  assert.deepEqual((await admin.get("/api/admin/probe")).json, { ok: true, role: "admin" });
  // chord owner 会话同样 200（身份等价）
  assert.equal((await owner.get("/api/admin/probe")).status, 200);
});

test("digest 管理路由：匿名 401 / member 403 / admin 200", async () => {
  for (const [method, path] of [["GET", "/api/push/logs"], ["GET", "/api/push/crawl-runs"]]) {
    assert.equal((await new Client(server.baseUrl).req(method, path)).status, 401);
    assert.equal((await alice.req(method, path)).status, 403);
    assert.equal((await admin.req(method, path)).status, 200);
  }
  // run-now 幂等路径：admin 200 但不真发（今日已推则 skipped）
  assert.equal((await alice.post("/api/push/run-now")).status, 403);
  assert.equal((await admin.post("/api/push/run-now")).status, 200);
});

test("bootstrap 两路由也走网关：member 403", async () => {
  assert.equal((await alice.get("/api/auth/bootstrap")).status, 403);
  assert.equal((await alice.post("/api/auth/bootstrap", { username: "z1", password: "zzzzzzzz" })).status, 403);
});

test("默认种子：成员可用 chat/money/papers，无 admin", async () => {
  const s = await alice.get("/api/session");
  assert.deepEqual(s.json.apps, ["chat", "money", "papers"]);
  assert.equal((await admin.get("/api/session")).json.apps.length, 4);
  // 默认全开回归
  for (const p of ["/api/chat/models", "/api/money/entries", "/api/money/categories", "/api/papers/library", "/api/push/subscriptions"]) {
    assert.equal((await alice.get(p)).status, 200, `${p} 应 200`);
  }
});

test("关掉成员的记账 → money 403 逐字、其他应用不受影响", async () => {
  await sql(server.databaseUrl, "UPDATE app_grants SET allowed = false WHERE app = 'money' AND role = 'member'");
  const m = await alice.get("/api/money/entries");
  assert.equal(m.status, 403);
  assert.equal(m.message, "无权访问该应用");
  assert.equal((await alice.get("/api/chat/models")).status, 200);
  assert.equal((await alice.get("/api/papers/library")).status, 200);
  assert.equal((await admin.get("/api/money/entries")).status, 200);
  const s = await alice.get("/api/session");
  assert.deepEqual(s.json.apps, ["chat", "papers"]);
  await sql(server.databaseUrl, "UPDATE app_grants SET allowed = true WHERE app = 'money' AND role = 'member'");
  assert.equal((await alice.get("/api/money/entries")).status, 200);
});

test("关掉 admin 的 papers → admin papers 403、probe 仍 200（双层互不干扰）", async () => {
  await sql(server.databaseUrl, "UPDATE app_grants SET allowed = false WHERE app = 'papers' AND role = 'admin'");
  assert.equal((await admin.get("/api/papers/library")).status, 403);
  assert.equal((await admin.get("/api/admin/probe")).status, 200);
  assert.equal((await alice.get("/api/papers/library")).status, 200);
  await sql(server.databaseUrl, "UPDATE app_grants SET allowed = true WHERE app = 'papers' AND role = 'admin'");
  assert.equal((await admin.get("/api/papers/library")).status, 200);
});

test("缺行 = 默认拒绝", async () => {
  await sql(server.databaseUrl, "DELETE FROM app_grants WHERE app = 'chat' AND role = 'member'");
  assert.equal((await alice.get("/api/chat/models")).status, 403);
  await sql(server.databaseUrl, "INSERT INTO app_grants (app, role, allowed) VALUES ('chat','member',true)");
  assert.equal((await alice.get("/api/chat/models")).status, 200);
});

test("无账号的纯邀请成员（principal 有、users 无）→ 默认 member 角色", async () => {
  // 直接造一个 chord 邀请（不建账号），消费后角色应为默认 member
  const invite = await admin.req("POST", "/_chord/invites", { principal: { kind: "member", name: "ghost" }, label: "幽灵" });
  assert.equal(invite.status, 200);
  const path = new URL(invite.json.path, server.baseUrl).pathname;
  const token = invite.json.path.split("#")[1];
  const anon = new Client(server.baseUrl);
  await anon.get(path);
  const consume = await anon.post(path, { token });
  assert.equal(consume.status, 200);
  // ghost 无 users 账号：roleOfPrincipal 给 member → 管理接口 403
  assert.equal((await anon.get("/api/admin/probe")).status, 403);
  assert.equal((await anon.get("/api/chat/models")).status, 200);
});
