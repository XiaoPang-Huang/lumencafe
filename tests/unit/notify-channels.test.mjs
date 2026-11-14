// 批 5：notify 推送三态单元测试（本地假 webhook，不外网、不真推）
import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { notify } from "../../src/api/notify.mjs";

const save = { ...process.env };
const restore = () => {
  for (const k of ["WXPUSH_WEBHOOK", "SERVERCHAN_SENDKEY"]) {
    if (save[k] === undefined) delete process.env[k];
    else process.env[k] = save[k];
  }
};
const clearChannels = () => {
  delete process.env.WXPUSH_WEBHOOK;
  delete process.env.SERVERCHAN_SENDKEY;
};

test("两通道都没配 → channel=none，不抛错", async () => {
  clearChannels();
  const r = await notify("测试消息");
  assert.deepEqual([r.ok, r.channel], [false, "none"]);
  restore();
});

test("企业微信主通道成功 → ok/channel=wxwork，正文到达", async () => {
  clearChannels();
  let got = null;
  const srv = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      got = JSON.parse(body);
      res.end(JSON.stringify({ errcode: 0 }));
    });
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  const port = srv.address().port;
  process.env.WXPUSH_WEBHOOK = `http://127.0.0.1:${port}/hook`;
  try {
    const r = await notify("批5测试正文");
    assert.deepEqual([r.ok, r.channel], [true, "wxwork"]);
    assert.equal(got.markdown.content, "批5测试正文");
  } finally {
    srv.close();
    restore();
  }
});

test("主通道挂了且无备通道 → ok=false（failed 态），不抛错", async () => {
  clearChannels();
  // 无监听端口 → 连接即失败
  process.env.WXPUSH_WEBHOOK = "http://127.0.0.1:9/unreachable";
  const r = await notify("x");
  assert.equal(r.ok, false);
  assert.match(r.detail, /主备都失败/);
  restore();
});

test("主通道返回业务错误码 → 视为失败（ok=false）", async () => {
  clearChannels();
  const srv = http.createServer((req, res) => {
    res.end(JSON.stringify({ errcode: 93000, errmsg: "invalid webhook" }));
  });
  await new Promise((r) => srv.listen(0, "127.0.0.1", r));
  process.env.WXPUSH_WEBHOOK = `http://127.0.0.1:${srv.address().port}/hook`;
  try {
    const r = await notify("x");
    assert.equal(r.ok, false);
    assert.match(r.detail, /93000/);
  } finally {
    srv.close();
    restore();
  }
});
