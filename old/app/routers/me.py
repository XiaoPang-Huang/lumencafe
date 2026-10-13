from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import UserSetting, WhitelistUser
from ..schemas import SettingsPut

router = APIRouter(tags=["me"])


@router.get("/me")
async def read_me(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user.openid, UserSetting.scope == "user"
            )
        )
    ).scalars().all()
    return {
        "openid": user.openid,
        "nickname": user.nickname,
        "role": user.role,
        "settings": {r.key: r.value for r in rows},
    }


@router.put("/me/settings")
async def put_settings(
    body: SettingsPut,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user.openid,
                UserSetting.scope == "user",
                UserSetting.key == body.key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(UserSetting(user_id=user.openid, scope="user", key=body.key, value=body.value))
    else:
        row.value = body.value
    await db.commit()
    return {"ok": True}
