// 密钥加解密（需求-模型API管理-v1.md R1：AES-256-GCM 入库）
// 主密钥来自 .env 的 LC_SECRET_KEY（scrypt 派生 32 字节）；未配置时降级为进程内随机密钥——
// 意味着重启后旧密文解不开（开发环境可接受，生产必须在 .env 配 LC_SECRET_KEY）。
// 密文格式: v1.<iv b64>.<tag b64>.<data b64>
import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";

let cachedKey = null;
let warned = false;

function masterKey() {
  if (cachedKey) return cachedKey;
  const secret = process.env.LC_SECRET_KEY;
  if (secret && secret.length >= 16) {
    cachedKey = scryptSync(secret, "lumencafe-model-keys", 32);
  } else {
    if (!warned) {
      warned = true;
      console.warn("[secret] LC_SECRET_KEY 未配置（或 <16 字符）：模型密钥用进程内随机密钥加密，重启后失效。生产请在 .env 配置。");
    }
    cachedKey = randomBytes(32);
  }
  return cachedKey;
}

/** 脱敏提示：sk-abcd…wxyz（前4后4），不足 8 位打全码 */
export function keyHint(plain) {
  const s = String(plain ?? "");
  if (!s) return "";
  if (s.length <= 8) return `${s.slice(0, 2)}…(${s.length})`;
  return `${s.slice(0, 4)}…${s.slice(-4)}`;
}

export function encryptSecret(plain) {
  const text = String(plain ?? "");
  if (!text) return "";
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", masterKey(), iv);
  const data = Buffer.concat([cipher.update(text, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1.${iv.toString("base64")}.${tag.toString("base64")}.${data.toString("base64")}`;
}

/** 解密失败返回 null（密文损坏 / 主密钥换了），调用方按「未配置密钥」处理 */
export function decryptSecret(cipherText) {
  const s = String(cipherText ?? "");
  if (!s) return null;
  try {
    const [v, ivB64, tagB64, dataB64] = s.split(".");
    if (v !== "v1") return null;
    const decipher = createDecipheriv("aes-256-gcm", masterKey(), Buffer.from(ivB64, "base64"));
    decipher.setAuthTag(Buffer.from(tagB64, "base64"));
    return Buffer.concat([decipher.update(Buffer.from(dataB64, "base64")), decipher.final()]).toString("utf8");
  } catch {
    return null;
  }
}
