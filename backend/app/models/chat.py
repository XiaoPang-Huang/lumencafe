"""对话模型（架构设计 §3.4，两表）。

chat_messages 冗余 user_id / app_id：隔离查询与限流统计不走 JOIN。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("ix_conv_user_app", "user_id", "app_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    app_id: Mapped[str] = mapped_column(String(32), ForeignKey("app_registry.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(64), default="新对话")
    model_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("llm_models.id"))
    # P0-2 ⑤：会话级思考档位快照（与 model_id 同模式，切换只影响后续消息）
    thinking_level: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_msg_conv", "conversation_id", "id"),
        Index("ix_msg_user_time", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    app_id: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(String, default="")
    # R2：思维链全文（可空；落库前 service 层 64KB 截断；历史回看不回注厂商，Q4）
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
