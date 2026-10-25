"""批次4：网关路由升级（架构设计-增量 v2 B1/D2/D3，步 3）

- model_assignments：app_key → 主模型 + 有序备用链（按消费者指派，D2）；
- model_circuit_states：熔断状态存库（连挂摘出/冷却/探测，重启不丢，Q2）；
- llm_call_logs：调用记账（token 进出/耗时/成败/费用=单价快照×token，D3）；
- 单价不建独立列：挂 llm_models.meta 的 pricing 键（Q1 拍板，schemaless）。

只增不改旧（步 3 纪律红线）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    # D2：按消费者指派（app_key 唯一；备用链有序 JSONB，元素 = llm_models.id）
    op.create_table(
        "model_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_key", sa.String(length=64), nullable=False),
        sa.Column(
            "primary_model_id",
            sa.Integer(),
            sa.ForeignKey("llm_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fallback_chain",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at", TZ, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.UniqueConstraint("app_key", name="uq_model_assignments_app_key"),
    )

    # Q2：熔断状态（Portkey 语义：连挂 N 次摘出 → 冷却 → 每 30s 探测 → 成功切回）
    op.create_table(
        "model_circuit_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("llm_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "state", sa.String(length=16), nullable=False, server_default="closed"
        ),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("opened_at", TZ, nullable=True),
        sa.Column("next_probe_at", TZ, nullable=True),
        sa.Column(
            "updated_at", TZ, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.UniqueConstraint("model_id", name="uq_model_circuit_states_model"),
    )

    # D3：调用记账（Langfuse 费用模型：调用时固化单价快照，事后改价不动历史）
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_key", sa.String(length=64), nullable=False),
        sa.Column(
            "model_id",
            sa.Integer(),
            sa.ForeignKey("llm_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "output_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.String(length=512), nullable=True),
        # 单价快照（元/百万 token，可空 = 未定价/失败调用无 usage）
        sa.Column("input_price", sa.Numeric(12, 6), nullable=True),
        sa.Column("output_price", sa.Numeric(12, 6), nullable=True),
        sa.Column("cost", sa.Numeric(14, 6), nullable=True),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
    )
    # 统计页查询路径：时间筛选 + 按 app/模型聚合
    op.create_index(
        "ix_llm_call_logs_created_at", "llm_call_logs", ["created_at"]
    )
    op.create_index(
        "ix_llm_call_logs_app_key", "llm_call_logs", ["app_key", "created_at"]
    )
    op.create_index(
        "ix_llm_call_logs_model", "llm_call_logs", ["model_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_model", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_app_key", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_created_at", table_name="llm_call_logs")
    op.drop_table("llm_call_logs")
    op.drop_table("model_circuit_states")
    op.drop_table("model_assignments")
