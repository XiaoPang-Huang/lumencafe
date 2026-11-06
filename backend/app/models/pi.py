"""Pi Agent 执行记录（开发计划-pi-runner-v1 步 5）。

pi_runs 只记录主体派发给 pi-runner 的任务：状态机、错误、进度与产物键。
真正的模型成本由 pi-runner 专用 gateway token 走 /gw/v1 产生；结果文件经
对象存储落库（app=pi），本表不存正文。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PiRun(Base):
    """一次 pi-runner 任务（run_id 由主体生成，pi-runner 幂等接收）。"""

    __tablename__ = "pi_runs"
    __table_args__ = (
        Index("ix_pi_runs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    task: Mapped[str] = mapped_column(Text)
    # pending|running|completed|failed|aborted（与 pi-runner run_end.status 对齐）
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 进度/最近事件摘要/产物清单（JSONB；原地修改用 MutableDict 感知）
    progress: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    artifacts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    result_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
