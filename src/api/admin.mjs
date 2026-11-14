// 批 4 管理页后端：用户与角色 + 角色权限矩阵
// 白皮书 §12 硬规定：角色/权限规则只在网关一处判断——本模块自身不写任何角色判断，
// 所有路由统一 gateApp("admin")（应用授权）包 requireAdmin（角色）双层门槛。
// 用户表密码哈希复用 auth.mjs 的 hashPassword（scrypt）。
import { getPg } from "../db.mjs";
import { hashPassword, userByPrincipal } from "./auth.mjs";
import { requireAdmin, gateApp } from "./gateway.mjs";
import { issueMemberInvite } from "./invite-issuer.mjs";
import { notify } from "./notify.mjs";

const bad = (status, message) => ({ kind: "error", status, message });
const json = (value, status = 200) => ({ kind: "json", value, status });

const USERNAME_RE = /^[a-z0-9_]{2,32}$/;
const GATED_APPS = ["chat", "money", "papers", "admin"];
const ROLES = ["admin", "member"];

const toPublicUser = (row) => ({
  id: row.id,
  username: row.username,
  displayName: row.display_name,
  role: row.role,
  enabled: row.enabled,
  createdAt: row.created_at,
});

const listGrants = async () => {
  const { rows } = await getPg().query(
    "SELECT app, role, allowed FROM app_grants ORDER BY app, role",
  );
  return rows;
};

/** 除 id 外还有几名「启用中的 admin」（管理员保护规则共用） */
async function otherEnabledAdmins(pg, id) {
  const { rows } = await getPg().query(
    "SELECT count(*)::int AS n FROM users WHERE role = 'admin' AND enabled = TRUE AND id <> $1",
    [id],
  );
  return rows[0]?.n ?? 0;
}

/**
 * 「自己」判定：userByPrincipal(ctx).username 与目标 username 比对。
 * 边界：chord 原生 owner 会话映射到「第一名 admin 账号」——即用 owner 链接进来时
 * 视同为那名 admin 本人，不能改/停他；chord member 会话按 username 精确比对。
 */
async function isSelf(ctx, target) {
  const me = await userByPrincipal(ctx);
  return Boolean(me && me.username === target.username);
}

