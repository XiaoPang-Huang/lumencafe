from fastapi import Depends, Header, HTTPException
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import WhitelistUser
from .security import decode_token


async def get_current_user(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> WhitelistUser:
    """校验 JWT 并确认 openid 仍在白名单内。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        openid = decode_token(authorization.removeprefix("Bearer "))
    except PyJWTError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新进入")
    user = (
        await db.execute(select(WhitelistUser).where(WhitelistUser.openid == openid))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="不在白名单中")
    return user
