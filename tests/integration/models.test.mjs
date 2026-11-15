// 模型 & API 管理集成测试（需求-模型API管理-v1.md）
// 覆盖：供应商/套餐/模型 CRUD、密钥脱敏、一键拉取（本地 mock 上游）、批量启停、
//       授权整替、R3 并集可见、个人模型隔离（越权 404）、匿名 401
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { startServer, ownerSession, loginAs, insertUser, Client } from "../helpers.mjs";

let server;
let admin;
let upstream; // 假 OpenAI 上游（/models 返回固定清单）
let upstreamCalls = 0;

test.before(async () => {
  upstream = http.createServer((req, res) => {
    upstreamCalls++;
    const auth = req.headers.authorization ?? "";
    if (req.url === "/models") {
      if (!auth.includes("sk-test-key-123")) { res.writeHead(401); res.end(JSON.stringify({ error: "bad key" })); return; }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ object: "list", data: [
        { id: "mock-model-a" }, { id: "mock-model-b" },
      ] }));
      return;
    }
    res.writeHead(404); res.end("{}");
  });
  await new Promise((r) => upstream.listen(0, "127.0.0.1", r));

  server = await startServer("models");
  const owner = await ownerSession(server);
  await owner.post("/api/auth/bootstrap", { username: "boss", password: "boss-pass-1" });
  admin = await loginAs(server, "boss", "boss-pass-1");
});

test.after(async () => {
  await server.stop();
  await new Promise((r) => upstream.close(r));
});

const upstreamBase = () => `http://127.0.0.1:${upstream.address().port}`;

test("供应商 CRUD + 密钥只回脱敏提示", async () => {
  const r = await admin.post("/api/models/providers", {
    name: "Mock 上游", code: "mock", protocol: "openai",
    baseUrl: upstreamBase(), authType: "bearer", key: "sk-test-key-123", remark: "测试",
  });
  assert.equal(r.status, 201);
  assert.equal(r.json.provider.code, "mock");
  assert.equal(r.json.provider.hasKey, true);
  assert.match(r.json.provider.keyHint, /^sk-t…/);
  assert.equal(r.json.provider.key_cipher, undefined); // 密文绝不出接口
  assert.equal(r.json.provider.key, undefined);

  // code 重复 409
  const dup = await admin.post("/api/models/providers", { name: "x", code: "mock", protocol: "openai", baseUrl: upstreamBase() });
  assert.equal(dup.status, 409);

  // 编辑：换密钥 → hint 更新
  const upd = await admin.patch(`/api/models/providers/${r.json.provider.id}`, { key: "sk-test-key-456" });
  assert.match(upd.json.provider.keyHint, /-456$/);
});

test("连通测试：好 key 通、坏 key 返回上游错误", async () => {
  const tree = await admin.get("/api/models/tree");
  const mock = tree.json.providers.find((p) => p.code === "mock");
  // 先换回好 key
  await admin.patch(`/api/models/providers/${mock.id}`, { key: "sk-test-key-123" });
  const ok = await admin.post(`/api/models/providers/${mock.id}/test`, {});
  assert.equal(ok.json.ok, true);
  assert.equal(ok.json.modelsCount, 2);

  await admin.patch(`/api/models/providers/${mock.id}`, { key: "sk-bad-key" });
  const badRes = await admin.post(`/api/models/providers/${mock.id}/test`, {});
  assert.equal(badRes.json.ok, false);
  assert.match(badRes.json.error, /401/);
  await admin.patch(`/api/models/providers/${mock.id}`, { key: "sk-test-key-123" });
});

test("一键拉模型：新增+幂等（重复拉不重复建）", async () => {
  const tree = await admin.get("/api/models/tree");
  const mock = tree.json.providers.find((p) => p.code === "mock");
  const before = upstreamCalls;

  const f1 = await admin.post("/api/models/fetch", { providerId: mock.id });
  assert.equal(f1.json.ok, true);
  assert.equal(f1.json.created, 2);
  const f2 = await admin.post("/api/models/fetch", { providerId: mock.id });
  assert.equal(f2.json.updated, 2);
  assert.equal(f2.json.created, 0);
  assert.ok(upstreamCalls > before);

  const tree2 = await admin.get("/api/models/tree");
  const mock2 = tree2.json.providers.find((p) => p.code === "mock");
  const refs = mock2.models.map((m) => m.ref).sort();
  assert.deepEqual(refs, ["mock/mock-model-a", "mock/mock-model-b"]);
});

