"""论文域 P30：papers 全文状态列（全文与解析解耦，只增）。

fulltext_status：none|oa|uploaded（全文文件就绪度，与解析状态机解耦——
「获取全文」成功=oa、「上传全文」=uploaded、无文件=none）；fulltext_error：
获取全文失败原因（可空，前端失败态可见可重试）。reparse_pending：显式
「需重新解析」标志（替换文件且此前已解析/解析中 → true；解析发起即清）。

存量回填口径（拍板 P30，COS 抽样不可行）：parse_status ∈ (done, failed)
说明历史上走通/尝试走过下载步、PDF 已落 COS → fulltext_status='oa'；
其余（none/pending/running）→ 'none'。解析中（pending/running）行不打断，
由在跑的管线自然推进。

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("fulltext_status", sa.String(16), nullable=True),
    )
    op.add_column(
        "papers",
        sa.Column("fulltext_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "papers",
        sa.Column("reparse_pending", sa.Boolean(), nullable=True),
    )
    # 存量回填：历史跑过解析管线（done/failed）→ PDF 已在 COS = oa；其余 none
    op.execute(
        "UPDATE papers SET fulltext_status = 'oa' "
        "WHERE parse_status IN ('done', 'failed')"
    )
    op.execute(
        "UPDATE papers SET fulltext_status = 'none' WHERE fulltext_status IS NULL"
    )
    op.execute(
        "UPDATE papers SET reparse_pending = false WHERE reparse_pending IS NULL"
    )
    op.alter_column(
        "papers",
        "fulltext_status",
        nullable=False,
        server_default=sa.text("'none'"),
    )
    op.alter_column(
        "papers",
        "reparse_pending",
        nullable=False,
        server_default=sa.false(),
    )


def downgrade() -> None:
    op.drop_column("papers", "reparse_pending")
    op.drop_column("papers", "fulltext_error")
    op.drop_column("papers", "fulltext_status")
