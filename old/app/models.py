"""数据模型。

按开发指令：每个应用独立 schema/库。脚手架阶段先放在一个库内用表前缀区分，
后续随应用逐个拆分为独立 schema（papers_db / focus_db / mood_db / chat_db / settings_db）。
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class WhitelistUser(Base):
    """微信 openid 白名单。只有两人，均为管理员。"""

    __tablename__ = "whitelist_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(32), default="岛民")
    role: Mapped[str] = mapped_column(String(16), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserSetting(Base):
    """设置键值表。

    scope=user：个人设置，按 openid 隔离，互不可见。
    scope=space：空间设置，两人共用（user_id 固定存 "space"）。
    """

    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id", "scope", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(8), default="user")
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Category(Base):
    """应用分类。空间级共享，两人看到同样的分类。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class AppRegistry(Base):
    """应用注册表：新增应用只需加一条记录，前端应用面板数据驱动。"""

    __tablename__ = "app_registry"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # slug: chat / breath / ...
    name: Mapped[str] = mapped_column(String(32))
    desc: Mapped[str] = mapped_column(String(128), default="")
    color: Mapped[str] = mapped_column(String(16), default="#FFE0CC")
    icon: Mapped[str] = mapped_column(String(64), default="")
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    built_in: Mapped[bool] = mapped_column(Boolean, default=True)


class AppVisibility(Base):
    """按用户覆盖应用的隐藏状态与自定义分类。"""

    __tablename__ = "app_visibility"
    __table_args__ = (UniqueConstraint("user_id", "app_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    app_id: Mapped[str] = mapped_column(String(32))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ========== 专注打卡 / 每日小事（将来拆入 focus_db） ==========

class FocusCheckin(Base):
    """「放下小说挑战」每日打卡。每人每天一条，重复打卡返回已打卡状态。"""

    __tablename__ = "focus_checkins"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailyTaskDone(Base):
    """每日一件小事的完成状态。每人每天一条。"""

    __tablename__ = "focus_task_done"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[datetime.date] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class FocusTodo(Base):
    """用户自建待办事项：新增、打勾完成、删除。仅本人可见。"""

    __tablename__ = "focus_todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(128))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ========== 心情记录（将来拆入 mood_db，仅本人可见） ==========

class MoodRecord(Base):
    """每日心情（good / ok / anxious）。每人每天一条，重复记录覆盖。"""

    __tablename__ = "mood_records"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    date: Mapped[date] = mapped_column(Date)
    mood: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# ========== 文献推送（将来拆入 papers_db） ==========

class Paper(Base):
    """PubMed 文献。pmid 全局唯一；tags 为规则打标结果（AD/PD/ALS/scale）。

    JSON 列在 PostgreSQL 下使用 JSONB 变体，以支持 @> 包含查询（标签筛选）。
    """

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True)
    pmid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(1024), default="")
    abstract: Mapped[str] = mapped_column(String, default="")  # Text
    abstract_zh: Mapped[str | None] = mapped_column(String, nullable=True)  # Text，LLM 中译文
    journal: Mapped[str] = mapped_column(String(256), default="")
    authors: Mapped[list] = mapped_column(JSON, default=list)  # ["LastName FM", ...]
    pub_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tags: Mapped[list] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    keywords: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=list
    )  # 打标时实际命中的关键词
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ========== LLM 厂家渠道（管理页可配，运行时热生效；env 仅作首次种子与兜底） ==========

class LLMProvider(Base):
    """一个可管理的 AI 厂家渠道：OpenAI 兼容接口（deepseek/kimi/自定义）或 mock。"""

    __tablename__ = "llm_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))  # 展示名，如「DeepSeek 主号」
    vendor: Mapped[str] = mapped_column(String(32))  # deepseek / kimi / openai / mock
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key: Mapped[str] = mapped_column(String(256), default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperFavorite(Base):
    """文献收藏。每人每篇一条，重复切换靠应用层幂等处理。"""

    __tablename__ = "paper_favorites"
    __table_args__ = (UniqueConstraint("user_id", "paper_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperUser(Base):
    """文献 × 用户归属：该篇是由哪个用户的订阅关键词抓到的（一篇可归属多人）。

    文献流按人隔离的依据；crawler 入库时写入。
    """

    __tablename__ = "paper_users"
    __table_args__ = (UniqueConstraint("paper_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperNote(Base):
    """文献笔记（仅本人可见）。每人每篇一条，重复保存覆盖。"""

    __tablename__ = "paper_notes"
    __table_args__ = (UniqueConstraint("user_id", "paper_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    content: Mapped[str] = mapped_column(String, default="")  # Text
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PaperExplanation(Base):
    """文献 AI 解读。按 paper_id 全局共享缓存（两人看到同一份解读）。"""

    __tablename__ = "paper_explanations"

    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), unique=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(String, default="")  # Text
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ========== 空间设置载体 ==========
# 空间设置存 user_settings 表：scope="space", user_id="space"（两人共享）
# 以下两张为空间运行所需的辅助表。

class SpaceInvite(Base):
    """邀请码。24 小时有效，一人一码，兑换后把对方 openid 加进白名单。"""

    __tablename__ = "space_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DangerRequest(Base):
    """危险操作双人确认：一人发起、另一人确认后才执行。两人均为管理员。"""

    __tablename__ = "danger_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(32))  # clear_chat / clear_focus / clear_mood / clear_papers
    requested_by: Mapped[str] = mapped_column(String(64))
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / done / rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ========== 小岛树洞对话历史（将来拆入 chat_db，仅本人可见，支持一键清空） ==========

class ChatConversation(Base):
    """一段对话（会话）。每用户多会话，消息挂在会话下；首条消息自动生成标题。"""

    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(64), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ChatMessage(Base):
    """对话消息。按用户 + 会话隔离；清空=删除该会话内全部消息。"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_conversations.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(String, default="")  # Text
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
