"""论文域轮①（P22/P23/P24/P26）：用户世界隔离 + 我的文献库 + 抓取进度字段（只增 + 约束重定向）。

- papers.user_id：行级归属（每日抓取按人入库，同一篇两人抓各存一份）；存量行回填
  口径 = **该篇最早 paper_users 归属人**（按归属 created_at、id 取首），无归属行
  回填 **admin**（users 表 username='admin' 的首行，种子保证存在）；
- papers.origin：crawl | import（轮②导入用），存量行回落 crawl；
- papers 去重键加 user 维度：旧全局 UniqueConstraint(pmid)（0002 未命名，PG 默认名
  papers_pmid_key）→ 唯一索引 uq_papers_user_pmid(user_id, pmid)（同用户内去重，
  跨用户各存一份）；
- 新表 paper_library：我的文献工作台（unique(user_id, paper_id)，added_via 记
  加入途径 crawl|import）；
- papers_crawl_runs.progress JSONB 可空：轮②「立即检索」阶段式进度条的数据源
  （phase + per_source 计数 + 当前关键词）。

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 0002 建表时 sa.UniqueConstraint("pmid") 未命名，PostgreSQL 默认命名 papers_pmid_key
_LEGACY_PMID_UQ = "papers_pmid_key"


def upgrade() -> None:
    # ── papers.user_id（先可空 → 回填 → NOT NULL）+ origin ──
    op.add_column("papers", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column(
        "papers",
        sa.Column("origin", sa.String(16), server_default="crawl", nullable=False),
    )

    # 存量行回填口径①：最早 paper_users 归属人（created_at、id 取首，确定性）
    op.execute(
        """
        UPDATE papers SET user_id = t.owner_id
        FROM (
            SELECT DISTINCT ON (paper_id) paper_id, user_id AS owner_id
            FROM paper_users
            ORDER BY paper_id, created_at ASC, id ASC
        ) t
        WHERE papers.id = t.paper_id
        """
    )
    # 存量行回填口径②：无归属行归 admin（种子用户，username='admin' 首行）
    op.execute(
        """
        UPDATE papers SET user_id = (
            SELECT id FROM users WHERE username = 'admin' ORDER BY id LIMIT 1
        )
        WHERE user_id IS NULL
        """
    )

    # 回填后仍有 NULL（理论上不可能：admin 恒在）则不强行 NOT NULL，避免迁移卡死
    conn = op.get_bind()
    remaining = conn.execute(
        sa.text("SELECT count(*) FROM papers WHERE user_id IS NULL")
    ).scalar()
    if remaining == 0:
        op.alter_column("papers", "user_id", nullable=False)

    op.create_foreign_key(
        "fk_papers_user_id", "papers", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_papers_user_id", "papers", ["user_id"])

    # 去重键加 user 维度：全局唯一 → (user_id, pmid) 唯一
    op.drop_constraint(_LEGACY_PMID_UQ, "papers", type_="unique")
    op.create_index("uq_papers_user_pmid", "papers", ["user_id", "pmid"], unique=True)

    # ── 新表：我的文献库（P22 工作台；删除级联 P24 的关联载体）──
    op.create_table(
        "paper_library",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.Integer(),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_via",
            sa.String(16),
            server_default="crawl",
            nullable=False,
        ),  # crawl（抓取/收藏并解析加入）| import（轮②导入）
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "paper_id", name="uq_paper_library_user_paper"),
    )
    op.create_index(
        "ix_paper_library_user_created", "paper_library", ["user_id", "created_at"]
    )

    # ── runs.progress：轮②检索进度条数据源（JSONB 可空，轮内实时更新）──
    op.add_column(
        "papers_crawl_runs", sa.Column("progress", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("papers_crawl_runs", "progress")
    op.drop_index("ix_paper_library_user_created", table_name="paper_library")
    op.drop_table("paper_library")
    op.drop_index("uq_papers_user_pmid", table_name="papers")
    op.create_unique_constraint(_LEGACY_PMID_UQ, "papers", ["pmid"])
    op.drop_index("ix_papers_user_id", table_name="papers")
    op.drop_constraint("fk_papers_user_id", "papers", type_="foreignkey")
    op.drop_column("papers", "origin")
    op.drop_column("papers", "user_id")
