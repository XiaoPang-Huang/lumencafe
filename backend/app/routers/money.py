"""记账接口（PRD §4.7，权限点 app:money；业务逻辑在 services/money_service.py）。

- 账目按 user_id 隔离；分类同 kind 重名 409；预置分类可改名不可改 kind/不可删；
- 入账幂等：request_id 冲突回查原记录 200 + idempotent:true；
- 统计按 date 归属月；parse（AI 记一笔）仅生成草稿不落库，限流 10 次/分钟/用户（N14）。
"""
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.money import MoneyCategory
from app.models.user import User
from app.schemas.money import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    MonthlyStats,
    ParseRequest,
    ParseResponse,
    SummaryStats,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TrendStats,
)
from app.services import money_service, rate_limit

router = APIRouter(prefix="/money", tags=["money"])


async def _bookkeeper(user: User = Depends(require_permission("app:money"))) -> User:
    return user


def _category_out(c: MoneyCategory) -> CategoryOut:
    return CategoryOut(
        id=c.id, name=c.name, kind=c.kind, icon=c.icon, sort=c.sort, built_in=c.built_in
    )


# ── 分类 ────────────────────────────────────────────────
@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    user: User = Depends(_bookkeeper), db: AsyncSession = Depends(get_db)
):
    rows = await money_service.list_categories(db, user.id)
    return [_category_out(c) for c in rows]


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreate,
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    category = await money_service.create_category(db, user.id, body)
    return _category_out(category)


@router.put("/categories/{cid}", response_model=CategoryOut)
async def update_category(
    cid: int,
    body: CategoryUpdate,
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    category = await money_service.update_category(db, user.id, cid, body)
    return _category_out(category)


@router.delete("/categories/{cid}")
async def delete_category(
    cid: int, user: User = Depends(_bookkeeper), db: AsyncSession = Depends(get_db)
):
    txn_count = await money_service.delete_category(db, user.id, cid)
    if txn_count > 0:
        raise HTTPException(
            status_code=409, detail=f"该分类下还有 {txn_count} 笔账目，请先迁移或删除"
        )
    return {"ok": True}


# ── 账目 ────────────────────────────────────────────────
@router.get("/transactions", response_model=TransactionPage)
async def list_transactions(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    category_id: int | None = None,
    type: str | None = Query(default=None, pattern="^(expense|income)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(UTC).date()
    if date_from is None and date_to is None:
        date_from = today.replace(day=1)  # 默认本月（PRD：必填其一，默认本月）
    items, total = await money_service.list_transactions(
        db,
        user.id,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        txn_type=type,
        page=page,
        page_size=page_size,
    )
    return TransactionPage(
        items=[money_service.transaction_out(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/transactions", response_model=TransactionOut, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    response: Response,
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    result = await money_service.create_transaction(db, user.id, body)
    if result.idempotent:
        response.status_code = 200  # 幂等重放返回 200（首次创建 201）
    return result


@router.get("/transactions/{tid}", response_model=TransactionOut)
async def get_transaction(
    tid: int, user: User = Depends(_bookkeeper), db: AsyncSession = Depends(get_db)
):
    txn = await money_service.get_transaction(db, user.id, tid)
    return money_service.transaction_out(txn)


@router.put("/transactions/{tid}", response_model=TransactionOut)
async def update_transaction(
    tid: int,
    body: TransactionUpdate,
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    return await money_service.update_transaction(db, user.id, tid, body)


@router.delete("/transactions/{tid}")
async def delete_transaction(
    tid: int, user: User = Depends(_bookkeeper), db: AsyncSession = Depends(get_db)
):
    await money_service.delete_transaction(db, user.id, tid)
    return {"ok": True}


# ── 统计 ────────────────────────────────────────────────
@router.get("/stats/monthly", response_model=MonthlyStats)
async def monthly_stats(
    month: str = Query(pattern="^\\d{4}-\\d{2}$"),
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    return await money_service.monthly_stats(db, user.id, month)


@router.get("/stats/trend", response_model=TrendStats)
async def trend_stats(
    months: int = Query(default=6, ge=1, le=12),
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    return await money_service.trend_stats(db, user.id, months)


@router.get("/stats/summary", response_model=SummaryStats)
async def summary_stats(
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    """每日看板聚合（PRD v1.1-rev7）：昨日支出 / 本周支出 / 本月收支（分）。"""
    return await money_service.summary_stats(db, user.id)


# ── AI 记一笔 ───────────────────────────────────────────
@router.post("/parse", response_model=ParseResponse)
async def parse_transaction(
    body: ParseRequest,
    user: User = Depends(_bookkeeper),
    db: AsyncSession = Depends(get_db),
):
    if not rate_limit.hit(f"money-parse:{user.id}", limit=10):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    return await money_service.parse_text(db, body.text)
