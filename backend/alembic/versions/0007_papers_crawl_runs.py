"""步 B：papers_crawl_runs 抓取轮次记录表（只增不改旧）。

- 每轮抓取结束写一行（成功/失败都写）；trigger = schedule|manual；
- stats JSONB 承载轮内统计（per_source 各源命中/新增数、users 覆盖用户数等）；
- run_at 索引：digest 接口取「最近一次抓取」与页面「已更新于 HH:MM」。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "papers_crawl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("stats", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_papers_crawl_runs_run_at", "papers_crawl_runs", ["run_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_papers_crawl_runs_run_at", table_name="papers_crawl_runs")
    op.drop_table("papers_crawl_runs")
