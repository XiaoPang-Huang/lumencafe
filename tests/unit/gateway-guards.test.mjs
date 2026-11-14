// 批 2/3：网关守卫单元测试——只用不触库的 principal（owner/server），
// member 角色判定要查 users 表，归集成测试覆盖。
import test from "node:test";
import assert from "node:assert/strict";
import { requireRole, requireAdmin, gateApp, allowedApps } from "../../src/api/gateway.mjs";

const ctxOf = (principal) => ({ principal });

test("requireRole：server principal（角色 null）→ 403 且不执行 handler", async () => {
  let called = 0;
  const handler = async () => { called += 1; return { kind: "json", value: { ok: true } }; };
  const res = await requireRole(handler, "admin")( {}, ctxOf({ kind: "server" }));
  assert.equal(res.status, 403);
  assert.equal(res.message, "无权访问");
  assert.equal(called, 0);
});

test("requireAdmin：owner principal → 放行且参数原样透传", async () => {
  const handler = async (request, ctx) => ({ kind: "json", value: { seen: [request.x, ctx.principal.kind] } });
  const res = await requireAdmin(handler)({ x: 42 }, ctxOf({ kind: "owner" }));
  assert.deepEqual(res.value.seen, [42, "owner"]);
});

test("requireRole：角色不在允许列表 → 403", async () => {
  // owner → admin；要求 member → 拒
  const res = await requireRole(async () => ({ kind: "json" }), "member")({}, ctxOf({ kind: "owner" }));
  assert.equal(res.status, 403);
});

test("gateApp：只包裸 handler，对象形态条目原样放行", () => {
  const bare = async () => ({ kind: "json", value: 1 });
  const pageEntry = { public: true, page: true, handler: async () => ({ kind: "html" }) };
  const out = gateApp("chat", { "GET /a": bare, "GET /b": pageEntry });
  assert.notEqual(out["GET /a"], bare, "裸 handler 应被包装");
  assert.equal(out["GET /b"], pageEntry, "对象条目不得包装");
});

test("gateApp：角色 null → 统一 403「无权访问该应用」，handler 不执行", async () => {
  let called = 0;
  const routes = gateApp("chat", { "GET /x": async () => { called += 1; return { kind: "json" }; } });
  const res = await routes["GET /x"]({}, ctxOf({ kind: "server" }));
  assert.equal(res.status, 403);
  assert.equal(res.message, "无权访问该应用");
  assert.equal(called, 0);
});

test("allowedApps：角色 null → 空数组（全程不触库）", async () => {
  assert.deepEqual(await allowedApps(ctxOf({ kind: "server" })), []);
  assert.deepEqual(await allowedApps(ctxOf(null)), []);
});
