-- 0001_init.sql — 最小建表（第 0 批 0B）
-- 说明：框架状态（登录/会话/账号/对话记录/pi-durable 检查点）在 chord 自带 SQLite，不在此列。
-- 业务表随各批追加；本批只立地基：pgvector 扩展、用户业务扩展、审计占位、后台待办表（Q17 拍板放 PG）。

-- pgvector 扩展（向量检索用，镜像自带；放最前，删库重建时一并恢复）
CREATE EXTENSION IF NOT EXISTS vector;

-- 用户业务侧扩展（与 chord 账号的 key 对应，一对零或一）
CREATE TABLE IF NOT EXISTS user_profiles (
  user_key     TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT '',
  preferences  JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 审计占位：关键动作留痕（谁、做了什么、细节），各批按需写入
CREATE TABLE IF NOT EXISTS audit_log (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,
  detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 业务后台待办表（Q17：与业务数据同库，「写数据 + 记待办」同一次事务）
-- 调度本身本批不实现（第 3 批起用），先把结构立住。
-- 规矩三「任务幂等」靠 idempotency_key 唯一约束保证：同一待办重复投递不会重复执行。
CREATE TABLE IF NOT EXISTS background_todos (
  id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind             TEXT NOT NULL,                -- 待办类型（如 paper.fetch），工人按类型认领
  payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
  status           TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
  idempotency_key  TEXT NOT NULL UNIQUE,
  attempts         INTEGER NOT NULL DEFAULT 0,
  max_attempts     INTEGER NOT NULL DEFAULT 3,
  run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),   -- 可领取时间
  locked_at        TIMESTAMPTZ,                          -- 被谁领取
  locked_by        TEXT,
  last_error       TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_background_todos_claim
  ON background_todos (status, run_at) WHERE status = 'pending';
