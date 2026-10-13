"""AI 模型渠道管理（仅管理员）。

- llm_providers 表：厂家渠道 CRUD，api_key 返回一律脱敏（只留后 4 位）；
- POST /admin/llm/providers/{id}/test：最小请求测试连通性；
- llm_routing（space 设置）：chat / explain / translate 三个用途各绑定一个渠道。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..llm.providers import (
    FEATURES,
    ROUTING_SETTING_KEY,
    SPACE_USER,
    VENDOR_TEMPLATES,
    get_llm,
    test_provider,
)
from ..models import LLMProvider, UserSetting, WhitelistUser

logger = logging.getLogger("island.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(user: WhitelistUser = Depends(get_current_user)) -> WhitelistUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def mask_key(key: str) -> str:
    return "****" + key[-4:] if key else ""


def provider_to_dict(p: LLMProvider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "vendor": p.vendor,
        "base_url": p.base_url,
        "model": p.model,
        "enabled": p.enabled,
        "api_key_masked": mask_key(p.api_key),
        "has_key": bool(p.api_key),
    }


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=32)
    base_url: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=256)
    model: str = Field(default="", max_length=64)
    enabled: bool = True


class RoutingIn(BaseModel):
    chat: int | None = None
    explain: int | None = None
    translate: int | None = None


# ---------- 厂家渠道 CRUD ----------

@router.get("/llm/providers")
async def list_providers(
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(LLMProvider).order_by(LLMProvider.id.asc()))
    ).scalars().all()
    return {"providers": [provider_to_dict(p) for p in rows]}


@router.post("/llm/providers")
async def create_provider(
    body: ProviderIn,
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if body.vendor not in VENDOR_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"未知厂家：{body.vendor}")
    row = LLMProvider(
        name=body.name.strip(),
        vendor=body.vendor,
        base_url=body.base_url.strip(),
        api_key=body.api_key.strip(),
        model=body.model.strip(),
        enabled=body.enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return provider_to_dict(row)


@router.put("/llm/providers/{pid}")
async def update_provider(
    pid: int,
    body: ProviderIn,
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(LLMProvider).where(LLMProvider.id == pid))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    row.name = body.name.strip()
    row.vendor = body.vendor
    row.base_url = body.base_url.strip()
    row.model = body.model.strip()
    row.enabled = body.enabled
    # api_key 留空表示不修改（前端脱敏展示，无法回填原值）
    if body.api_key.strip():
        row.api_key = body.api_key.strip()
    await db.commit()
    return provider_to_dict(row)


@router.delete("/llm/providers/{pid}")
async def delete_provider(
    pid: int,
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(LLMProvider).where(LLMProvider.id == pid))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/llm/providers/{pid}/test")
async def test_connection(
    pid: int,
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(LLMProvider).where(LLMProvider.id == pid))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return await test_provider(row)


# ---------- 用途绑定 ----------

@router.get("/llm/routing")
async def read_routing(
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == SPACE_USER,
                UserSetting.scope == "space",
                UserSetting.key == ROUTING_SETTING_KEY,
            )
        )
    ).scalar_one_or_none()
    value = row.value if row and isinstance(row.value, dict) else {}
    return {"routing": {f: value.get(f) for f in FEATURES}}


@router.put("/llm/routing")
async def write_routing(
    body: RoutingIn,
    user: WhitelistUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    incoming = body.model_dump()
    for feature, pid in incoming.items():
        if pid is None:
            continue
        row = (
            await db.execute(select(LLMProvider).where(LLMProvider.id == pid))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=400, detail=f"渠道不存在：id={pid}")
        if not row.enabled:
            raise HTTPException(status_code=400, detail=f"渠道「{row.name}」已停用，不能绑定")
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == SPACE_USER,
                UserSetting.scope == "space",
                UserSetting.key == ROUTING_SETTING_KEY,
            )
        )
    ).scalar_one_or_none()
    merged = dict(row.value) if row and isinstance(row.value, dict) else {}
    for feature, pid in incoming.items():
        if pid is None:
            merged.pop(feature, None)
        else:
            merged[feature] = pid
    if row is None:
        db.add(UserSetting(
            user_id=SPACE_USER, scope="space", key=ROUTING_SETTING_KEY, value=merged,
        ))
    else:
        row.value = merged
    await db.commit()
    return {"routing": {f: merged.get(f) for f in FEATURES}}


@router.get("/llm/self-test")
async def self_test(
    user: WhitelistUser = Depends(require_admin),
):
    """验证 get_llm 当前实际会拿到哪个渠道（按用途探测，不发起网络请求）。"""
    result: dict[str, str] = {}
    for feature in FEATURES:
        try:
            llm = await get_llm(feature)
            result[feature] = f"{type(llm).__name__}({llm.model})"
        except Exception as exc:
            result[feature] = f"ERROR: {exc}"
    return {"resolved": result}
