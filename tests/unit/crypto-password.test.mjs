// 批 1：scrypt 密码哈希单元测试（纯函数，无 PG/服务依赖）
import test from "node:test";
import assert from "node:assert/strict";
import { hashPassword, verifyPassword } from "../../src/api/auth.mjs";

test("哈希格式正确且每次盐不同", () => {
  const a = hashPassword("secret-pass-1");
  const b = hashPassword("secret-pass-1");
  assert.match(a, /^scrypt\$16384\$8\$1\$.+\$.+$/);
  assert.notEqual(a, b, "同密码两次哈希必须不同（随机盐）");
});

test("正确密码校验通过", () => {
  const stored = hashPassword("my-password");
  assert.equal(verifyPassword("my-password", stored), true);
});

test("错误密码校验失败", () => {
  const stored = hashPassword("my-password");
  assert.equal(verifyPassword("wrong-password", stored), false);
  assert.equal(verifyPassword("", stored), false);
});

test("格式非法一律 false 且不抛错", () => {
  const good = hashPassword("my-password");
  for (const bad of [
    "", null, undefined, 42,
    "scrypt",                                  // 段数不足
    "scrypt$16384$8$1$onlysalt",               // 缺 hash 段
    "bcrypt$16384$8$1$AAAA$BBBB",              // 算法名不对
    "scrypt$abc$8$1$AAAA$BBBB",                // N 非整数
    "scrypt$16384$8$1$not-base64$also-not-b64",// base64 解析后为空
  ]) {
    assert.equal(verifyPassword("my-password", bad), false, `stored=${String(bad)}`);
  }
  // 篡改 hash 段：仍应安全返回 false
  const tampered = good.slice(0, -4) + "AAAA";
  assert.equal(verifyPassword("my-password", tampered), false);
});

test("超长密码与 Unicode 密码往返", () => {
  for (const pw of ["x".repeat(200), "密码-🔐-pässwörd", "a"]) {
    assert.equal(verifyPassword(pw, hashPassword(pw)), true);
  }
});