export function adminRoutes() {
  return gateApp("admin", {
    // 用户列表（按创建时间排序）
    "GET /api/admin/users": requireAdmin(async () => {
      const { rows } = await getPg().query("SELECT * FROM users ORDER BY created_at, id");
      return json({ users: rows.map(toPublicUser) });
    }),

    // 添加用户（校验规则同 auth.mjs 注册：用户名小写化、密码 ≥8、role 白名单）
    // 批 5 可选开关：invite=true 生成 chord 邀请链接（仅 member，principal 是 member），
    // push=true 经 notify 推送登录信息（企业微信主/Server 酱备）；两者失败都不阻断建号
    "POST /api/admin/users": requireAdmin(async (request) => {
      const body = await request.json().catch(() => null);
      const username = String(body?.username ?? "").trim().toLowerCase();
      const displayName = String(body?.displayName ?? "").trim() || username;
      const password = String(body?.password ?? "");
      const role = ROLES.includes(body?.role) ? body.role : null;
      const wantInvite = body?.invite === true;
      const wantPush = body?.push === true;
      if (!USERNAME_RE.test(username)) {
        return bad(400, "用户名需为 2-32 位小写字母、数字或下划线");
      }
      if (password.length < 8) return bad(400, "密码至少 8 位");
      if (!role) return bad(400, "角色只能是 admin 或 member");
      if (wantInvite && role !== "member") {
        // 邀请 principal 是 { kind: "member", name }，与 admin 的 owner principal 不匹配
        return bad(400, "邀请链接仅适用于成员账号");
      }
      let user;
      try {
        const { rows } = await getPg().query(
          "INSERT INTO users (username, display_name, password_hash, role) VALUES ($1,$2,$3,$4) RETURNING *",
          [username, displayName, hashPassword(password), role],
        );
        user = rows[0];
      } catch (error) {
        if (/unique|duplicate/i.test(error.message)) return bad(409, "用户名已存在");
        throw error;
      }
      const result = { user: toPublicUser(user) };
      if (wantInvite) {
        try {
          const invite = await issueMemberInvite({ username, displayName });
          result.inviteUrl = invite.url;
        } catch (error) {
          result.inviteError = error.message; // 兜底：链接生成失败不阻断建号
        }
      }
      if (wantPush) {
        const lines = [
          "流光咖啡馆 · 新成员邀请",
          `用户名：${username}`,
          `初始密码：${password}`,
        ];
        if (result.inviteUrl) lines.push(`邀请链接：${result.inviteUrl}`);
        lines.push("提示：邀请链接 7 天内一次性有效，打开即免密登录；也可用用户名+密码直接登录。");
        try {
          const pushed = await notify(lines.join("\n"));
          result.pushed = pushed.ok ? "ok" : pushed.channel === "none" ? "none" : "failed";
        } catch {
          result.pushed = "failed";
        }
      }
      return json(result, 201);
    }),

    // 改角色：不能改自己；不能把最后一名启用管理员降级
    "PATCH /api/admin/users/:id/role": requireAdmin(async (request, ctx) => {
      const id = Number(request.params.id);
      const body = await request.json().catch(() => null);
      const role = ROLES.includes(body?.role) ? body.role : null;
      if (!role) return bad(400, "角色只能是 admin 或 member");
      const pg = getPg();
      const { rows } = await pg.query("SELECT * FROM users WHERE id = $1", [id]);
      const target = rows[0];
      if (!target) return bad(404, "用户不存在");
      if (await isSelf(ctx, target)) return bad(409, "不能修改自己的角色");
      if (target.role === "admin" && role !== "admin" &&
          (await otherEnabledAdmins(pg, id)) === 0 && target.enabled) {
        return bad(409, "至少保留一名启用管理员");
      }
      const { rows: updated } = await pg.query(
        "UPDATE users SET role = $1, updated_at = now() WHERE id = $2 RETURNING *",
        [role, id],
      );
      return json({ user: toPublicUser(updated[0]) });
    }),

    // 停用/启用：不能停自己；不能停最后一名启用管理员
    "PATCH /api/admin/users/:id/enabled": requireAdmin(async (request, ctx) => {
      const id = Number(request.params.id);
      const body = await request.json().catch(() => null);
      if (typeof body?.enabled !== "boolean") return bad(400, "enabled 需为布尔");
      const pg = getPg();
      const { rows } = await pg.query("SELECT * FROM users WHERE id = $1", [id]);
      const target = rows[0];
      if (!target) return bad(404, "用户不存在");
      if (await isSelf(ctx, target)) return bad(409, "不能停用自己");
      if (body.enabled === false && target.role === "admin" && target.enabled &&
          (await otherEnabledAdmins(pg, id)) === 0) {
        return bad(409, "至少保留一名启用管理员");
      }
      const { rows: updated } = await pg.query(
        "UPDATE users SET enabled = $1, updated_at = now() WHERE id = $2 RETURNING *",
        [body.enabled, id],
      );
      return json({ user: toPublicUser(updated[0]) });
    }),

    // 重置密码：只换 hash；不自发登出——chord 会话与账号密码相互独立（批 1 既定行为），
    // 已发的会话继续有效，重置只影响下次密码登录
    "POST /api/admin/users/:id/reset-password": requireAdmin(async (request) => {
      const id = Number(request.params.id);
      const body = await request.json().catch(() => null);
      const password = String(body?.password ?? "");
      if (password.length < 8) return bad(400, "密码至少 8 位");
      const { rows } = await getPg().query(
        "UPDATE users SET password_hash = $1, updated_at = now() WHERE id = $2 RETURNING id",
        [hashPassword(password), id],
      );
      if (!rows[0]) return bad(404, "用户不存在");
      return json({ ok: true });
    }),

    // 角色权限矩阵全量
    "GET /api/admin/grants": requireAdmin(async () => json({ grants: await listGrants() })),

    // 改矩阵一格：锁死格 admin×admin 不能关（防把管理员入口对所有管理员关掉）；
    // 写库后返回全量矩阵，前端整表刷新
    "PUT /api/admin/grants": requireAdmin(async (request) => {
      const body = await request.json().catch(() => null);
      const app = body?.app;
      const role = body?.role;
      const allowed = body?.allowed;
      if (!GATED_APPS.includes(app)) return bad(400, "应用不合法");
      if (!ROLES.includes(role)) return bad(400, "角色不合法");
      if (typeof allowed !== "boolean") return bad(400, "allowed 需为布尔");
      if (app === "admin" && role === "admin" && allowed === false) {
        return bad(409, "管理员入口不能对管理员关闭");
      }
      await getPg().query(
        `INSERT INTO app_grants (app, role, allowed) VALUES ($1,$2,$3)
         ON CONFLICT (app, role) DO UPDATE SET allowed = $3`,
        [app, role, allowed],
      );
      return json({ grants: await listGrants() });
    }),
  });
}
