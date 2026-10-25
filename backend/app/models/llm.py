"""模型管理模型（架构设计 §3.2，三表：providers / llm_models / gateway_tokens）。

- 纯网关：无应用绑定表；默认路由 = providers.is_default + llm_models.is_default 两标记；
- is_default 用部分唯一索引兜底「全库至多一个」（PostgreSQL 限定）；
- gateway_tokens 仅存哈希，展示一律掩码（增补6）。
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _gen_public_id() -> str:
    """gateway_tokens 对外 ID（生成令牌明文时作前缀）。"""
    return uuid.uuid4().hex[:24]


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        Index(
            "uq_providers_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    vendor: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key: Mapped[str] = mapped_column(String(256), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    models: Mapped[list["LLMModel"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", lazy="selectin"
    )


class LLMModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        Index(
            "uq_llm_models_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("providers.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    custom: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    provider: Mapped[Provider] = relationship(back_populates="models")


class ModelAssignment(Base):
    """按消费者指派（架构设计-增量 v2 D2）：app_key → 主模型 + 有序备用链。"""

    __tablename__ = "model_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_key: Mapped[str] = mapped_column(String(64), unique=True)
    primary_model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("llm_models.id", ondelete="CASCADE")
    )
    # 有序备用链（JSONB）：元素 = llm_models.id，按兜底顺序排列
    fallback_chain: Mapped[list[int]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelCircuitState(Base):
    """熔断状态（Q2，Portkey 语义）：连挂 N 次摘出 → 冷却 → 探测 → 恢复切回。

    状态机：closed（正常）→ open（摘出，跳过路由）→ 冷却到点后探测
    （下一个请求即探针，成功 closed / 失败重开并进入 30s 探测间隔）。
    """

    __tablename__ = "model_circuit_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("llm_models.id", ondelete="CASCADE"), unique=True
    )
    state: Mapped[str] = mapped_column(String(16), default="closed")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMCallLog(Base):
    """调用记账（D3，Langfuse 费用模型）：一次 LLM 调用一条，费用=单价快照×token。"""

    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_key: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("llm_models.id", ondelete="SET NULL"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String(64), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 单价快照（元/百万 token）：调用时固化，事后改价不动历史账
    input_price: Mapped[float | None] = mapped_column(nullable=True)
    output_price: Mapped[float | None] = mapped_column(nullable=True)
    cost: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GatewayToken(Base):
    __tablename__ = "gateway_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, default=_gen_public_id)
    name: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    token_mask: Mapped[str] = mapped_column(String(32))
    model_scope: Mapped[list[str] | None] = mapped_column(JSON)  # NULL = 全部模型
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
