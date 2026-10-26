"""记账业务逻辑（PRD §4.7，架构设计 §4.7/§5.3）。

- 幂等入账：INSERT … ON CONFLICT (user_id, request_id) DO NOTHING，
  冲突回查原记录 200 + idempotent:true（§5.3）；
- 分类名查重按 PRD「同 kind 重名 409」（DB UNIQUE(user_id, built_in, name) 兜底同档位）；
- 校验：金额>0、date 不晚于今天、分类属本人、type×kind 兼容；
- 统计口径：按 date 字段归属月份（不按 created_at）。
"""
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.money import MoneyCategory, MoneyTransaction
from app.schemas.money import (
    CategoryCreate,
    CategoryStat,
    CategoryUpdate,
    MonthlyStats,
    MonthPoint,
    ParseResponse,
    SummaryStats,
    TransactionCreate,
    TransactionOut,
    TransactionUpdate,
    TrendStats,
)
from app.services import llm_gateway, model_caller

_TXN_KIND_COMPAT = {
    "expense": ("expense", "both"),
    "income": ("income", "both"),
}


def transaction_out(txn: MoneyTransaction, *, idempotent: bool = False) -> TransactionOut:
    return TransactionOut(
        id=txn.id,
        request_id=txn.request_id,
        amount=txn.amount,
        type=txn.type,
        category_id=txn.category_id,
        note=txn.note,
        date=txn.date,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
        idempotent=idempotent,
    )


def _today() -> date:
    """业务默认日期（记账归属日、AI 记一笔草稿日期）——用服务器本地时区。

    历史实现误用 UTC：每天本地 00:00-08:00 窗口会把「今天」记成昨天
    （2026-10-27 凌晨实测踩中，test_parse_mock_route 等 7 例暴露）。
    """
    return datetime.now().date()


def _today_local() -> date:
    """服务器本地时区的今天（每日看板日期边界口径，PRD v1.1-rev7）。

    与 _today() 同口径，保留别名以兼容既有调用点。
    """
    return _today()


