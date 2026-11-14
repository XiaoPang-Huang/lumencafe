// 批 2 角色 + 网关单点判断（白皮书 §12 硬规定：角色规则只在网关一处判断）
// 所有接口的角色门槛一律经 requireRole / requireAdmin 包 handler，
// 业务代码里不再出现 principal.kind 的权限判断（principal → 角色的映射只在此文件）。
import { getPg } from "../db.mjs";

/**
 * principal → 角色（"admin" / "member" / null）：
 * - chord owner 会话（含我们登录的 admin，principal 映射为 { kind: "owner" }）→ "admin"
 * - chord member：users 表查到账号 → 以表里的 role 为准；
 *   查不到（纯邀请链接成员，无账号）→ 默认 "member"
 * - 其它（如 server principal）→ null
 * 注意：停用账号（enabled=false）的角色判定仍以 users 表 role 为准——
 * enabled 只影响登录，不影响已发会话的角色判定（规格：批 2 角色判定约定）。
 */
export async function roleOfPrincipal(principal) {
  if (principal?.kind === "owner") return "admin";
  if (principal?.kind === "member") {
    const name = principal.name;
    if (typeof name === "string" && name) {
      const { rows } = await getPg().query(
        "SELECT role FROM users WHERE username = $1",
        [name],
      );
      if (rows[0]) return rows[0].role;
    }
    return "member"; // 纯邀请链接成员：无账号，给最低角色
  }
  return null;
}

/** HTTP ctx → 角色（ctx.principal 是 chord 解析好的登录身份） */
export async function roleOf(ctx) {
  return roleOfPrincipal(ctx.principal);
}

/**
 * 角色门槛包装器：handler 签名不变 (request, ctx) => response。
 * 角色不在允许列表内（含 null 兜底）→ 统一 403 { message: "无权访问" }。
 * 匿名请求理论上到不了这里（chord 非 public 路由默认 401 已挡），兜底同样 403。
 */
export function requireRole(handler, ...roles) {
  return async (request, ctx) => {
    const role = await roleOf(ctx);
    if (role === null || !roles.includes(role)) {
      return { kind: "error", status: 403, message: "无权访问" };
    }
    return handler(request, ctx);
  };
}

/** 管理员门槛（当前唯一角色门槛；后续角色扩展继续走 requireRole） */
export const requireAdmin = (handler) => requireRole(handler, "admin");
