// 推送通道（白皮书 §15-4：企业微信群机器人主 + Server 酱备；代码不进核心，统一 notify 出口）
// 通道地址/钥匙只进 .env：WXPUSH_WEBHOOK（企业微信机器人 Webhook 完整地址）、SERVERCHAN_SENDKEY。
// 未配置时返回 ok=false channel='none'，调用方照常记 push_logs（失败可次日补推/手动重试）。

async function pushWxwork(text) {
  const webhook = process.env.WXPUSH_WEBHOOK;
  if (!webhook) throw new Error("未配置 WXPUSH_WEBHOOK");
  const res = await fetch(webhook, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ msgtype: "markdown", markdown: { content: text.slice(0, 4000) } }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.errcode !== 0) throw new Error(`企业微信返回 ${data.errcode ?? res.status}：${data.errmsg ?? ""}`);
  return data;
}

async function pushServerChan(text) {
  const key = process.env.SERVERCHAN_SENDKEY;
  if (!key) throw new Error("未配置 SERVERCHAN_SENDKEY");
  const res = await fetch(`https://sctapi.ftqq.com/${key}.send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "流光咖啡馆 · 论文 digest", desp: text.slice(0, 8000) }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.code !== 0) throw new Error(`Server 酱返回 ${data.code ?? res.status}`);
  return data;
}

/** 统一推送出口：主通道失败自动换备通道；结果交给调用方落 push_logs */
export async function notify(text) {
  if (!process.env.WXPUSH_WEBHOOK && !process.env.SERVERCHAN_SENDKEY) {
    console.warn("[push] 未配置任何推送通道（WXPUSH_WEBHOOK / SERVERCHAN_SENDKEY），本条只记日志");
    return { ok: false, channel: "none", detail: "未配置通道" };
  }
  try {
    await pushWxwork(text);
    return { ok: true, channel: "wxwork", detail: "" };
  } catch (primary) {
    console.warn("[push] 主通道（企业微信）失败：", primary.message);
    try {
      await pushServerChan(text);
      return { ok: true, channel: "serverchan", detail: `主通道失败已切备：${primary.message}` };
    } catch (fallback) {
      return { ok: false, channel: "wxwork", detail: `主备都失败：${primary.message}；${fallback.message}` };
    }
  }
}
