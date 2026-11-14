// 批 1 账号登录（需求 docs/需求-账号角色权限-v1.md 批 1）
// 自有账号体系：scrypt 密码哈希（node:crypto 内置，零新增依赖）、登录限速、
// 登录 / 登出 / 改密 / owner 引导建首个管理员。
// 会话仍走 chord：登录验证通过后 sessions.issue 发 chord-session cookie，
// principal 映射规则：admin → { kind: "owner" }，member → { kind: "member", name: username }
//（兼容既有 owner 数据的 key 与判断，chord 侧行为零改动）。
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { Sessions } from "@earendil-works/chord/app";
import { getPg } from "../db.mjs";

/* ---------- scrypt 密码哈希 ---------- */
const SCRYPT_N = 16384;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const SALT_LEN = 16;

/** 生成密码哈希：scrypt$N$r$p$<salt b64>$<hash b64> */
export function hashPassword(password) {
  const salt = randomBytes(SALT_LEN);
  const hash = scryptSync(password, salt, 64, { N: SCRYPT_N, r: SCRYPT_R, p: SCRYPT_P });
  return `scrypt$${SCRYPT_N}$${SCRYPT_R}$${SCRYPT_P}$${salt.toString("base64")}$${hash.toString("base64")}`;
}

/** 校验密码：解析哈希格式后重算，常量时间比较；格式非法一律 false */
export function verifyPassword(password, stored) {
  try {
    const parts = String(stored ?? "").split("$");
    if (parts.length !== 6 || parts[0] !== "scrypt") return false;
    const n = Number(parts[1]);
    const r = Number(parts[2]);
    const p = Number(parts[3]);
    if (!Number.isInteger(n) || !Number.isInteger(r) || !Number.isInteger(p)) return false;
    const salt = Buffer.from(parts[4], "base64");
    const expected = Buffer.from(parts[5], "base64");
    if (salt.length === 0 || expected.length === 0) return false;
    const actual = scryptSync(String(password), salt, expected.length, { N: n, r, p });
    return timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

/* ---------- 登录限速（内存 Map；key = `${username}|${ip}`） ---------- */
const LOGIN_MAX_FAILS = 5;
const LOGIN_LOCK_MS = 5 * 60 * 1000; // 连错 5 次锁 5 分钟
const SWEEP_MS = 10 * 60 * 1000;     // 每 10 分钟清扫过期项

const loginAttempts = new Map(); // key -> { fails, lockedUntil }

const sweepTimer = setInterval(() => {
  const now = Date.now();
  for (const [key, rec] of loginAttempts) {
    if (!rec.lockedUntil || rec.lockedUntil <= now) loginAttempts.delete(key);
  }
}, SWEEP_MS);
sweepTimer.unref();

/** 锁定期内返回 true（调用方直接 429） */
function isLocked(key) {
  const rec = loginAttempts.get(key);
  return Boolean(rec?.lockedUntil && rec.lockedUntil > Date.now());
}

/** 记一次失败；若触发锁定返回 true（本次响应也按 429 处理） */
function recordFail(key) {
  const rec = loginAttempts.get(key) ?? { fails: 0, lockedUntil: 0 };
  rec.fails += 1;
  if (rec.fails >= LOGIN_MAX_FAILS) {
    rec.lockedUntil = Date.now() + LOGIN_LOCK_MS;
    rec.fails = 0; // 解锁后重新计数
    loginAttempts.set(key, rec);
    return true;
  }
  loginAttempts.set(key, rec);
  return false;
}

/** 登录成功清零 */
function clearFails(key) {
  loginAttempts.delete(key);
}

const LOCK_MESSAGE = "尝试次数过多，请 5 分钟后再试";

/* ---------- principal → users 行 ---------- */
/**
 * chord principal 映射到自有账号整行：
 * - owner（chord 主人 / 我们登录的 admin）→ 第一名 role='admin' 的账号（兼容既有 owner 数据）
 * - member（chord 成员 / 我们登录的 member）→ username = principal.name
 * - 其他（如 server principal）→ null
 */
export async function userByPrincipal(ctx) {
  const pg = getPg();
  const principal = ctx.principal;
  if (principal?.kind === "owner") {
    const { rows } = await pg.query(
      "SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1",
    );
    return rows[0] ?? null;
  }
  if (principal?.kind === "member" && typeof principal.name === "string" && principal.name) {
    const { rows } = await pg.query(
      "SELECT * FROM users WHERE username = $1",
      [principal.name],
    );
    return rows[0] ?? null;
  }
  return null;
}

/** 对外暴露的用户信息（不含密码哈希） */
function toPublicUser(row) {
  return { username: row.username, displayName: row.display_name, role: row.role };
}

/** 尽力取客户端 IP（chord 请求对象暴露 remoteAddress；取不到记 "unknown"） */
function clientIp(request) {
  return typeof request.remoteAddress === "string" && request.remoteAddress
    ? request.remoteAddress
    : "unknown";
}

/** 解析 JSON body，失败返回 null（走统一参数错误） */
async function readJsonBody(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

/* ---------- 路由表 ---------- */
export function authRoutes() {
  return {
    // 登录（公开）：用户名 + 密码 → 验证通过后发 chord 会话 cookie
    "POST /api/auth/login": {
      public: true,
      handler: async (request, ctx) => {
        const body = await readJsonBody(request);
        const username = String(body?.username ?? "").trim().toLowerCase();
        const password = String(body?.password ?? "");
        const key = `${username}|${clientIp(request)}`;

        if (isLocked(key)) {
          return { kind: "error", status: 429, message: LOCK_MESSAGE };
        }

        const pg = getPg();
        const { rows } = await pg.query(
          "SELECT * FROM users WHERE username = $1",
          [username],
        );
        const user = rows[0];
        // 用户不存在 / 已停用 / 密码错：统一 401，不泄露哪一项错
        if (!user || user.enabled !== true || !verifyPassword(password, user.password_hash)) {
          if (recordFail(key)) {
            return { kind: "error", status: 429, message: LOCK_MESSAGE };
          }
          return { kind: "error", status: 401, message: "用户名或密码错误" };
        }
        clearFails(key);

        const principal = user.role === "admin"
          ? { kind: "owner" }
          : { kind: "member", name: user.username };
        const sessions = await ctx.get(Sessions, {});
        const secure = request.provenance.kind !== "local";
        const issued = await sessions.issue(
          { principal, label: user.username, kind: "browser", secure },
          ctx,
        );
        return {
          kind: "json",
          value: { ok: true },
          headers: { "Set-Cookie": issued.cookie },
        };
      },
    },

    // 登出：清 chord-session cookie（会话记录随其闲置过期，cookie 立即失效）
    "POST /api/auth/logout": async () => ({
      kind: "json",
      value: { ok: true },
      headers: { "Set-Cookie": "chord-session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0" },
    }),

    // 当前账号信息
    "GET /api/auth/me": async (_request, ctx) => {
      const user = await userByPrincipal(ctx);
      return { kind: "json", value: { user: user ? toPublicUser(user) : null } };
    },

    // 自助改密：旧密码验证 + 新密码 ≥ 8 位
    "POST /api/auth/password": async (request, ctx) => {
      const user = await userByPrincipal(ctx);
      if (!user) {
        return { kind: "error", status: 403, message: "该登录方式无密码" };
      }
      const body = await readJsonBody(request);
      if (!verifyPassword(String(body?.oldPassword ?? ""), user.password_hash)) {
        return { kind: "error", status: 401, message: "旧密码错误" };
      }
      const newPassword = String(body?.newPassword ?? "");
      if (newPassword.length < 8) {
        return { kind: "error", status: 400, message: "新密码至少 8 位" };
      }
      await getPg().query(
        "UPDATE users SET password_hash = $1, updated_at = now() WHERE id = $2",
        [hashPassword(newPassword), user.id],
      );
      return { kind: "json", value: { ok: true } };
    },

    // owner 引导建首个管理员：users 表为空时 needed=true
    "GET /api/auth/bootstrap": async (_request, ctx) => {
      if (ctx.principal?.kind !== "owner") {
        return { kind: "error", status: 403, message: "仅主人可用" };
      }
      const { rows } = await getPg().query("SELECT count(*)::int AS n FROM users");
      return { kind: "json", value: { needed: rows[0]?.n === 0 } };
    },

    // 创建首个管理员（仅 owner，仅当 users 表为空；幂等性由 409 保证）
    "POST /api/auth/bootstrap": async (request, ctx) => {
      if (ctx.principal?.kind !== "owner") {
        return { kind: "error", status: 403, message: "仅主人可用" };
      }
      const { rows } = await getPg().query("SELECT count(*)::int AS n FROM users");
      if ((rows[0]?.n ?? 0) > 0) {
        return { kind: "error", status: 409, message: "首个管理员已创建" };
      }
      const body = await readJsonBody(request);
      const username = String(body?.username ?? "").trim().toLowerCase();
      const displayName = String(body?.displayName ?? "").trim() || username;
      const password = String(body?.password ?? "");
      if (!/^[a-z0-9_]{2,32}$/.test(username)) {
        return {
          kind: "error",
          status: 400,
          message: "用户名需为 2-32 位小写字母、数字或下划线",
        };
      }
      if (password.length < 8) {
        return { kind: "error", status: 400, message: "密码至少 8 位" };
      }
      await getPg().query(
        "INSERT INTO users (username, display_name, password_hash, role) VALUES ($1, $2, $3, 'admin')",
        [username, displayName, hashPassword(password)],
      );
      return { kind: "json", value: { ok: true } };
    },
  };
}
