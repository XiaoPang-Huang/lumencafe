"""Skill 安装记录（架构设计-增量 v1 §3.2 user_skills）。

- 安装位置固定 app_id=chat（用户拍板）；用户级全局生效，装上即对全部对话生效（Q9）；
- prompt 服务端存储、用户不可改写（N-增5），任何接口不回写编辑；
- skillhub_id 为 SkillHub 平台 ID（本期为 mock id），同用户同应用下唯一。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (
        Index("ix_user_skills_user_app", "user_id", "app_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    app_id: Mapped[str] = mapped_column(String(32), default="chat")
    skillhub_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(String(256), default="")
    prompt: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