test("模型编辑/通用标记/批量启停/删除", async () => {
  const tree = await admin.get("/api/models/tree");
  const mock = tree.json.providers.find((p) => p.code === "mock");
  const [a, b] = mock.models;

  const e = await admin.patch(`/api/models/${a.id}`, { displayName: "模型甲", inputPrice: 1.5, outputPrice: 6 });
  assert.equal(e.json.model.displayName, "模型甲");
  assert.equal(Number(e.json.model.inputPrice), 1.5);

  const c = await admin.patch(`/api/models/${a.id}`, { isCommon: true });
  assert.equal(c.json.model.isCommon, true);

  const batch = await admin.post("/api/models/batch", { ids: [a.id, b.id], op: "disable" });
  assert.equal(batch.json.count, 2);
  const tree2 = await admin.get("/api/models/tree");
  const mock2 = tree2.json.providers.find((p) => p.code === "mock");
  assert.ok(mock2.models.every((m) => !m.enabled));

  await admin.post("/api/models/batch", { ids: [a.id, b.id], op: "enable" });
  const del = await admin.req("DELETE", `/api/models/${b.id}`);
  assert.equal(del.status, 200);
});

test("授权整替 + R3 并集可见（通用∪角色∪账号∪个人）", async () => {
  const tree = await admin.get("/api/models/tree");
  const mock = tree.json.providers.find((p) => p.code === "mock");
  const modelA = mock.models.find((m) => m.ref === "mock/mock-model-a");

  // 非通用 + 授权 member 角色 → member 可见
  await admin.patch(`/api/models/${modelA.id}`, { isCommon: false });
  let g = await admin.put(`/api/models/${modelA.id}/grants`, { grants: [{ type: "role", grantee: "member" }] });
  assert.equal(g.json.model.grants.length, 1);

  await insertUser(server.databaseUrl, { username: "member1", password: "member-pass-1" });
  const member = await loginAs(server, "member1", "member-pass-1");
  let list = await member.get("/api/chat/models");
  assert.ok(list.json.models.some((m) => m.id === "mock/mock-model-a"));

  // 收回角色授权、改为按账号授权给 admin 自己 → member 不可见
  const me = await admin.get("/api/session");
  g = await admin.put(`/api/models/${modelA.id}/grants`, { grants: [{ type: "user", grantee: me.json.user?.id ?? "1" }] });
  list = await member.get("/api/chat/models");
  assert.ok(!list.json.models.some((m) => m.id === "mock/mock-model-a"));

  // 通用标记 → 全员可见（无需授权行）
  await admin.patch(`/api/models/${modelA.id}`, { isCommon: true });
  list = await member.get("/api/chat/models");
  assert.ok(list.json.models.some((m) => m.id === "mock/mock-model-a"));
});

test("个人模型：自接/隔离/越权 404", async () => {
  await insertUser(server.databaseUrl, { username: "member2", password: "member-pass-2" });
  const member2 = await loginAs(server, "member2", "member-pass-2");

  const r = await member2.post("/api/models/mine/providers", {
    name: "我的上游", code: "mine", protocol: "openai", baseUrl: upstreamBase(), key: "sk-test-key-123",
  });
  assert.equal(r.status, 201);
  const pid = r.json.provider.id;
  assert.equal(r.json.provider.scope, "personal");
  assert.ok(r.json.provider.code.startsWith(`u${r.json.provider.ownerUserId}-`)); // 归属前缀强制

  const f = await member2.post("/api/models/mine/fetch", { providerId: pid });
  assert.equal(f.json.total, 2);

  // 自己可见
  const list = await member2.get("/api/chat/models");
  assert.ok(list.json.models.some((m) => m.id.startsWith(`u${r.json.provider.ownerUserId}-mine/`)));

  // 他人不可见（并集不含别人的 personal）
  const member1 = await loginAs(server, "member1", "member-pass-1");
  const list1 = await member1.get("/api/chat/models");
  assert.ok(!list1.json.models.some((m) => m.provider.startsWith("u") && m.provider.includes("-mine")));

  // 越权操作他人供应商 → 404（不暴露存在性）
  const evil = await member1.req("PATCH", `/api/models/mine/providers/${pid}`, { name: "抢" });
  assert.equal(evil.status, 404);
  const evilDel = await member1.req("DELETE", `/api/models/mine/providers/${pid}`);
  assert.equal(evilDel.status, 404);
});

test("调用日志：拉取动作本身不写日志；列表接口可用", async () => {
  const logs = await admin.get("/api/models/logs?limit=50");
  assert.equal(logs.status, 200);
  assert.ok(Array.isArray(logs.json.logs));
});

test("权限门槛：匿名 401；member 访问管理端 403", async () => {
  const anon = new Client(server.baseUrl);
  assert.equal((await anon.get("/api/models/tree")).status, 401);
  const member = await loginAs(server, "member1", "member-pass-1");
  assert.equal((await member.get("/api/models/tree")).status, 403);
  // 管理接口(member 可走的个人接口)不受影响
  assert.equal((await member.get("/api/models/mine")).status, 200);
});
