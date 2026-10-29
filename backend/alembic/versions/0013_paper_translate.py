"""论文域轮③（P27）：papers 段落级中英对照翻译状态列（只增，可空）。

translate_status：none|running|done|failed（存量行/从未翻译为 NULL，语义同 none，
响应层回落 "none"）；translate_error：翻译失败原因（可空，前端失败态可见可重试）。

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("translate_status", sa.String(16), nullable=True),
    )
    op.add_column(
        "papers",
        sa.Column("translate_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("papers", "translate_error")
    op.drop_column("papers", "translate_status")
