// 对象存储接口（COS mock 边界，2026-11-14 定）
// 接口：put/get/remove/exists，key 带前缀（papers/ snapshots/ backups/）。
// 驱动按 .env 的 STORAGE_DRIVER 切：local = 项目内 .data/storage（开发期零依赖）；
// cos 驱动上生产前补腾讯云 COS SDK，接口不变。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", ".data", "storage");

const safeKey = (key) => {
  const full = path.normalize(path.join(root, key));
  if (!full.startsWith(root + path.sep)) throw new Error("非法存储 key");
  return full;
};

export const storage = {
  async put(key, buf) {
    const full = safeKey(key);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, buf);
    return key;
  },
  async get(key) {
    const full = safeKey(key);
    if (!fs.existsSync(full)) return null;
    return fs.readFileSync(full);
  },
  async remove(key) {
    const full = safeKey(key);
    if (fs.existsSync(full)) fs.rmSync(full);
  },
  async exists(key) {
    return fs.existsSync(safeKey(key));
  },
  driver: () => process.env.STORAGE_DRIVER ?? "local",
};
