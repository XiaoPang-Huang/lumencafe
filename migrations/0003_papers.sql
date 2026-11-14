-- 0003_papers.sql — 论文应用（第 3 批，白皮书 §08 论文拍板）
-- 库与业务数据落 PG；PDF 原件/Markdown 快照归 COS（本地 mock 见 src/api/storage.mjs）。

-- 论文元数据：doi 去重键；abstract_zh 翻译缓存；tags 文本数组
CREATE TABLE IF NOT EXISTS papers (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  doi         TEXT,
  pmid        TEXT,
  arxiv_id    TEXT,
  title       TEXT NOT NULL,
  authors     TEXT NOT NULL DEFAULT '',
  journal     TEXT NOT NULL DEFAULT '',
  year        INTEGER,
  cited_by    INTEGER NOT NULL DEFAULT 0,
  if_approx   TEXT NOT NULL DEFAULT '',
  abstract    TEXT NOT NULL DEFAULT '',
  abstract_zh TEXT NOT NULL DEFAULT '',
  tags        TEXT[] NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (doi)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_pmid ON papers (pmid) WHERE pmid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv ON papers (arxiv_id) WHERE arxiv_id IS NOT NULL;

-- 库内归属与状态：每人一条；阶段四段（fetch/upload/queue/parse 全走完 = done）；shared 逐篇共享
CREATE TABLE IF NOT EXISTS library_items (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  paper_id       BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  user_id        TEXT NOT NULL,               -- principal JSON key
  phase          TEXT NOT NULL DEFAULT 'fetch' CHECK (phase IN ('fetch','upload','queue','parse','done','failed')),
  phase_error    TEXT NOT NULL DEFAULT '',    -- 失败原因（说人话）
  fail_class     TEXT NOT NULL DEFAULT '',    -- 无元数据 / 有元数据无PDF / 付费墙 / 超护栏
  shared         BOOLEAN NOT NULL DEFAULT false,
  pdf_key        TEXT NOT NULL DEFAULT '',    -- 存储里的 key（PDF 原件）
  snapshot_key   TEXT NOT NULL DEFAULT '',    -- Markdown 快照 key
  request_id     TEXT NOT NULL UNIQUE,        -- 幂等：同一请求不重复建条目
  retry_of       BIGINT,                      -- 手动重试链
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (paper_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_items_user ON library_items (user_id, updated_at DESC);

-- 解析产物：block 锚点（问答出处、批注 anchor 都靠它）
CREATE TABLE IF NOT EXISTS parse_blocks (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  paper_id    BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  block_idx   INTEGER NOT NULL,               -- 篇内序号（稳定锚点）
  block_type  TEXT NOT NULL DEFAULT 'text',   -- text / heading / formula / table / image
  text_level  INTEGER NOT NULL DEFAULT 0,     -- 标题层级等
  page_no     INTEGER NOT NULL DEFAULT 0,
  content     TEXT NOT NULL DEFAULT '',
  content_zh  TEXT NOT NULL DEFAULT '',       -- 翻译缓存
  UNIQUE (paper_id, block_idx)
);

-- 批注笔记：anchor_block_id 点回原文；links 双链
CREATE TABLE IF NOT EXISTS annotations (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  paper_id      BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  user_id       TEXT NOT NULL,
  anchor_block  INTEGER NOT NULL,
  anchor_quote  TEXT NOT NULL DEFAULT '',
  body          TEXT NOT NULL DEFAULT '',
  links         TEXT[] NOT NULL DEFAULT '{}',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_anno_paper ON annotations (paper_id, user_id);

-- 切块向量：embedding 模型 = bge-m3（换模型全量重算，见白皮书 §11）
CREATE TABLE IF NOT EXISTS embeddings (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  paper_id   BIGINT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  block_idx  INTEGER NOT NULL,
  chunk_text TEXT NOT NULL DEFAULT '',
  vector     vector(1024),
  model      TEXT NOT NULL DEFAULT 'bge-m3',
  UNIQUE (paper_id, block_idx, model)
);
CREATE INDEX IF NOT EXISTS idx_emb_vector ON embeddings USING hnsw (vector vector_cosine_ops);
