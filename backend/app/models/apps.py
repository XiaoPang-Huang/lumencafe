"""应用注册表模型（架构设计 §3.3，三表）。

app_visibility 目前只承载 hidden + 用户自定义分类（PRD §4.4 提到的
pinned/sort 覆盖与 DDL §3.3 不一致，以 DDL 为准，待文档对齐）。
"""
from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class AppRegistry(Base):
    __tablename__ = "app_registry"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # slug：chat / money / ...
    name: Mapped[str] = mapped_column(String(32))
    desc: Mapped[str] = mapped_column(String(128), default="")
    color: Mapped[str] = mapped_column(String(16), default="#FFE0CC")
    icon: Mapped[str] = mapped_column(String(64), default="")
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL")
    )
    sort: Mapped[int] = mapped_column(Integer, default=0)
    built_in: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(16), default="chat")  # chat/data/static/backend
    perm_code: Mapped[str] = mapped_column(String(64), default="app:chat")


class AppVisibility(Base):
    __tablename__ = "app_visibility"
    __table_args__ = (UniqueConstraint("user_id", "app_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    app_id: Mapped[str] = mapped_column(String(32), ForeignKey("app_registry.id", ondelete="CASCADE"))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[int | None] = mapped_column()  # 无 FK：分类删除时批量置 NULL
