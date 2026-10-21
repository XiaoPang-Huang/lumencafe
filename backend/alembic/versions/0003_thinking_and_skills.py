"""批次3：对话思考双流 + Skill 接入（架构设计-增量 v1 §3.2/§3.4）

- chat_messages 增列 reasoning（R2：思维全文，可空 TEXT，随 assistant 消息落库）；
- chat_conversations 增列 thinking_level（P0-2 ⑤：会话级档位快照，与 model_id 同模式）；
- user_skills 表（SkillHub 安装记录，prompt 服务端存储、用户不可改写，N-增5）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # R2：思维链全文（64KB 截断在 service 层做，列本身不限长）
    op.add_column(
        "chat_messages",
        sa.Column("reasoning", sa.Text(), nullable=True),
    )
    # P0-2 ⑤：会话级 thinking_level 快照（R1 边界②：仅会话级，无全局默认）
    op.add_column(
        "chat_conversations",
        sa.Column("thinking_level", sa.String(length=32), nullable=True),
    )
    # Skill 安装记录：安装位置固定 chat（用户拍板），用户级全局生效（Q9）
    op.create_table(
        "user_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("app_id", sa.String(length=32), nullable=False, server_default="chat"),
        sa.Column("skillhub_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False),  # 服务端存储，用户不可改写
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("installed_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "app_id", "skillhub_id", name="uq_user_skill"),
    )
    op.create_index(
        "ix_user_skills_user_app", "user_skills", ["user_id", "app_id", "enabled"]
    )


def downgrade() -> None:
    op.drop_index("ix_user_skills_user_app", table_name="user_skills")
    op.drop_table("user_skills")
    op.drop_column("chat_conversations", "thinking_level")
    op.drop_column("chat_messages", "reasoning")
