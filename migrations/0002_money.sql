-- 0002_money.sql — 记账应用（第 2 批，白皮书 §08 记账拍板）
-- 账本数据落 PG（业务数据）；金额一律「分」整数；收入红支出绿由前端按 type 渲染。

-- 分类：每人一套（user_id），预置不可删可改名可隐藏；自建可删
CREATE TABLE IF NOT EXISTS categories (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    TEXT NOT NULL,                -- principal 的 JSON key
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
  built_in   BOOLEAN NOT NULL DEFAULT false,
  hidden     BOOLEAN NOT NULL DEFAULT false,
  sort       INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);

-- 账目：request_id 幂等键（AI 记一笔与表单同一条写路径）；shared=家庭账本
CREATE TABLE IF NOT EXISTS transactions (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     TEXT NOT NULL,               -- 归属人（私人=本人；shared=记账人）
  created_by  TEXT NOT NULL,               -- 创建人（shared 双方可改删，行内追溯）
  amount_fen  BIGINT NOT NULL CHECK (amount_fen > 0),
  type        TEXT NOT NULL CHECK (type IN ('income', 'expense')),
  category_id BIGINT NOT NULL REFERENCES categories(id),
  note        TEXT NOT NULL DEFAULT '',
  occurred_on DATE NOT NULL,
  shared      BOOLEAN NOT NULL DEFAULT false,
  request_id  TEXT NOT NULL UNIQUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions (user_id, occurred_on DESC);
CREATE INDEX IF NOT EXISTS idx_tx_family ON transactions (shared, occurred_on DESC) WHERE shared;
