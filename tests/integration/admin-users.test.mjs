// 批 4 集成测试：管理页后端——用户 CRUD 全流程 + 管理员保护 + 权限矩阵读写
import test from "node:test";
import assert from "node:assert/strict";
import { startServer, ownerSession, loginAs, insertUser, sql, Client } from "../helpers.mjs";

let server, owner, admin, alice;

test.before(async () => {
  server = await startServer("admincrud");
  owner = await ownerSession(server);
  await owner.post("/api/auth/bootstrap", { username: "admin1", displayName: "管理员", password: "admin-pass-1" });
  await insertUser(server.databaseUrl, { username: "alice", password: "alice-pass-1" });
  admin = await loginAs(server, "admin1", "admin-pass-1");
  alice = await loginAs(server, "alice", "alice-pass-1");
});

test.after(async () => {
  await server.stop();
});

test("门槛：匿名 401 / member 403（8 个管理路由全覆盖）", async () => {
  const adminPaths = [
    ["GET", "/api/admin/users"], ["POST", "/api/admin/users"],
    ["PATCH", "/api/admin/users/1/role"], ["PATCH", "/api/admin/users/1/enabled"],
    ["POST", "/api/admin/users/1/reset-password"],
    ["GET", "/api/admin/grants"], ["PUT", "/api/admin/grants"],
    ["GET", "/api/admin/probe"],
  ];
  for (const [m, p] of adminPaths) {
    assert.equal((await new Client(server.baseUrl).req(m, p)).status, 401, `匿名 ${m} ${p}`);
    assert.equal((await alice.req(m, p)).status, 403, `member ${m} ${p}`);
  }
});

test("建号全流程：建 member → 新账号登录 → 提 admin → 停用 → 登录被拒", async () => {
  const created = await admin.post("/api/admin/users", { username: "bob", displayName: "小博", password: "bob-pass-1", role: "member" });
  assert.equal(created.status, 201);
  const bob = await loginAs(server, "bob", "bob-pass-1");
  assert.equal((await bob.get("/api/auth/me")).json.user.role, "member");

  const id = created.json.user.id;
  const up = await admin.patch(`/api/admin/users/${id}/role`, { role: "admin" });
  assert.equal(up.status, 200);
  // 提 admin 后 bob 重新登录 → 角色生效（admin 的 me 映射第一名 admin，用 probe 证明角色）
  const bob2 = await loginAs(server, "bob", "bob-pass-1");
  assert.equal((await bob2.get("/api/admin/probe")).status, 200);

  const off = await admin.patch(`/api/admin/users/${id}/enabled`, { enabled: false });
  assert.equal(off.status, 200);
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.post("/api/auth/login", { username: "bob", password: "bob-pass-1" })).status, 401);
});

test("建号校验：重名 409 / 非法输入 400", async () => {
  assert.equal((await admin.post("/api/admin/users", { username: "alice", password: "alice-pass-1", role: "member" })).status, 409);
  assert.equal((await admin.post("/api/admin/users", { username: "Bad-Name", password: "xxxxxxxxx", role: "member" })).status, 400);
  assert.equal((await admin.post("/api/admin/users", { username: "okname", password: "short", role: "member" })).status, 400);
  assert.equal((await admin.post("/api/admin/users", { username: "okname", password: "xxxxxxxxx", role: "root" })).status, 400);
});

test("保护：改自己/停自己 409", async () => {
  const users = (await admin.get("/api/admin/users")).json.users;
  const me = users.find((u) => u.username === "admin1");
  assert.equal((await admin.patch(`/api/admin/users/${me.id}/role`, { role: "member" })).status, 409);
  assert.equal((await admin.patch(`/api/admin/users/${me.id}/enabled`, { enabled: false })).status, 409);
});

