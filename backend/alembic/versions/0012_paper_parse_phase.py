"""论文域轮②（P25/P26）：papers.parse_phase 阶段列（只增，可空）。

解析五段阶段条（下载→上传→排队→解析中→完成）的数据源：状态机推进时写
download|upload|queue|parsing，完成清空（done 由 parse_status 承载），
失败保留在出错阶段（前端把该段标红）。

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("parse_phase", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("papers", "parse_phase")
