"""步 A：papers 多源扩展——source/doi 列（只增不改旧；pmid 列扩长容纳 source:id 形态）。

- papers.source：数据源 key（pubmed/arxiv/openalex/semantic_scholar/doaj），存量行回填 pubmed；
- papers.doi：跨源去重键（小写裸 DOI，可空）+ 部分唯一索引（非空才唯一，NULL 不互斥）；
- papers.pmid 列放宽到 64：非 PubMed 源存 "{source}:{external_id}"（如 arxiv:2401.12345），
  唯一约束语义不变（全局去重键），存量纯数字 pmid 不受影响。

注：步 B 的 papers_crawl_runs 表顺延为 0007。

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column(
            "source", sa.String(length=32), nullable=False, server_default="pubmed"
        ),
    )
    op.add_column(
        "papers",
        sa.Column("doi", sa.String(length=512), nullable=True),
    )
    op.alter_column("papers", "pmid", type_=sa.String(length=64))
    # 部分唯一索引：doi 非空且非空串时全局唯一（跨源去重的库级兜底）
    op.create_index(
        "uq_papers_doi",
        "papers",
        ["doi"],
        unique=True,
        postgresql_where=sa.text("doi IS NOT NULL AND doi <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_papers_doi", table_name="papers")
    op.drop_column("papers", "doi")
    op.drop_column("papers", "source")
    op.alter_column("papers", "pmid", type_=sa.String(length=16))
