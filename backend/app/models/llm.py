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