async def _get_category(
    db: AsyncSession, user_id: int, cid: int
) -> MoneyCategory | None:
    return (
        await db.execute(
            select(MoneyCategory).where(
                MoneyCategory.id == cid, MoneyCategory.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def _get_transaction(
    db: AsyncSession, user_id: int, tid: int
) -> MoneyTransaction | None:
    return (
        await db.execute(
            select(MoneyTransaction).where(
                MoneyTransaction.id == tid, MoneyTransaction.user_id == user_id
            )
        )
    ).scalar_one_or_none()


def _validate_combo(category: MoneyCategory, txn_type: str) -> str | None:
    """type×kind 兼容校验；返回错误文案或 None。"""
    if txn_type not in _TXN_KIND_COMPAT:
        return "type 须为 expense / income"
    if category.kind not in _TXN_KIND_COMPAT[txn_type]:
        return f"该分类（{category.kind}）不能记 {txn_type} 账目"
    return None


# ── 分类 ────────────────────────────────────────────────
async def list_categories(db: AsyncSession, user_id: int) -> list[MoneyCategory]:
    result = await db.execute(
        select(MoneyCategory)
        .where(MoneyCategory.user_id == user_id)
        .order_by(MoneyCategory.sort, MoneyCategory.id)
    )
    return list(result.scalars().all())


async def create_category(
    db: AsyncSession, user_id: int, body: CategoryCreate
) -> MoneyCategory:
    dup = (
        await db.execute(
            select(MoneyCategory.id).where(
                MoneyCategory.user_id == user_id,
                MoneyCategory.name == body.name,
                MoneyCategory.kind == body.kind,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="已存在同名同类型的分类")
    category = MoneyCategory(user_id=user_id, built_in=False, **body.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, user_id: int, cid: int, body: CategoryUpdate
) -> MoneyCategory:
    category = await _get_category(db, user_id, cid)
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    if category.built_in and body.kind is not None and body.kind != category.kind:
        raise HTTPException(status_code=400, detail="预置分类不可修改类型")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != category.name:
        dup = (
            await db.execute(
                select(MoneyCategory.id).where(
                    MoneyCategory.user_id == user_id,
                    MoneyCategory.name == data["name"],
                    MoneyCategory.kind == (data.get("kind") or category.kind),
                    MoneyCategory.id != cid,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status_code=409, detail="已存在同名同类型的分类")
    for key, value in data.items():
        setattr(category, key, value)
    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, user_id: int, cid: int) -> int:
    """删除自定义分类；返回名下账目数（>0 时调用方转 409）。"""
    category = await _get_category(db, user_id, cid)
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    if category.built_in:
        raise HTTPException(status_code=403, detail="预置分类不可删除")
    count = (
        await db.execute(
            select(func.count(MoneyTransaction.id)).where(
                MoneyTransaction.category_id == cid
            )
        )
    ).scalar_one()
    if count > 0:
        return count  # 应用层先查后删（PRD 4.7），由路由转 409
    await db.delete(category)
    await db.commit()
    return 0


# ── 账目 ────────────────────────────────────────────────
async def create_transaction(
    db: AsyncSession, user_id: int, body: TransactionCreate
) -> TransactionOut:
    if body.date > _today():
        raise HTTPException(status_code=400, detail="日期不能晚于今天")
    category = await _get_category(db, user_id, body.category_id)
    if category is None:
        raise HTTPException(status_code=400, detail="分类不存在")
    if err := _validate_combo(category, body.type):
        raise HTTPException(status_code=400, detail=err)

    stmt = (
        pg_insert(MoneyTransaction)
        .values(user_id=user_id, **body.model_dump())
        .on_conflict_do_nothing(index_elements=["user_id", "request_id"])
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 0:
        # 幂等重放：回查原记录返回（PRD 4.7）
        original = (
            await db.execute(
                select(MoneyTransaction).where(
                    MoneyTransaction.user_id == user_id,
                    MoneyTransaction.request_id == body.request_id,
                )
            )
        ).scalar_one()
        return transaction_out(original, idempotent=True)
    created = (
        await db.execute(
            select(MoneyTransaction).where(
                MoneyTransaction.user_id == user_id,
                MoneyTransaction.request_id == body.request_id,
            )
        )
    ).scalar_one()
    return transaction_out(created)


async def list_transactions(
    db: AsyncSession,
    user_id: int,
    *,
    date_from: date | None,
    date_to: date | None,
    category_id: int | None,
    txn_type: str | None,
    page: int,
    page_size: int,
) -> tuple[list[MoneyTransaction], int]:
    conditions = [MoneyTransaction.user_id == user_id]
    if date_from is not None:
        conditions.append(MoneyTransaction.date >= date_from)
    if date_to is not None:
        conditions.append(MoneyTransaction.date <= date_to)
    if category_id is not None:
        conditions.append(MoneyTransaction.category_id == category_id)
    if txn_type is not None:
        conditions.append(MoneyTransaction.type == txn_type)

    total = (
        await db.execute(
            select(func.count(MoneyTransaction.id)).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(MoneyTransaction)
            .where(*conditions)
            .order_by(MoneyTransaction.date.desc(), MoneyTransaction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


async def get_transaction(
    db: AsyncSession, user_id: int, tid: int
) -> MoneyTransaction:
    txn = await _get_transaction(db, user_id, tid)
    if txn is None:
        raise HTTPException(status_code=404, detail="账目不存在")
    return txn


async def update_transaction(
    db: AsyncSession, user_id: int, tid: int, body: TransactionUpdate
) -> TransactionOut:
    txn = await _get_transaction(db, user_id, tid)
    if txn is None:
        raise HTTPException(status_code=404, detail="账目不存在")
    data = body.model_dump(exclude_unset=True)

    new_type = data.get("type", txn.type)
    new_category_id = data.get("category_id", txn.category_id)
    new_date = data.get("date", txn.date)
    if new_date > _today():
        raise HTTPException(status_code=400, detail="日期不能晚于今天")
    category = await _get_category(db, user_id, new_category_id)
    if category is None:
        raise HTTPException(status_code=400, detail="分类不存在")
    if err := _validate_combo(category, new_type):
        raise HTTPException(status_code=400, detail=err)

    for key, value in data.items():
        setattr(txn, key, value)
    await db.commit()
    await db.refresh(txn)
    return transaction_out(txn)


async def delete_transaction(db: AsyncSession, user_id: int, tid: int) -> None:
    txn = await _get_transaction(db, user_id, tid)
    if txn is None:
        raise HTTPException(status_code=404, detail="账目不存在")
    await db.delete(txn)
    await db.commit()


# ── 统计 ────────────────────────────────────────────────
async def monthly_stats(db: AsyncSession, user_id: int, month: str) -> MonthlyStats:
    year, mon = int(month[:4]), int(month[5:7])
    start = date(year, mon, 1)
    end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)

    sums = (
        await db.execute(
            select(MoneyTransaction.type, func.coalesce(func.sum(MoneyTransaction.amount), 0))
            .where(
                MoneyTransaction.user_id == user_id,
                MoneyTransaction.date >= start,
                MoneyTransaction.date < end,
            )
            .group_by(MoneyTransaction.type)
        )
    ).all()
    totals = {row[0]: int(row[1]) for row in sums}
    expense_total = totals.get("expense", 0)
    income_total = totals.get("income", 0)

    by_cat_rows = (
        await db.execute(
            select(
                MoneyCategory.id,
                MoneyCategory.name,
                func.coalesce(func.sum(MoneyTransaction.amount), 0),
                func.count(MoneyTransaction.id),
            )
            .join(MoneyTransaction, MoneyTransaction.category_id == MoneyCategory.id)
            .where(
                MoneyTransaction.user_id == user_id,
                MoneyTransaction.type == "expense",
                MoneyTransaction.date >= start,
                MoneyTransaction.date < end,
            )
            .group_by(MoneyCategory.id, MoneyCategory.name)
            .order_by(func.sum(MoneyTransaction.amount).desc())
        )
    ).all()
    return MonthlyStats(
        month=month,
        expense_total=expense_total,
        income_total=income_total,
        balance=income_total - expense_total,
        by_category=[
            CategoryStat(category_id=int(r[0]), name=r[1], total=int(r[2]), count=int(r[3]))
            for r in by_cat_rows
        ],
    )


async def trend_stats(db: AsyncSession, user_id: int, months: int) -> TrendStats:
    """最近 N 个月收支趋势；无数据月份补零。归属口径 = date 字段。"""
    today = _today()
    # 生成最近 N 个月的 YYYY-MM 标签（含当月）
    labels: list[str] = []
    year, mon = today.year, today.month
    for _ in range(months):
        labels.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            mon, year = 12, year - 1
    labels.reverse()

    first = date(int(labels[0][:4]), int(labels[0][5:7]), 1)
    # 直接从 date 列取 YYYY-MM 文本做分桶键——免疫时区：
    # date_trunc('month', date) 会返回会话时区的 timestamptz，经 SQLAlchemy
    # 以 naive UTC 归一后 +08 时区下月桶会整体回退一月（2026-10-27 被分进 2026-09，
    # 2026-10-27 凌晨实测踩中）；to_char 在 date 列上算，无此问题
    month_label = func.to_char(MoneyTransaction.date, "YYYY-MM").label("month_label")
    rows = (
        await db.execute(
            select(
                month_label,
                MoneyTransaction.type,
                func.coalesce(func.sum(MoneyTransaction.amount), 0),
            )
            .where(
                MoneyTransaction.user_id == user_id,
                MoneyTransaction.date >= first,
            )
            .group_by(month_label, MoneyTransaction.type)
        )
    ).all()
    data: dict[str, dict[str, int]] = {
        label: {"expense": 0, "income": 0} for label in labels
    }
    for label, txn_type, total in rows:
        if label in data:
            data[label][txn_type] = int(total)
    return TrendStats(
        months=[
            MonthPoint(month=label, expense_total=data[label]["expense"], income_total=data[label]["income"])
            for label in labels
        ]
    )


async def summary_stats(db: AsyncSession, user_id: int) -> SummaryStats:
    """每日看板聚合（PRD v1.1-rev7）：昨日支出 / 本周支出 / 本月收支。

    日期边界按服务器本地时区（_today_local）；周 = 周一为界（含今天）；
    归属口径与 monthly_stats 一致 = date 字段。单次聚合查询出四个值。
    """
    today = _today_local()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    month_end = (
        date(today.year + 1, 1, 1)
        if today.month == 12
        else date(today.year, today.month + 1, 1)
    )

    t = MoneyTransaction
    is_expense = t.type == "expense"
    is_income = t.type == "income"
    row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((and_(is_expense, t.date == yesterday), t.amount), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (and_(is_expense, t.date >= week_start, t.date <= today), t.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(is_income, t.date >= month_start, t.date < month_end),
                                t.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(is_expense, t.date >= month_start, t.date < month_end),
                                t.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(t.user_id == user_id)
        )
    ).one()
    return SummaryStats(
        yesterday_expense=int(row[0]),
        week_expense=int(row[1]),
        month_income=int(row[2]),
        month_expense=int(row[3]),
    )


# ── AI 记一笔 ───────────────────────────────────────────
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

PARSE_SYSTEM_PROMPT = (
    "你是记账助手。把用户的消费/收入描述解析为严格 JSON，只输出 JSON，不要输出任何其他文字。"
    "字段：amount（金额，单位「分」的正整数，如 12.5 元 → 1250）、"
    "type（expense 支出 / income 收入）、"
    "category_suggestion（最贴切的分类名，短词）、"
    "note（简短备注，可空字符串）、"
    "date（YYYY-MM-DD，默认今天，不晚于今天）、"
    "confidence（0~1 可选）。"
    "无法确定金额时返回 {\"error\": \"无法解析\"}。"
)


def extract_json(text: str) -> dict[str, Any]:
    """从模型回复中提取 JSON 对象（容忍 ```json 围栏与前后杂文本）。"""
    cleaned = _JSON_FENCE_RE.sub("", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型未返回 JSON")
    return json.loads(cleaned[start : end + 1])


async def parse_text(
    db: AsyncSession, text: str
) -> ParseResponse:
    """AI 记一笔：仅生成草稿不落库。模型未配置 503；解析/超时失败 502。

    步 3：走 app_key="money_parse" 路由编排（主模型 + 备用链兜底 + 熔断 + 记账）。
    """
    try:
        reply = await model_caller.chat_once(
            db,
            "money_parse",
            [
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            timeout=8.0,  # PRD N5
        )
    except model_caller.RouteUnavailable:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail="AI 解析失败，请手动记一笔") from exc

    try:
        data = extract_json(reply)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="AI 解析结果异常，请手动记一笔") from exc
    if data.get("error"):
        raise HTTPException(status_code=502, detail=str(data["error"]))

    try:
        amount = int(data["amount"])
        txn_type = str(data["type"])
        if amount <= 0 or txn_type not in ("expense", "income"):
            raise ValueError
        parsed_date = date.fromisoformat(str(data.get("date") or _today()))
        parsed_date = min(parsed_date, _today())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="AI 解析结果异常，请手动记一笔") from exc

    return ParseResponse(
        amount=amount,
        type=txn_type,  # type: ignore[arg-type]
        category_suggestion=str(data.get("category_suggestion") or "其他"),
        note=str(data.get("note") or "")[:256],
        date=parsed_date,
        confidence=(
            float(data["confidence"]) if isinstance(data.get("confidence"), int | float) else None
        ),
    )