test("保护：至少留一名启用管理员（唯一启用 admin 非第一名的兜底分支）", async () => {
  // 造第二 admin carol；SQL 停用 admin1（owner 链接会话映射第一名 admin，API 改不到它——见 §19 边界）
  const carol = await admin.post("/api/admin/users", { username: "carol", password: "carol-pass-1", role: "admin" });
  const carolId = carol.json.user.id;
  await sql(server.databaseUrl, "UPDATE users SET enabled = false WHERE username = 'admin1'");
  const carolClient = await loginAs(server, "carol", "carol-pass-1");
  // carol 成唯一启用 admin：降级自己 / 停自己都触发「至少保留一名」409
  const r1 = await carolClient.patch(`/api/admin/users/${carolId}/role`, { role: "member" });
  assert.equal(r1.status, 409);
  assert.equal(r1.message, "至少保留一名启用管理员");
  const r2 = await carolClient.patch(`/api/admin/users/${carolId}/enabled`, { enabled: false });
  assert.equal(r2.status, 409);
  // 且没被锁死：carol 仍可正常登录
  await loginAs(server, "carol", "carol-pass-1");
  // 复原：启用 admin1
  await sql(server.databaseUrl, "UPDATE users SET enabled = true WHERE username = 'admin1'");
});

test("保护：第二 admin 操作第一名 admin 视同 self → 409", async () => {
  const users = (await admin.get("/api/admin/users")).json.users;
  const first = users.find((u) => u.username === "admin1");
  // carol（admin）会话的 principal 是 {kind:owner}，映射第一名 admin1 → isSelf 命中
  const carol = await loginAs(server, "carol", "carol-pass-1");
  assert.equal((await carol.patch(`/api/admin/users/${first.id}/role`, { role: "member" })).status, 409);
  assert.equal((await carol.patch(`/api/admin/users/${first.id}/enabled`, { enabled: false })).status, 409);
  // 但 carol 可以操作非第一名的其他人（如 bob）
  const bob = users.find((u) => u.username === "bob");
  assert.equal((await carol.patch(`/api/admin/users/${bob.id}/enabled`, { enabled: true })).status, 200);
});

test("重置密码：短密 400 / 重置后旧密失效新密可登 / 不踢既有会话", async () => {
  const users = (await admin.get("/api/admin/users")).json.users;
  const bob = users.find((u) => u.username === "bob");
  assert.equal((await admin.post(`/api/admin/users/${bob.id}/reset-password`, { password: "1234567" })).status, 400);
  const session = await loginAs(server, "bob", "bob-pass-1"); // bob 现密码登录（上一步已重新启用）
  assert.equal((await admin.post(`/api/admin/users/${bob.id}/reset-password`, { password: "bob-pass-2" })).status, 200);
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.post("/api/auth/login", { username: "bob", password: "bob-pass-1" })).status, 401);
  await loginAs(server, "bob", "bob-pass-2");
  // 已发的 chord 会话不因重置失效（批 1 既定行为）
  assert.equal((await session.get("/api/session")).status, 200);
});

test("权限矩阵：GET 8 行 / 改一格即时生效 / 锁死格 409 / 非法 400", async () => {
  const g = await admin.get("/api/admin/grants");
  assert.equal(g.json.grants.length, 8);

  const off = await admin.put("/api/admin/grants", { app: "money", role: "member", allowed: false });
  assert.equal(off.status, 200);
  assert.equal(off.json.grants.length, 8, "PUT 返回全量矩阵");
  assert.equal((await alice.get("/api/money/entries")).status, 403);
  assert.equal((await alice.get("/api/chat/models")).status, 200, "同角色跨应用隔离");

  const locked = await admin.put("/api/admin/grants", { app: "admin", role: "admin", allowed: false });
  assert.equal(locked.status, 409);
  assert.equal(locked.message, "管理员入口不能对管理员关闭");
  assert.equal((await admin.put("/api/admin/grants", { app: "nope", role: "member", allowed: true })).status, 400);
  assert.equal((await admin.put("/api/admin/grants", { app: "chat", role: "root", allowed: true })).status, 400);
  assert.equal((await admin.put("/api/admin/grants", { app: "chat", role: "member", allowed: "yes" })).status, 400);

  await admin.put("/api/admin/grants", { app: "money", role: "member", allowed: true });
  assert.equal((await alice.get("/api/money/entries")).status, 200);
});
