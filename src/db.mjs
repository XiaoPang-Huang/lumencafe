// PG 连接层 + migration 机制（第 0 批 0B）
// 约定：
// - 连接参数读 .env 的 DATABASE_URL（server.mjs 已把 .env 解析进 process.env）
// - 不用 ORM；migration 是 migrations/ 下的顺序 SQL 文件，自建版本号表记录已执行的
// - 启动时连不上 PG 直接抛错（fail fast，主程序不静默带病跑）
import pg from "pg";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const migrationsDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "migrations");

/** 连上 PG 并跑完未执行的 migration；返回当前版本号。连不上直接抛错。 */
export async function initDb(databaseUrl) {
  const client = new pg.Client({ connectionString: databaseUrl });
  try {
    await client.connect();
  } catch (error) {
    await client.end().catch(() => {});
    throw new Error(`连不上 PostgreSQL（请确认 pg 容器已启动、DATABASE_URL 正确）：${error.message}`);
  }

  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS _migrations (
        version    INTEGER PRIMARY KEY,
        name       TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
      )
    `);

    const files = fs
      .readdirSync(migrationsDir)
      .filter((f) => f.endsWith(".sql"))
      .sort();

    const { rows } = await client.query("SELECT version FROM _migrations");
    const applied = new Set(rows.map((r) => r.version));

    for (const file of files) {
      const version = Number(file.match(/^(\d+)/)?.[1]);
      if (!version || applied.has(version)) continue;

      const sql = fs.readFileSync(path.join(migrationsDir, file), "utf8");
      // 单文件单事务：失败整体回滚，版本号不落，下次启动重跑
      await client.query("BEGIN");
      try {
        await client.query(sql);
        await client.query("INSERT INTO _migrations (version, name) VALUES ($1, $2)", [version, file]);
        await client.query("COMMIT");
        console.log(`[db] 已执行 migration：${file}`);
      } catch (error) {
        await client.query("ROLLBACK");
        throw new Error(`migration ${file} 执行失败：${error.message}`);
      }
    }

    const { rows: latest } = await client.query(
      "SELECT version FROM _migrations ORDER BY version DESC LIMIT 1",
    );
    const version = latest[0]?.version ?? 0;
    console.log(`[db] PG 连接成功，migration 版本：${version}`);
    return { client, version };
  } catch (error) {
    await client.end().catch(() => {});
    throw error;
  }
}
