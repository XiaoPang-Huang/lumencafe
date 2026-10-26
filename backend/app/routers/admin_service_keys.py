"""平台管理-服务 Key 管理（架构设计-增量 v2.9，权限点复用 admin:models）。

- 表 service_keys 只托管异构服务（MinerU/FunASR/DashScope 等）钥匙，不走模型网关代理；
- 路由挂 /admin/service-keys，权限复用现有 admin:models（require_permission，零新增权限点）；
- api_key 一律掩码回显（前 4 + **** + 后 4）：只有 POST/PUT 写入时接收完整 key，
  任何接口不回显完整 key；
- service_key（服务标识）格式校验：小写字母数字下划线（新增/编辑均校验，编辑仅防御性——
  Update schema 未开放 service_key 字段）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.service_key import ServiceKey
from app.models.user import User
from app.schemas.service_key import ServiceKeyCreate, ServiceKeyOut, ServiceKeyUpdate

router = APIRouter(prefix="/admin/service-keys", tags=["admin-service-keys"])


async def _admin_models(user: User = Depends(require_permission("admin:models"))) -> User:
    return user


def mask_api_key(key: str) -> str:
    """API Key 脱敏：前 4 位 + **** + 后 4 位；不足 8 位时整体掩码；无 key 返回空串。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _skey_out(row: ServiceKey) -> ServiceKeyOut:
    return ServiceKeyOut(
        id=row.id,
        service_key=row.service_key,
        vendor=row.vendor,
        api_key_masked=mask_api_key(row.api_key),
        base_url=row.base_url,
        note=row.note,
        enabled=row.enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_row(db: AsyncSession, row_id: int) -> ServiceKey:
    row = (
        await db.execute(select(ServiceKey).where(ServiceKey.id == row_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="服务 Key 不存在")
    return row


@router.get("", response_model=list[ServiceKeyOut])
async def list_service_keys(
    admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(select(ServiceKey).order_by(ServiceKey.id))
    ).scalars().all()
    return [_skey_out(r) for r in rows]


@router.post("", response_model=ServiceKeyOut, status_code=201)
async def create_service_key(
    body: ServiceKeyCreate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    row = ServiceKey(**body.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="service_key 已存在") from exc
    await db.refresh(row)
    return _skey_out(row)


@router.put("/{row_id}", response_model=ServiceKeyOut)
async def update_service_key(
    row_id: int,
    body: ServiceKeyUpdate,
    admin: User = Depends(_admin_models),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_row(db, row_id)
    data = body.model_dump(exclude_unset=True)
    if "api_key" in data:
        if not data["api_key"]:
            del data["api_key"]  # 留空 = 不修改
        elif not data["api_key"].strip():
            del data["api_key"]
    for key, value in data.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return _skey_out(row)


@router.delete("/{row_id}")
async def delete_service_key(
    row_id: int, admin: User = Depends(_admin_models), db: AsyncSession = Depends(get_db)
):
    row = await _get_row(db, row_id)
    await db.delete(row)
    await db.commit()
    return {"ok": True}
