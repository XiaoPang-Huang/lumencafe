"""论文域元数据增强：papers 表补引用数与影响因子近似列（只增不改旧）。

- cited_count：被引次数（OpenAlex cited_by_count / S2 citationCount）；
- if_approx：影响因子近似口径 = OpenAlex summary_stats 2yr_mean_citedness
  （两年篇均引用，非 JCR 官方值，界面标注「≈」）；
- authors/journal/pub_date 三列批次 2 已存在（authors JSONB / journal String /
  pub_date Date），本迁移不复述。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("cited_count", sa.Integer(), nullable=True))
    op.add_column("papers", sa.Column("if_approx", sa.Numeric(10, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("papers", "if_approx")
    op.drop_column("papers", "cited_count")
