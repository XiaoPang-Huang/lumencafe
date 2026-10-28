"""论文域收藏并解析全链路（P16/P20）：papers 表补解析状态列与原文链接列（只增不改旧）。

- url：源落地页/OA 直链（PaperItem.url 落库；下载优先直链，失败走 Unpaywall 补链）；
- parse_status：解析状态机 none|pending|running|done|failed（默认 none，存量行 server_default）；
- parse_error：失败原因（可空，前端错误区展示 + 手动下载指引）；
- parsed_at：解析完成时间（可空）。

P20：原始 PDF 存 papers/pdfs/{yyyy}/{mm}/{paper_id}.pdf，解析产物存
papers/parsed/{paper_id}/full.md + content_list.json + meta.json（存储抽象层
强制 {app}/ 前缀，COS key 恒 papers/ 开头，本迁移不复述存储侧）。

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("url", sa.Text(), nullable=True))
    op.add_column(
        "papers",
        sa.Column("parse_status", sa.String(16), server_default="none", nullable=False),
    )
    op.add_column("papers", sa.Column("parse_error", sa.Text(), nullable=True))
    op.add_column("papers", sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "parsed_at")
    op.drop_column("papers", "parse_error")
    op.drop_column("papers", "parse_status")
    op.drop_column("papers", "url")
