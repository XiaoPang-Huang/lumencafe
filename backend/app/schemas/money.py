"""请求/响应模型：记账（PRD §4.7）。

金额一律「分」正整数（N7）；日期 YYYY-MM-DD 不晚于今天；request_id 为客户端幂等键。
"""
import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["expense", "income", "both"]
TxnType = Literal["expense", "income"]


# ── 分类 ────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    kind: Kind = "both"
    icon: str = Field(default="", max_length=64)
    sort: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    kind: Kind | None = None
    icon: str | None = Field(default=None, max_length=64)
    sort: int | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    kind: str
    icon: str
    sort: int
    built_in: bool


# ── 账目 ────────────────────────────────────────────────
class TransactionCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    amount: int = Field(gt=0)  # 单位：分
    type: TxnType
    category_id: int
    note: str = Field(default="", max_length=256)
    date: dt.date


class TransactionUpdate(BaseModel):
    amount: int | None = Field(default=None, gt=0)
    type: TxnType | None = None
    category_id: int | None = None
    note: str | None = Field(default=None, max_length=256)
    date: dt.date | None = None


class TransactionOut(BaseModel):
    id: int
    request_id: str
    amount: int
    type: str
    category_id: int
    note: str
    date: dt.date
    created_at: dt.datetime
    updated_at: dt.datetime
    idempotent: bool = False  # 幂等重放时 true（首次创建 false）


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


# ── AI 记一笔 ───────────────────────────────────────────
class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ParseResponse(BaseModel):
    amount: int
    type: TxnType
    category_suggestion: str
    note: str = ""
    date: dt.date
    confidence: float | None = None


# ── 统计 ────────────────────────────────────────────────
class CategoryStat(BaseModel):
    category_id: int
    name: str
    total: int
    count: int


class MonthlyStats(BaseModel):
    month: str  # YYYY-MM
    expense_total: int
    income_total: int
    balance: int  # 收入 - 支出
    by_category: list[CategoryStat]


class MonthPoint(BaseModel):
    month: str
    expense_total: int
    income_total: int


class TrendStats(BaseModel):
    months: list[MonthPoint]


class SummaryStats(BaseModel):
    """每日看板聚合（PRD v1.1-rev7）：昨日支出 / 本周支出 / 本月收支。

    金额单位「分」对齐既有统计接口；日期边界按服务器本地时区，周 = 周一起。
    """

    yesterday_expense: int
    week_expense: int
    month_income: int
    month_expense: int
