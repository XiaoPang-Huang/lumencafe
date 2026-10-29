"""文献模型（批次 2，架构设计 §3.8/PRD §4.8；轮①起六表 + runs 进度列）。

- papers：题录表（轮① 起行级归属 user_id，去重键 (user_id, pmid)）；
  tags/keywords 为 JSONB（`@>` 查询）；
- paper_users：归属表（哪篇推送给哪个用户，可见性隔离依据）；
- paper_library：我的文献工作台（轮① P22，阅读/批注/翻译唯一入口）；
- paper_favorites / paper_notes：收藏（幂等 toggle）与笔记（全文笔记 upsert +
  P8 批注双形态）；
- paper_explanations：AI 解读全局缓存（一篇一条，成功才入库，全局共享）。
"""
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 去重键（轮①起加 user 维度，唯一索引 uq_papers_user_pmid）：
    # PubMed 为纯数字 pmid；其余源为 "{source}:{external_id}"（步 A 多源扩展）。
    # 同一篇两人抓各存一份（拍板 P23：多几 MB 换语义干净 + 删除互不影响）
    pmid: Mapped[str] = mapped_column(String(64))
    # 行级归属（轮①，Alembic 0011）：抓取按人入库；存量行回填 = 最早 paper_users
    # 归属人，无归属归 admin；用户删除行级联带走其文献
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE")
    )
    # 来源：crawl（订阅/语义检索抓取）| import（轮② PDF/arXiv/DOI 导入）
    origin: Mapped[str] = mapped_column(String(16), default="crawl")
    source: Mapped[str] = mapped_column(String(32), default="pubmed")  # 数据源 key（步 A）
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 跨源去重键（步 A）
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    abstract_zh: Mapped[str] = mapped_column(Text, default="")  # LLM 中译（空串 = 未译）
    journal: Mapped[str] = mapped_column(String(256), default="")
    authors: Mapped[list[str]] = mapped_column(JSONB, default=list)
    pub_date: Mapped[date | None] = mapped_column(Date)  # 发表日期（= 展示设置口径的 published_date）
    # ── 论文域元数据增强（P15，Alembic 0008）──
    cited_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 被引次数
    # 影响因子近似（OpenAlex：优先 2yr_mean_citedness，该字段下线后回落 fwci；
    # 非 JCR 官方值，界面标注「≈」）
    if_approx: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    # ── 收藏并解析全链路（P16/P20，Alembic 0009）──
    url: Mapped[str] = mapped_column(Text, default="")  # 源落地页/OA 直链（PaperItem.url）
    parse_status: Mapped[str] = mapped_column(
        String(16), default="none"
    )  # none|pending|running|done|failed
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因（可空）
    parsed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # 解析完成时间（可空）
    # 轮②（Alembic 0012，P26）：解析五段阶段条数据源 download|upload|queue|parsing
    # （完成清空、失败保留在出错阶段；存量行/未启动为 NULL）
    parse_phase: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # AD/PD/ALS/scale
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 轮①（Alembic 0011）：去重键 = (user_id, pmid)，同用户内唯一
        Index("uq_papers_user_pmid", "user_id", "pmid", unique=True),
    )


class PaperCrawlRun(Base):
    """抓取轮次记录（论文域步 B）：每轮抓取结束写一行，成功/失败都写。

    run_at 锚定轮次发起时刻（而非结束时刻）：该轮入库的 papers.created_at
    均 ≥ run_at，digest「自最近一轮成功检索以来」窗口以它为界（发起时刻由
    _execute_round 捕获显式写入；直接插入无显式值时回落数据库 now()）。
    stats JSONB 承载轮内统计（per_source 各源命中/新增数、users 覆盖用户数等），
    支撑论文页「已更新于 HH:MM」与 runs 追溯。
    """

    __tablename__ = "papers_crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trigger: Mapped[str] = mapped_column(String(16))  # schedule（定时）| manual（立即检索）
    # MutableDict：轮内原地改 stats/progress 也能被会话感知提交（轮② P26 进度条）
    stats: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    status: Mapped[str] = mapped_column(String(16))  # success | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 轮①（Alembic 0011）：轮内实时进度（轮②检索进度条数据源；JSONB 可空）
    # 形如 {"phase": "fetching|translating|done", "keyword": 当前关键词,
    #       "per_source": {源: {"fetched": n, "added": n}}}
    progress: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSONB), nullable=True
    )


class PaperUser(Base):
    """归属表：文献推送给哪些用户（PRD 4.8 归属隔离）。"""

    __tablename__ = "paper_users"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperLibrary(Base):
    """我的文献工作台（轮①，P22/P24；Alembic 0011）。

    阅读/批注/翻译的唯一入口载体（拍板 P22）；删除 = 级联本人 papers 行 +
    本人批注 + COS 产物 + 收藏/归属/库关联（拍板 P24，删除逻辑见
    services/paper_library.py）。added_via 记加入途径：crawl（抓取/收藏并
    解析）| import（轮②导入）。
    """

    __tablename__ = "paper_library"
    __table_args__ = (
        UniqueConstraint("user_id", "paper_id", name="uq_paper_library_user_paper"),
        Index("ix_paper_library_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    added_via: Mapped[str] = mapped_column(String(16), default="crawl")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperFavorite(Base):
    __tablename__ = "paper_favorites"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperNote(Base):
    """论文笔记行：全文笔记（note_kind='note'）与批注（note_kind='annotation'）共存同表。

    P8 批注式笔记：批注每篇可多条，锚定解析段落（anchor_block_id =
    content_list 派生的 `p{页}_b{页内序}`，规则见 services/paper_content.py），
    anchor_quote 存被选中原文（hypothes.is 式精确引用）。links = 出链批注
    id 数组（知识网边，单向存储；反向链接由查询派生，不双写）。

    唯一性：全文笔记仍每篇至多一条（部分唯一索引 uq_paper_notes_legacy_note，
    Alembic 0010，upsert 语义不变）；批注无篇级唯一约束。
    """

    __tablename__ = "paper_notes"
    __table_args__ = (
        Index("ix_paper_notes_paper_user", "paper_id", "user_id"),
        # 部分唯一索引：全文笔记每篇至多一条（旧 upsert 语义）；批注（annotation）不受限
        Index(
            "uq_paper_notes_legacy_note",
            "paper_id",
            "user_id",
            unique=True,
            postgresql_where=text("note_kind = 'note'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, default="")  # 笔记正文 / 批注 body（划线可空串）
    # ── P8 批注锚点（Alembic 0010；全文笔记行三列均为默认值）──
    anchor_quote: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    anchor_block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note_kind: Mapped[str] = mapped_column(String(16), default="note")  # annotation|note
    links: Mapped[list[int]] = mapped_column(JSONB, default=list)  # 出链批注 id（去重保序）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
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
