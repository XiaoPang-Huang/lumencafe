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

/* ---------- 批 3 应用级授权（权限矩阵） ---------- */
// 授权数据在 app_grants 表（migrations/0006）：**缺行 = 默认拒绝**。
// 未来新增应用必须给种子行，否则所有角色都被拒。

/** 受应用门槛管辖的应用 key（与 app_grants CHECK 约束一致） */
const GATED_APPS = ["chat", "money", "papers", "admin"];

/**
 * 某角色对某应用是否有授权：查 app_grants 的 allowed；
 * 无行（缺行）→ false；role 为 null（非人 principal）→ false。
 */
export async function appAllowedForRole(role, app) {
  if (role === null || role === undefined) return false;
  const { rows } = await getPg().query(
    "SELECT allowed FROM app_grants WHERE app = $1 AND role = $2",
    [app, role],
  );
  return rows[0]?.allowed === true;
}

/** 当前 ctx 角色可用的应用 key 数组（四个应用逐个直查，量小不做缓存避免失效） */
export async function allowedApps(ctx) {
  const role = await roleOf(ctx);
  const out = [];
  for (const app of GATED_APPS) {
    if (await appAllowedForRole(role, app)) out.push(app);
  }
  return out;
}

/**
 * 应用门槛：把路由表里所有「裸 handler」条目统一包上应用授权判断——
 * 角色对该 app 无授权 → 403 { message: "无权访问该应用" }，否则原 handler。
 * 对象形态条目（带 public/page 字段的）原样放行不包装：
 * 如 agent.mjs 的 dev hook 是 public 调试路由，不属于应用门槛范围。
 */
export function gateApp(app, routes) {
  const out = {};
  for (const [key, value] of Object.entries(routes)) {
    out[key] = typeof value === "function" ? gateHandler(app, value) : value;
  }
  return out;
}

function gateHandler(app, handler) {
  return async (request, ctx) => {
    const role = await roleOf(ctx);
    if (!(await appAllowedForRole(role, app))) {
      return { kind: "error", status: 403, message: "无权访问该应用" };
    }
    return handler(request, ctx);
  };
}
