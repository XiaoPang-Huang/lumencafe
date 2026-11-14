-- 批 1 账号登录：自有账号表（chord 降级为纯会话管道，账号与角色归我们）
-- 密码只存 scrypt 哈希（格式 scrypt$N$r$p$salt_b64$hash_b64），见 src/api/auth.mjs
CREATE TABLE users (
  id            SERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
  enabled       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
