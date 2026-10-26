"""批次5：底座小件——服务 Key 表（架构设计-增量 v2.9，异构服务钥匙集中管理）

非 LLM 的异构服务（MinerU 解析 / FunASR 语音 / DashScope 等）协议不是 OpenAI 兼容，
不走模型网关代理；但其 API 钥匙要集中管理（增删改、轮换不重启），故建 service_keys：
只托管钥匙，后端服务用时按服务名（service_key）取 key 直连厂商。

- service_key 唯一（服务标识，如 mineru / funasr / dashscope）；
- api_key 只存明文入库，任何接口不回显完整 key（一律掩码：前 4 + **** + 后 4）。

只增不改旧（增量纪律红线）。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "service_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_key", sa.String(length=64), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("api_key", sa.String(length=512), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at", TZ, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
        ),
        sa.UniqueConstraint("service_key", name="uq_service_keys_service_key"),
    )


def downgrade() -> None:
    op.drop_table("service_keys")
