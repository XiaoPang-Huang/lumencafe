// 页面外壳的静态服务（进程基础代码，插件经 @lumencafe/app/v1 取用）
// 插件脚本里不能用 import.meta.url / fs——路径解析必须放在主程序侧做
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const staticDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "static");
const indexFile = path.join(staticDir, "index.html");

const MIME = {
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".woff2": "font/woff2",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json; charset=utf-8",
};

// chord 默认 CSP 是 default-src 'none' 且没有 style-src——页面路由要自己加宽
const PAGE_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'self'",
].join("; ");

const readBody = (file) => {
  const buf = fs.readFileSync(file);
  return async (offset, length) => new Uint8Array(buf.subarray(offset, offset + length));
};

// 防目录穿越：规范化后必须仍落在 assets 目录内
const resolveAsset = (requestPath) => {
  const rel = decodeURIComponent(requestPath.replace(/^\/assets\//, ""));
  const assetsDir = path.join(staticDir, "assets");
  const full = path.normalize(path.join(assetsDir, rel));
  if (!full.startsWith(assetsDir + path.sep)) return null;
  return full;
};

// 外壳插件的路由表（返回给 plugins/shell 的 facet 用）
export function shellRoutes() {
  return {
    // 首页：公开（未登录也要能加载，前端检测登录态后跳 chord 的 /_chord/owner 登录页）
    "GET /": {
      public: true,
      page: true,
      handler: async () => ({
        kind: "html",
        body: fs.readFileSync(indexFile, "utf8"),
        headers: {
          "Content-Security-Policy": PAGE_CSP,
          "Cache-Control": "no-cache",
        },
      }),
    },
    // 静态资源：公开 + 长缓存（靠 ?v= 版本号刷新）
    "GET /assets/*": {
      public: true,
      handler: async (request) => {
        const file = resolveAsset(request.path);
        if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
          return { kind: "error", status: 404, message: "not found" };
        }
        const size = fs.statSync(file).size;
        return {
          kind: "bytes",
          mime: MIME[path.extname(file).toLowerCase()] ?? "application/octet-stream",
          size,
          read: readBody(file),
          inline: true,
        };
      },
    },
    // 登录态探测：默认拒绝——未登录 401，前端据此跳登录
    "GET /api/session": async (_request, ctx) => ({
      kind: "json",
      value: { principal: ctx.principal },
    }),
    // 管理面探针：RBAC 单点判断的样板（白皮书 §06 规矩：角色规则只在网关一处判断）
    // 匿名 401（chord 默认拒绝）；已登录非主人 403；主人 200
    "GET /api/admin/probe": async (_request, ctx) =>
      ctx.principal?.kind === "owner"
        ? { kind: "json", value: { ok: true, role: "owner" } }
        : { kind: "error", status: 403, message: "仅主人可用" },
  };
}
