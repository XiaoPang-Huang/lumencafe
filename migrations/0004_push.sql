-- 0004_push.sql — 定时推送（第 4 批，白皮书 §08 定时抓取推送时序图）
-- 订阅关键词独立建表（2026-11-13 拍板，不沿用 settings 键）；push_logs 按 push_key 幂等防重复推送。

CREATE TABLE IF NOT EXISTS subscriptions (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    TEXT NOT NULL,               -- principal JSON key
  keyword    TEXT NOT NULL,
  sources    TEXT[] NOT NULL DEFAULT '{arxiv,s2}',
  enabled    BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, keyword)
);

CREATE TABLE IF NOT EXISTS crawl_runs (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at    TIMESTAMPTZ,
  status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed')),
  keyword        TEXT NOT NULL DEFAULT '',   -- 本轮按关键词逐条记
  found_count    INTEGER NOT NULL DEFAULT 0,
  new_count      INTEGER NOT NULL DEFAULT 0,
  error          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_crawl_runs_time ON crawl_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS push_logs (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  push_key   TEXT NOT NULL UNIQUE,          -- 幂等键：digest-YYYY-MM-DD
  channel    TEXT NOT NULL DEFAULT '',      -- wxwork / serverchan / none
  ok         BOOLEAN NOT NULL DEFAULT false,
  detail     TEXT NOT NULL DEFAULT '',
  new_count  INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
