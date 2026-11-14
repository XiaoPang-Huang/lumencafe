// 批 1 集成测试：账号登录全链路——bootstrap 建号、登录/登出/改密、限速、停用
import test from "node:test";
import assert from "node:assert/strict";
import { startServer, ownerSession, loginAs, insertUser, Client } from "../helpers.mjs";

let server;
let owner; // owner 一次性链接兑换的会话（= 首个 admin 的引导身份）

test.before(async () => {
  server = await startServer("authflow");
  owner = await ownerSession(server);
});

test.after(async () => {
  await server.stop();
});

test("未登录访问受保护接口 → 401", async () => {
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.get("/api/session")).status, 401);
  assert.equal((await anon.get("/api/auth/me")).status, 401);
  assert.equal((await anon.post("/api/auth/logout")).status, 401);
});

test("登录页公开可访问且 CSP 禁止内联", async () => {
  const raw = await fetch(`${server.baseUrl}/login`);
  assert.equal(raw.status, 200);
  assert.match(await raw.text(), /loginForm|login-card/);
  assert.match(raw.headers.get("content-security-policy"), /script-src 'self'/);
});

test("owner 引导：needed → 校验 400 → 建首个 admin → 幂等 409", async () => {
  const r1 = await owner.get("/api/auth/bootstrap");
  assert.deepEqual(r1.json, { needed: true });

  // 400 校验要在建号前做：users 非空后 POST 一律先 409（既定顺序，见 auth.mjs）
  assert.equal((await owner.post("/api/auth/bootstrap", { username: "Bad-Name", password: "abcdefgh" })).status, 400);
  assert.equal((await owner.post("/api/auth/bootstrap", { username: "x2", password: "short" })).status, 400);

  // 大小写混合用户名自动小写化
  const r2 = await owner.post("/api/auth/bootstrap", { username: "Boss_ACC", displayName: "老板", password: "admin-pass-1" });
  assert.equal(r2.status, 200);
  assert.equal((await owner.get("/api/auth/bootstrap")).json.needed, false);
  assert.equal((await owner.post("/api/auth/bootstrap", { username: "x2", password: "abcdefgh" })).status, 409);
});

test("登录成功 → cookie 生效 → principal 映射正确", async () => {
  const admin = await loginAs(server, "boss_acc", "admin-pass-1");
  const me = await admin.get("/api/session");
  assert.equal(me.status, 200);
  assert.deepEqual(me.json.principal, { kind: "owner" });
  assert.equal(me.json.user.role, "admin");
  assert.equal(me.json.user.username, "boss_acc");
});

test("member 登录 → principal {kind:member,name}", async () => {
  await insertUser(server.databaseUrl, { username: "alice", password: "alice-pass-1", displayName: "爱丽丝" });
  const alice = await loginAs(server, "alice", "alice-pass-1");
  const me = await alice.get("/api/session");
  assert.deepEqual(me.json.principal, { kind: "member", name: "alice" });
  assert.equal(me.json.user.displayName, "爱丽丝");
});

test("限速：连错 5 次锁 5 分钟，锁按用户名隔离", async () => {
  await insertUser(server.databaseUrl, { username: "bob", password: "bob-pass-1" });
  const anon = new Client(server.baseUrl);
  for (let i = 0; i < 4; i++) {
    const r = await anon.post("/api/auth/login", { username: "alice", password: "wrong-pass" });
    assert.equal(r.status, 401);
    assert.equal(r.message, "用户名或密码错误", "不存在用户与密码错文案统一（不泄露哪项错）");
  }
  const fifth = await anon.post("/api/auth/login", { username: "alice", password: "wrong-pass" });
  assert.equal(fifth.status, 429);
  // 锁定期内正确密码也 429
  const locked = await anon.post("/api/auth/login", { username: "alice", password: "alice-pass-1" });
  assert.equal(locked.status, 429);
  // 另一用户名不受影响
  const bob = await loginAs(server, "bob", "bob-pass-1");
  assert.equal((await bob.get("/api/auth/me")).status, 200);
});

test("改密：旧密错 401 / 新密短 400 / 成功后旧密失效", async () => {
  await insertUser(server.databaseUrl, { username: "carol", password: "carol-pass-1" });
  const c = await loginAs(server, "carol", "carol-pass-1");
  assert.equal((await c.post("/api/auth/password", { oldPassword: "nope", newPassword: "carol-pass-2" })).status, 401);
  assert.equal((await c.post("/api/auth/password", { oldPassword: "carol-pass-1", newPassword: "1234567" })).status, 400);
  assert.equal((await c.post("/api/auth/password", { oldPassword: "carol-pass-1", newPassword: "carol-pass-2" })).status, 200);
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.post("/api/auth/login", { username: "carol", password: "carol-pass-1" })).status, 401);
  await loginAs(server, "carol", "carol-pass-2"); // 新密码可登录
  // 匿名改密 401
  assert.equal((await anon.post("/api/auth/password", { oldPassword: "a", newPassword: "bbbbbbbb" })).status, 401);
});

test("登出 → cookie 立即失效", async () => {
  await insertUser(server.databaseUrl, { username: "dave1", password: "dave-pass-1" });
  const c = await loginAs(server, "dave1", "dave-pass-1");
  const out = await c.post("/api/auth/logout");
  assert.equal(out.status, 200);
  assert.equal((await c.get("/api/session")).status, 401);
});

test("停用账号登录被拒 401", async () => {
  await insertUser(server.databaseUrl, { username: "erin", password: "erin-pass-1", enabled: false });
  const anon = new Client(server.baseUrl);
  const r = await anon.post("/api/auth/login", { username: "erin", password: "erin-pass-1" });
  assert.equal(r.status, 401);
});

test("bootstrap 门槛：member 403、匿名 401", async () => {
  await insertUser(server.databaseUrl, { username: "frank", password: "frank-pass-1" });
  const frank = await loginAs(server, "frank", "frank-pass-1");
  assert.equal((await frank.get("/api/auth/bootstrap")).status, 403);
  assert.equal((await new Client(server.baseUrl).get("/api/auth/bootstrap")).status, 401);
});
