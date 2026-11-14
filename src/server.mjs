// 流光咖啡馆 · 主程序入口（第 0 批 0A：chord 最小启动）
import { startServer } from "@earendil-works/chord/app";
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { initDb } from "./db.mjs";
import * as apiV1 from "./api/v1.mjs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// ---- 读 .env（自己解析，不引第三方依赖；环境变量优先）----
const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const envFile = path.join(rootDir, ".env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && m[1] && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}

const port = Number(process.env.PORT) || 8480;

// 先连 PG、跑完 migration，失败直接退出（fail fast），不静默带病启动
let db;
try {
  db = await initDb(process.env.DATABASE_URL);
} catch (error) {
  console.error(`[db] 启动失败：${error.message}`);
  process.exit(1);
}

// 后台下载解析工人（慢活并发 1；白皮书 §10 三规矩）
import { startPaperWorker } from "./api/pipeline.mjs";
startPaperWorker();

// 定时推送（每日早 8 点 digest；主程序内定时器，不开新进程）
import { startPushScheduler } from "./api/digest.mjs";
startPushScheduler();

const app = await startServer(
  {
    name: "lumencafe",
    dataDir: path.join(rootDir, ".data"),
    root: path.join(rootDir, "plugins"),
    listen: { host: "127.0.0.1", port },
    api: {
      name: "@lumencafe/app",
      versions: ["v1"],
      modules: { "@lumencafe/app/v1": apiV1 },
    },
    kinds: { server: { platform: "node" } },
    principal: {
      server: { kind: "server" },
      owner: { kind: "owner" },
    },
    onError: (error) => {
      console.error("[chord] 运行错误:", error);
    },
  },
  BACKGROUND_CONTEXT,
);

console.log(`\n流光咖啡馆主程序已启动（端口 ${port}）`);
console.log(`主人登录链接（一次性，10 分钟内有效）：\n  ${app.ownerLink()}\n`);

const shutdown = async () => {
  await app.close(BACKGROUND_CONTEXT);
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
