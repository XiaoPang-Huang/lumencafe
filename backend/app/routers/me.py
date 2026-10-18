"""个人页与用户设置（PRD §4.5）：本人信息 + 设置键值 upsert。

已知 key：subscribe_keywords（文献订阅关键词，批次 2 启用）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.models.user_settings import UserSetting
from app.schemas.me import MeResponse, SettingUpsert

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
async def read_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings_rows = (
        await db.execute(
            select(UserSetting).where(UserSetting.user_id == user.id, UserSetting.scope == "user")
        )
    ).scalars().all()
    return MeResponse(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        roles=sorted(r.name for r in user.roles),
        settings={s.key: s.value for s in settings_rows},
    )


@router.put("/me/settings")
async def upsert_setting(
    body: SettingUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        pg_insert(UserSetting)
        .values(user_id=user.id, scope="user", key=body.key, value=body.value)
        .on_conflict_do_update(
            index_elements=["user_id", "scope", "key"],
            set_={"value": body.value, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "key": body.key, "value": body.value}
