"""批次1地基：16 张业务表一次建好（架构设计 §3）

T02 建全部批次 1 ORM 模型对应的表：
账号与 RBAC 五表（§3.1）+ 模型管理三表（§3.2，含 gateway_tokens 增补6）
+ 应用注册表三表（§3.3）+ 对话两表（§3.4）+ 用户设置一表（§3.5）+ 记账两表（§3.6）。

说明：T01 时本文件为仅占位的空迁移（无任何库应用过）；按架构设计 §7
任务表「0001 迁移一次建 15 张（增补6 后 16 张）」，T02 直接填充本文件，
保持「全库一条 0001 初始迁移」的干净历史。批次 2 扩展一律走新迁移文件，不改本文件。

Revision ID: 0001
Revises: -
Create Date: 2026-10-14（T01 占位）/ 2026-10-18（T02 填充建表）

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # ── §3.1 账号与 RBAC（五表）───────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("nickname", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=128), nullable=False, server_default=""),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )

    # ── §3.2 模型管理（三表，含增补6 gateway_tokens）──────────
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("vendor", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("api_key", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    # 默认路由兜底：全库至多一个默认 Provider / 默认模型（部分唯一索引）
    op.create_index(
        "uq_providers_one_default", "providers", ["is_default"],
        unique=True, postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "llm_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("custom", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("provider_id", "name"),
    )
    op.create_index(
        "uq_llm_models_one_default", "llm_models", ["is_default"],
        unique=True, postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "gateway_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_mask", sa.String(length=32), nullable=False),
        sa.Column("model_scope", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("token_hash"),
    )

    # ── §3.3 应用注册表（三表）────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "app_registry",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("desc", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="#FFE0CC"),
        sa.Column("icon", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="chat"),
        sa.Column("perm_code", sa.String(length=64), nullable=False, server_default="app:chat"),
    )
    op.create_table(
        "app_visibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", sa.String(length=32), sa.ForeignKey("app_registry.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("category_id", sa.Integer(), nullable=True),  # 用户自定义分类，无 FK
        sa.UniqueConstraint("user_id", "app_id"),
    )

    # ── §3.4 对话（两表）──────────────────────────────────────
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", sa.String(length=32), sa.ForeignKey("app_registry.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False, server_default="新对话"),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("llm_models.id"), nullable=True),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_conv_user_app", "chat_conversations", ["user_id", "app_id", "updated_at"])
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("app_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_msg_conv", "chat_messages", ["conversation_id", "id"])
    op.create_index("ix_msg_user_time", "chat_messages", ["user_id", "created_at"])

    # ── §3.5 用户设置（一表）──────────────────────────────────
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "scope", "key"),
    )

    # ── §3.6 记账（两表，v1.1）────────────────────────────────
    op.create_table(
        "money_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="both"),
        sa.Column("icon", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('expense','income','both')", name="ck_money_cat_kind"),
        sa.UniqueConstraint("user_id", "built_in", "name"),
    )
    op.create_table(
        "money_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("money_categories.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount > 0", name="ck_money_txn_amount"),
        sa.CheckConstraint("type IN ('expense','income')", name="ck_money_txn_type"),
        sa.CheckConstraint("date <= CURRENT_DATE", name="ck_money_txn_date"),
        sa.UniqueConstraint("user_id", "request_id"),
    )
    op.create_index("ix_txn_user_date", "money_transactions", ["user_id", "date"])
    op.create_index("ix_txn_user_cat", "money_transactions", ["user_id", "category_id"])


def downgrade() -> None:
    """逆序删表（先删依赖方）。"""
    op.drop_table("money_transactions")
    op.drop_table("money_categories")
    op.drop_table("user_settings")
    op.drop_index("ix_msg_user_time", table_name="chat_messages")
    op.drop_index("ix_msg_conv", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conv_user_app", table_name="chat_conversations")
    op.drop_table("chat_conversations")
    op.drop_table("app_visibility")
    op.drop_table("app_registry")
    op.drop_table("categories")
    op.drop_table("gateway_tokens")
    op.drop_index("uq_llm_models_one_default", table_name="llm_models")
    op.drop_table("llm_models")
    op.drop_index("uq_providers_one_default", table_name="providers")
    op.drop_table("providers")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
