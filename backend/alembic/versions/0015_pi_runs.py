"""pi-runner 主体接入：pi_runs 任务记录表（只增不改旧）。

主体生成 run_id 并幂等派发给 pi-runner；本表记录状态机、错误、进度 JSONB
与产物对象键。产物正文不存库，经 storage（app=pi）落对象存储。

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "pi_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("artifacts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("result_key", sa.String(length=256), nullable=True),
        sa.Column("started_at", TZ, nullable=True),
        sa.Column("finished_at", TZ, nullable=True),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", name="uq_pi_runs_run_id"),
    )
    op.create_index("ix_pi_runs_user_created", "pi_runs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_pi_runs_user_created", table_name="pi_runs")
    op.drop_table("pi_runs")
