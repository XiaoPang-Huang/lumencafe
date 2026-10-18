"""记账模型（架构设计 §3.6，两表，v1.1 新增）。

- 金额一律「分」（BIGINT 正整数），杜绝浮点误差；
- 幂等：UNIQUE(user_id, request_id)，冲突时应用层回查返回 idempotent: true；
- date 不晚于今天（可补记过去），统计按 date 归属月份；
- 分类 UNIQUE(user_id, built_in, name)：同用户同 built_in 档位名字唯一。
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MoneyCategory(Base):
    __tablename__ = "money_categories"
    __table_args__ = (
        CheckConstraint("kind IN ('expense','income','both')", name="ck_money_cat_kind"),
        UniqueConstraint("user_id", "built_in", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    built_in: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(8), default="both")  # expense / income / both
    icon: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MoneyTransaction(Base):
    __tablename__ = "money_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_money_txn_amount"),
        CheckConstraint("type IN ('expense','income')", name="ck_money_txn_type"),
        UniqueConstraint("user_id", "request_id"),
        Index("ix_txn_user_date", "user_id", "date"),
        Index("ix_txn_user_cat", "user_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(BigInteger)  # 单位：分
    type: Mapped[str] = mapped_column(String(8))  # expense / income
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("money_categories.id", ondelete="RESTRICT")
    )
    note: Mapped[str] = mapped_column(String(256), default="")
    date: Mapped[date] = mapped_column(Date)  # CHECK (date <= CURRENT_DATE) 由应用层校验，PG 不支持非常量默认值约束
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
