// 测试公共件：独立测试库、临时数据目录、起真实服务、HTTP 会话。
// 约定（tests/README.md 同述）：
// - 测试代码全部在 tests/，与 src/ 分离；node --test 运行，零新增依赖。
// - 每个集成文件起一个真实服务（独立端口 + 独立 PG 测试库 + 独立 DATA_DIR），
//   互不干扰；用例间共享该文件的服务与数据，按序执行。
import { spawn } from "node:child_process";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import pg from "pg";
import "../src/env.mjs"; // 测试进程也要拿到 .env 的 DATABASE_URL（本进程环境变量优先）

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** 取一个空闲端口 */
export function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

const adminPg = () => {
  const u = new URL(process.env.DATABASE_URL);
  u.pathname = "/postgres"; // 维护库，用来 create/drop 测试库
  return new pg.Client({ connectionString: u.toString() });
};

/** 建独立测试库（存在先删）；返回连接串（库名带 pid+slug，防并发互踩） */
export async function createTestDb(slug) {
  const name = `lumencafe_test_${process.pid}_${slug}`.toLowerCase().replace(/[^a-z0-9_]/g, "_");
  const admin = adminPg();
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS ${name} WITH (FORCE)`);
  await admin.query(`CREATE DATABASE ${name}`);
  await admin.end();
  const u = new URL(process.env.DATABASE_URL);
  u.pathname = `/${name}`;
  return u.toString();
}

/** 删测试库 */
export async function dropTestDb(databaseUrl) {
  const name = new URL(databaseUrl).pathname.slice(1);
  const admin = adminPg();
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS ${name} WITH (FORCE)`);
  await admin.end();
}

/** 直连测试库执行 SQL（造测试数据/断言库内状态用） */
export async function sql(databaseUrl, text, params = []) {
  const client = new pg.Client({ connectionString: databaseUrl });
  await client.connect();
  try {
    return await client.query(text, params);
  } finally {
    await client.end();
  }
}

/**
 * 起真实服务（子进程）。等「主程序已启动」与 owner link 出现才返回。
 * envOverrides 会覆盖子进程环境（如 WXPUSH_WEBHOOK、DATA_DIR）。
 */
export async function startServer(slug, envOverrides = {}) {
  const port = await freePort();
  const databaseUrl = await createTestDb(slug);
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), `lc-test-${slug}-`));

  const proc = spawn(process.execPath, [path.join(rootDir, "src", "server.mjs")], {
    env: {
      ...process.env,
      PORT: String(port),
      DATABASE_URL: databaseUrl,
      DATA_DIR: dataDir,
      PUSH_SCHEDULER: "off", // 测试不触发定时推送
      ...envOverrides,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  const baseUrl = `http://127.0.0.1:${port}`;
  const ownerLink = await new Promise((resolve, reject) => {
    let out = "";
    const timer = setTimeout(() => reject(new Error(`服务启动超时\n${out}`)), 60_000);
    const onData = (buf) => {
      out += buf.toString();
      const m = out.match(/主人登录链接（一次性，10 分钟内有效）：\s*\n?\s*(\S+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
      if (/\[db\] 启动失败|migration .* 执行失败/.test(out)) {
        clearTimeout(timer);
        reject(new Error(`服务启动失败\n${out}`));
      }
    };
    proc.stdout.on("data", onData);
    proc.stderr.on("data", onData);
    proc.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`服务提前退出（code=${code}）\n${out}`));
    });
  });

  return {
    proc, baseUrl, databaseUrl, dataDir, ownerLink,
    stop: async () => {
      proc.kill("SIGTERM");
      await new Promise((resolve) => proc.once("exit", resolve));
      await dropTestDb(databaseUrl).catch(() => {});
      fs.rmSync(dataDir, { recursive: true, force: true });
    },
  };
}

/** 极简 HTTP 客户端：自动存取 chord-session cookie */
export class Client {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.cookie = "";
  }
  async req(method, path, body) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(this.cookie ? { Cookie: this.cookie } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    for (const sc of res.headers.getSetCookie()) {
      const pair = sc.split(";")[0];
      if (pair.startsWith("chord-session=")) {
        const value = pair.slice("chord-session=".length);
        this.cookie = value ? `chord-session=${value}` : "";
      }
    }
    const text = await res.text();
    let json = null;
    try { json = JSON.parse(text); } catch { /* text/plain 错误/HTML 页面 */ }
    // chord 的 kind:"error" 是 text/plain 正文（不是 JSON）；统一暴露 message 方便断言
    const message = json?.message ?? (json === null && !text.startsWith("<") && text ? text : undefined);
    return { status: res.status, json, text, message };
  }
  get(p) { return this.req("GET", p); }
  post(p, b) { return this.req("POST", p, b ?? {}); }
  patch(p, b) { return this.req("PATCH", p, b ?? {}); }
  put(p, b) { return this.req("PUT", p, b ?? {}); }
}

/** 消费 owner 一次性链接换 owner 会话（两步：GET 页面 → POST token） */
export async function ownerSession(server) {
  const link = new URL(server.ownerLink);
  const path = link.pathname; // 只取路径，Client 会拼 baseUrl
  const token = link.hash.slice(1);
  const client = new Client(server.baseUrl);
  await client.get(path); // 取页面（可能种 nonce）
  const res = await client.post(path, { token });
  if (res.status !== 200 || !client.cookie) {
    throw new Error(`owner 会话兑换失败：HTTP ${res.status} ${res.text}`);
  }
  return client;
}

/** 造 member 账号（绕过 bootstrap：直插 users，哈希用 auth.mjs 生成） */
export async function insertUser(databaseUrl, { username, password, role = "member", displayName, enabled = true }) {
  const { pathToFileURL } = await import("node:url");
  const { hashPassword } = await import(pathToFileURL(path.join(rootDir, "src", "api", "auth.mjs")).href);
  const { rows } = await sql(
    databaseUrl,
    `INSERT INTO users (username, display_name, password_hash, role, enabled)
     VALUES ($1,$2,$3,$4,$5) RETURNING id, username, role, enabled`,
    [username, displayName ?? username, hashPassword(password), role, enabled],
  );
  return rows[0];
}

/** 用户名+密码登录，成功返回带会话的 Client */
export async function loginAs(server, username, password) {
  const client = new Client(server.baseUrl);
  const res = await client.post("/api/auth/login", { username, password });
  if (res.status !== 200 || !client.cookie) {
    throw new Error(`登录失败 ${username}：HTTP ${res.status} ${res.text}`);
  }
  return client;
}
