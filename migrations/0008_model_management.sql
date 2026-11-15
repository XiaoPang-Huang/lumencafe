-- 模型 & API 管理（需求-模型API管理-v1.md §4；2026-11-15 拍板 R1-R4）
-- 三级：供应商 provider → 渠道套餐 plan → 模型 model；外加授权与调用日志

CREATE TABLE model_providers (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  code          TEXT NOT NULL UNIQUE,
  protocol      TEXT NOT NULL CHECK (protocol IN ('openai','anthropic','mineru')),
  base_url      TEXT NOT NULL,
  auth_type     TEXT NOT NULL DEFAULT 'bearer' CHECK (auth_type IN ('bearer','header','query','none')),
  auth_config   JSONB NOT NULL DEFAULT '{}'::jsonb,
  key_cipher    TEXT NOT NULL DEFAULT '',
  key_hint      TEXT NOT NULL DEFAULT '',
  enabled       BOOLEAN NOT NULL DEFAULT true,
  scope         TEXT NOT NULL DEFAULT 'system' CHECK (scope IN ('system','personal')),
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  remark        TEXT NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_plans (
  id          SERIAL PRIMARY KEY,
  provider_id INTEGER NOT NULL REFERENCES model_providers(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  plan_type   TEXT NOT NULL DEFAULT 'official' CHECK (plan_type IN ('official','tokenplan','agentplan','third_party')),
  base_url    TEXT NOT NULL DEFAULT '',
  key_cipher  TEXT NOT NULL DEFAULT '',
  key_hint    TEXT NOT NULL DEFAULT '',
  rpm_limit   INTEGER NOT NULL DEFAULT 0,
  daily_limit INTEGER NOT NULL DEFAULT 0,
  enabled     BOOLEAN NOT NULL DEFAULT true,
  remark      TEXT NOT NULL DEFAULT '',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE models (
  id                 SERIAL PRIMARY KEY,
  plan_id            INTEGER REFERENCES model_plans(id) ON DELETE CASCADE,
  provider_id        INTEGER NOT NULL REFERENCES model_providers(id) ON DELETE CASCADE,
  model_id           TEXT NOT NULL,
  ref                TEXT NOT NULL UNIQUE,
  display_name       TEXT NOT NULL,
  enabled            BOOLEAN NOT NULL DEFAULT true,
  is_common          BOOLEAN NOT NULL DEFAULT false,
  context_window     INTEGER,
  max_output_tokens  INTEGER,
  input_price        NUMERIC(12,6),
  output_price       NUMERIC(12,6),
  supports_tools     BOOLEAN NOT NULL DEFAULT false,
  source             TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','fetched')),
  fetched_at         TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider_id, model_id)
);

CREATE TABLE model_grants (
  id           SERIAL PRIMARY KEY,
  model_id     INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  grantee_type TEXT NOT NULL CHECK (grantee_type IN ('role','user')),
  grantee      TEXT NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (model_id, grantee_type, grantee)
);

CREATE TABLE llm_call_logs (
  id                BIGSERIAL PRIMARY KEY,
  model_id          INTEGER,
  plan_id           INTEGER,
  provider_id       INTEGER,
  user_id           INTEGER NOT NULL,
  app               TEXT NOT NULL DEFAULT 'chat',
  conversation_id   TEXT NOT NULL DEFAULT '',
  prompt_tokens     INTEGER,
  completion_tokens INTEGER,
  cost_fen          INTEGER NOT NULL DEFAULT 0,
  latency_ms        INTEGER NOT NULL DEFAULT 0,
  status            TEXT NOT NULL CHECK (status IN ('ok','failed','stopped')),
  error_code        TEXT NOT NULL DEFAULT '',
  error_msg         TEXT NOT NULL DEFAULT '',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_logs_model ON llm_call_logs (model_id, created_at DESC);
CREATE INDEX idx_llm_logs_user  ON llm_call_logs (user_id, created_at DESC);
CREATE INDEX idx_llm_logs_time  ON llm_call_logs (created_at DESC);
