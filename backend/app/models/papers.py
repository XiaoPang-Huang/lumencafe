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
    # 全局去重键：PubMed 为纯数字 pmid；其余源为 "{source}:{external_id}"（步 A 多源扩展）
    pmid: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(32), default="pubmed")  # 数据源 key（步 A）
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 跨源去重键（步 A）
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    abstract_zh: Mapped[str] = mapped_column(Text, default="")  # LLM 中译（空串 = 未译）
    journal: Mapped[str] = mapped_column(String(256), default="")
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    pub_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # AD/PD/ALS/scale
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperCrawlRun(Base):
    """抓取轮次记录（论文域步 B）：每轮抓取结束写一行，成功/失败都写。

    stats JSONB 承载轮内统计（per_source 各源命中/新增数、users 覆盖用户数等），
    支撑论文页「已更新于 HH:MM」与 runs 追溯。
    """

    __tablename__ = "papers_crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trigger: Mapped[str] = mapped_column(String(16))  # schedule（定时）| manual（立即检索）
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16))  # success | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


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
