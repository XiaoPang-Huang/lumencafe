"""批次2：文献五表（架构设计 §3.8，预留原则——新迁移文件，不改 0001）。

papers / paper_users / paper_favorites / paper_notes / paper_explanations；
pmid 全局唯一，tags/keywords JSONB（`@>` 包含查询），解读缓存全局共享。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pmid", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("abstract_zh", sa.Text(), nullable=False, server_default=""),
        sa.Column("journal", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("authors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("pub_date", sa.Date(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("keywords", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("pmid"),
    )
    op.create_table(
        "paper_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id", "user_id"),
    )
    op.create_table(
        "paper_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id", "user_id"),
    )
    op.create_table(
        "paper_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id", "user_id"),
    )
    op.create_table(
        "paper_explanations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("paper_id"),
    )


def downgrade() -> None:
    op.drop_table("paper_explanations")
    op.drop_table("paper_notes")
    op.drop_table("paper_favorites")
    op.drop_table("paper_users")
    op.drop_table("papers")
