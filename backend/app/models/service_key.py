"""服务 Key 表（架构设计-增量 v2.9）：异构服务（MinerU/FunASR/DashScope 等）钥匙集中管理。

只托管钥匙不走网关：后端服务用时按服务名（service_key）取 api_key/base_url 直连厂商；
轮换改库即生效、无需重启。api_key 仅存库不回显（接口一律掩码，见 admin_service_keys）。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ServiceKey(Base):
    __tablename__ = "service_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_key: Mapped[str] = mapped_column(String(64), unique=True)  # 服务标识（唯一）
    vendor: Mapped[str] = mapped_column(String(64))  # 厂商
    api_key: Mapped[str] = mapped_column(String(512))  # 完整钥匙（仅入库，接口不回显）
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 厂商网址（可空）
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 备注（可空）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
