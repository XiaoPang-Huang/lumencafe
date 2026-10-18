"""FastAPI 依赖注入：当前用户、权限点校验、内部令牌守卫（架构设计 §6.2）。

- get_current_user：Bearer JWT → 查库确认存在且未停用/未删除（PRD Q6 软删）；
- require_permission(code)：权限点校验依赖工厂；
- internal_token_guard：/internal/jobs/* 与 /gw/* 用，不走用户 JWT。
"""
import hmac

from fastapi import Depends, Header, HTTPException
from jwt import PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.user import User
from app.security import decode_token
from app.services import rbac_service


async def get_current_user(
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> User:
    """校验 JWT 并确认用户可用（is_active 且未软删）。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    try:
        user_id = decode_token(authorization.removeprefix("Bearer "))
    except (PyJWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None or user.is_deleted:
        raise HTTPException(status_code=401, detail="账号不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return user


def require_permission(code: str):
    """权限点校验依赖工厂：Depends(require_permission("admin:models"))"""

    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        perms = await rbac_service.permission_codes(db, user.id)
        if code not in perms:
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return checker


async def internal_token_guard(
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> None:
    """内部任务/网关守卫：比对 LUMEN_INTERNAL_TOKEN（留空 = 接口关闭 503）。"""
    token = settings.internal_token
    if not token:
        raise HTTPException(status_code=503, detail="内部接口未启用")
    if not x_internal_token or not hmac.compare_digest(x_internal_token, token):
        raise HTTPException(status_code=401, detail="内部令牌无效")
