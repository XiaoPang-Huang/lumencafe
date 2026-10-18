"""文献模型（批次 2，架构设计 §3.8/PRD §4.8，五表）。

- papers：题录全局表，pmid 全局唯一；tags/keywords 为 JSONB（`@>` 查询）；
- paper_users：归属表（哪篇推送给哪个用户，隔离依据）；
- paper_favorites / paper_notes：收藏（幂等 toggle）与笔记（每人每篇一条 upsert）；
- paper_explanations：AI 解读全局缓存（一篇一条，成功才入库，全局共享）。
"""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pmid: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    abstract_zh: Mapped[str] = mapped_column(Text, default="")  # LLM 中译（空串 = 未译）
    journal: Mapped[str] = mapped_column(String(256), default="")
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    pub_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # AD/PD/ALS/scale
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperUser(Base):
    """归属表：文献推送给哪些用户（PRD 4.8 归属隔离）。"""

    __tablename__ = "paper_users"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperFavorite(Base):
    __tablename__ = "paper_favorites"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperNote(Base):
    """每人每篇一条笔记（upsert 覆盖）。"""

    __tablename__ = "paper_notes"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperExplanation(Base):
    """AI 解读全局缓存：一篇一条，成功才入库（PRD 4.8）。"""

    __tablename__ = "paper_explanations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("papers.id", ondelete="CASCADE"), unique=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
