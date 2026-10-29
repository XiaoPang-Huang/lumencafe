"""论文域后批①（P8）：paper_notes 表改造为「全文笔记 + 批注」双形态（只增列 + 约束精化）。

- anchor_quote：被选中原文（划线/批注都存；hypothes.is 式 TextQuoteSelector，
  重解析后 block 位移时的人工找回依据）；
- anchor_block_id：锚定段落标识（content_list 派生的 `p{页}_b{页内序}`，见
  services/paper_content.py 规则说明）；
- note_kind：annotation | note（存量行 server_default='note'，旧行为不受影响）；
- links：JSONB 出链批注 id 数组（知识网边；反向链接由查询派生，不双写）。

约束精化（批注每篇可多条，全文笔记仍每篇至多一条）：
- 旧 UniqueConstraint(paper_id, user_id)（0002 未命名，PG 默认名
  paper_notes_paper_id_user_id_key）整表唯一会挡住批注多行 → 降级为
  **部分唯一索引** uq_paper_notes_legacy_note（仅 note_kind='note' 的行），
  旧 upsert 语义逐字保留；另建普通索引 ix_paper_notes_paper_user 支撑
  按篇拉批注列表。

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 0002 建表时 sa.UniqueConstraint("paper_id", "user_id") 未命名，
# PostgreSQL 默认命名规则：<table>_<cols>_key
_LEGACY_UQ = "paper_notes_paper_id_user_id_key"


def upgrade() -> None:
    # ── 新增列（全部带 server_default，存量行零迁移成本）──
    op.add_column("paper_notes", sa.Column("anchor_quote", sa.String(2000), nullable=True))
    op.add_column("paper_notes", sa.Column("anchor_block_id", sa.String(64), nullable=True))
    op.add_column(
        "paper_notes",
        sa.Column("note_kind", sa.String(16), server_default="note", nullable=False),
    )
    op.add_column(
        "paper_notes",
        sa.Column("links", postgresql.JSONB(), server_default="[]", nullable=False),
    )
    op.add_column(
        "paper_notes",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── 约束精化：整表唯一 → 部分唯一索引（仅全文笔记，Index 形态与 ORM 元数据一致）+ 列表索引 ──
    op.drop_constraint(_LEGACY_UQ, "paper_notes", type_="unique")
    op.create_index("ix_paper_notes_paper_user", "paper_notes", ["paper_id", "user_id"])
    op.create_index(
        "uq_paper_notes_legacy_note",
        "paper_notes",
        ["paper_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("note_kind = 'note'"),
    )


def downgrade() -> None:
    op.drop_index("uq_paper_notes_legacy_note", table_name="paper_notes")
    op.drop_index("ix_paper_notes_paper_user", table_name="paper_notes")
    op.create_unique_constraint(
        _LEGACY_UQ, "paper_notes", ["paper_id", "user_id"]
    )  # 若已有批注多行会失败——降级前需先清批注行
    op.drop_column("paper_notes", "links")
    op.drop_column("paper_notes", "note_kind")
    op.drop_column("paper_notes", "anchor_block_id")
    op.drop_column("paper_notes", "anchor_quote")
    op.drop_column("paper_notes", "created_at")
