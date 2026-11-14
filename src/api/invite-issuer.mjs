// 批 5 自动发钥匙：邀请链接签发器（服务端自调用 chord 的 POST /_chord/invites）
// 鉴权原理：app.ownerTokenFile 里是 chord 给 owner principal 签发的 device 会话
// token（id.secret 形态），chord 会话层支持 Authorization: Bearer <token>，
// 而 /_chord/invites 是 owner-only 路由——带上该 token 自调用即代表「主人发起邀请」，
// 不需要把 chord 内部 facet 翻出来，chord 升级也不受影响。
// 失败兜底：任何一步失败都抛错，由调用方（admin.mjs 建号）兜进 inviteError，不阻断主流程。
import fs from "node:fs";

let config = null; // { baseUrl, tokenFile }

/** 由 server.mjs 在 startServer 之后调用（此时才有 ownerTokenFile 路径） */
export function initInviteIssuer({ baseUrl, tokenFile }) {
  config = { baseUrl: String(baseUrl).replace(/\/+$/, ""), tokenFile };
}

/**
 * 给成员账号生成 chord 邀请链接（免密进系统；链接 7 天一次性有效，chord 语义）。
 * principal 固定为 { kind: "member", name: username }——与账号密码登录并存。
 */
export async function issueMemberInvite({ username, displayName }) {
  if (!config) throw new Error("邀请签发器未初始化（server.mjs 未调 initInviteIssuer）");
  const token = fs.readFileSync(config.tokenFile, "utf8").trim();
  if (!token) throw new Error("owner token 文件为空");
  const res = await fetch(`${config.baseUrl}/_chord/invites`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      principal: { kind: "member", name: username },
      label: displayName || username,
    }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || typeof data?.path !== "string") {
    throw new Error(`chord 邀请接口返回 HTTP ${res.status}`);
  }
  return { url: `${config.baseUrl}${data.path}` };
}
