"""应用注册表接口（PRD §4.4，登录即可）。

- GET /apps：注册表 + 分类 + 当前用户 visibility 覆盖合并，驱动前端两层 IA；
- 分类删除时 app_registry.category_id 与 app_visibility.category_id 批量置 NULL；
- 覆盖 upsert：category_id 显式 null = 清除覆盖。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.apps import AppRegistry, AppVisibility, Category
from app.models.user import User
from app.schemas.apps import (
    AppOut,
    AppsResponse,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    VisibilityConfig,
)

router = APIRouter(prefix="/apps", tags=["apps"])


def _category_out(c: Category) -> CategoryOut:
    return CategoryOut(id=c.id, name=c.name, sort=c.sort)


# ── 应用列表 ────────────────────────────────────────────
@router.get("", response_model=AppsResponse)
async def list_apps(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    apps = (
        await db.execute(select(AppRegistry).order_by(AppRegistry.sort, AppRegistry.id))
    ).scalars().all()
    categories = (
        await db.execute(select(Category).order_by(Category.sort, Category.id))
    ).scalars().all()
    visibility = {
        v.app_id: v
        for v in (
            await db.execute(select(AppVisibility).where(AppVisibility.user_id == user.id))
        ).scalars().all()
    }
    merged = []
    for app in apps:
        cover = visibility.get(app.id)
        merged.append(
            AppOut(
                id=app.id,
                name=app.name,
                desc=app.desc,
                color=app.color,
                icon=app.icon,
                sort=app.sort,
                mode=app.mode,
                perm_code=app.perm_code,
                category_id=(cover.category_id if cover else None) or app.category_id,
                hidden=cover.hidden if cover else False,
            )
        )
    return AppsResponse(apps=merged, categories=[_category_out(c) for c in categories])


# ── 分类 CRUD ───────────────────────────────────────────
@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(Category.id).where(Category.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="分类已存在")
    category = Category(**body.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return _category_out(category)


@router.put("/categories/{cid}", response_model=CategoryOut)
async def update_category(
    cid: int,
    body: CategoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    category = (
        await db.execute(select(Category).where(Category.id == cid))
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    if body.name is not None and body.name != category.name:
        exists = (
            await db.execute(select(Category.id).where(Category.name == body.name))
        ).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(status_code=409, detail="分类已存在")
        category.name = body.name
    if body.sort is not None:
        category.sort = body.sort
    await db.commit()
    await db.refresh(category)
    return _category_out(category)


@router.delete("/categories/{cid}")
async def delete_category(
    cid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    category = (
        await db.execute(select(Category).where(Category.id == cid))
    ).scalar_one_or_none()
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    # 旗下应用回落未分类：注册表与用户覆盖批量置 NULL
    await db.execute(
        update(AppRegistry).where(AppRegistry.category_id == cid).values(category_id=None)
    )
    await db.execute(
        update(AppVisibility).where(AppVisibility.category_id == cid).values(category_id=None)
    )
    await db.delete(category)
    await db.commit()
    return {"ok": True}


# ── 用户级覆盖 ──────────────────────────────────────────
@router.put("/{app_id}/config")
async def update_config(
    app_id: str,
    body: VisibilityConfig,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(AppRegistry.id).where(AppRegistry.id == app_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="应用不存在")

    current = (
        await db.execute(
            select(AppVisibility).where(
                AppVisibility.user_id == user.id, AppVisibility.app_id == app_id
            )
        )
    ).scalar_one_or_none()
    hidden = body.hidden if body.hidden is not None else (current.hidden if current else False)
    # 显式 null 与未传 key 都落到 category_id=None（清除覆盖）
    category_id = body.category_id if body.category_id is not None else None

    stmt = (
        pg_insert(AppVisibility)
        .values(user_id=user.id, app_id=app_id, hidden=hidden, category_id=category_id)
        .on_conflict_do_update(
            index_elements=["user_id", "app_id"],
            set_={"hidden": hidden, "category_id": category_id},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "app_id": app_id, "hidden": hidden, "category_id": category_id}
