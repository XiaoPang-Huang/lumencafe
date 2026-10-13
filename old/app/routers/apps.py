from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import AppRegistry, AppVisibility, Category, WhitelistUser
from ..schemas import AppConfigPut, CategoryCreate, CategoryRename

router = APIRouter(prefix="/apps", tags=["apps"])


@router.get("")
async def list_apps(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    apps = (await db.execute(select(AppRegistry).order_by(AppRegistry.sort))).scalars().all()
    cats = (await db.execute(select(Category).order_by(Category.sort))).scalars().all()
    vis = (
        await db.execute(select(AppVisibility).where(AppVisibility.user_id == user.openid))
    ).scalars().all()
    vis_map = {v.app_id: v for v in vis}
    cat_map = {c.id: c.name for c in cats}
    return {
        "apps": [
            {
                "id": a.id,
                "name": a.name,
                "desc": a.desc,
                "color": a.color,
                "icon": a.icon,
                "category_id": (
                    vis_map[a.id].category_id
                    if a.id in vis_map and vis_map[a.id].category_id is not None
                    else a.category_id
                ),
                "category_name": cat_map.get(
                    vis_map[a.id].category_id
                    if a.id in vis_map and vis_map[a.id].category_id is not None
                    else a.category_id,
                    "",
                ),
                "hidden": vis_map[a.id].hidden if a.id in vis_map else False,
            }
            for a in apps
        ],
        "categories": [{"id": c.id, "name": c.name} for c in cats],
    }


@router.post("/categories")
async def create_category(
    body: CategoryCreate,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    max_sort = (
        await db.execute(select(func.coalesce(func.max(Category.sort), 0)))
    ).scalar_one()
    cat = Category(name=body.name.strip(), sort=max_sort + 1)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return {"id": cat.id, "name": cat.name}


@router.put("/categories/{cat_id}")
async def rename_category(
    cat_id: int,
    body: CategoryRename,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cat = (
        await db.execute(select(Category).where(Category.id == cat_id))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    cat.name = body.name.strip()
    await db.commit()
    return {"id": cat.id, "name": cat.name}


@router.delete("/categories/{cat_id}")
async def delete_category(
    cat_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除分类；旗下应用（全局默认 + 用户覆盖）一律回落未分类（category_id=NULL）。"""
    cat = (
        await db.execute(select(Category).where(Category.id == cat_id))
    ).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    vis_moved = (
        await db.execute(
            AppVisibility.__table__.update()
            .where(AppVisibility.category_id == cat_id)
            .values(category_id=None)
        )
    ).rowcount
    reg_moved = (
        await db.execute(
            AppRegistry.__table__.update()
            .where(AppRegistry.category_id == cat_id)
            .values(category_id=None)
        )
    ).rowcount
    await db.delete(cat)
    await db.commit()
    return {"ok": True, "moved": (vis_moved or 0) + (reg_moved or 0)}


@router.put("/{app_id}/config")
async def update_config(
    app_id: str,
    body: AppConfigPut,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = (
        await db.execute(select(AppRegistry).where(AppRegistry.id == app_id))
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    row = (
        await db.execute(
            select(AppVisibility).where(
                AppVisibility.user_id == user.openid, AppVisibility.app_id == app_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = AppVisibility(user_id=user.openid, app_id=app_id)
        db.add(row)
    if body.hidden is not None:
        row.hidden = body.hidden
    if "category_id" in body.model_fields_set:
        # 显式传 null 表示回落未分类（清除用户覆盖）
        row.category_id = body.category_id
    await db.commit()
    return {"ok": True}
