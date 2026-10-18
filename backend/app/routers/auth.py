"""认证接口（PRD §4.1）：注册 / 登录 / 本人 / 改密。

- 注册仅 LUMEN_REGISTRATION_OPEN=true 开放（默认关），新用户绑 member 角色并补记账内置分类；
- JWT 30 天，无 refresh；登录/注册按 N14 同 IP 限流（10 次/分钟）。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import Role, User, UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.security import create_token, hash_password, verify_password
from app.services import rate_limit, rbac_service
from app.services import seed as seed_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        roles=sorted(r.name for r in user.roles),
    )


def _throttle(request: Request, action: str) -> None:
    if not settings.rate_limit_enabled:
        return
    ip = request.client.host if request.client else "unknown"
    if not rate_limit.hit(
        f"{action}:{ip}", limit=settings.auth_rate_limit_per_minute
    ):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")


async def _authenticate(db: AsyncSession, username: str, password: str) -> User:
    """登录共用：查用户 + bcrypt 校验 + 状态检查。"""
    user = (
        await db.execute(
            select(User).where(User.username == username, User.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return user


@router.post("/register", response_model=TokenResponse)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not settings.registration_open:
        raise HTTPException(status_code=403, detail="注册未开放")
    _throttle(request, "register")
    exists = (
        await db.execute(select(User.id).where(User.username == body.username))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    member = (
        await db.execute(select(Role).where(Role.name == "member"))
    ).scalar_one_or_none()
    if member is not None:
        db.add(UserRole(user_id=user.id, role_id=member.id))
    await db.flush()
    await seed_service.seed_money_categories(db, user.id)
    await db.commit()
    await db.refresh(user)
    return TokenResponse(token=create_token(user.id), user=_user_out(user))


@router.post("/login", response_model=TokenResponse)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    _throttle(request, "login")
    user = await _authenticate(db, body.username, body.password)
    await db.commit()  # 无写操作，仅为保持「路由内显式 commit」约定一致
    return TokenResponse(token=create_token(user.id), user=_user_out(user))


@router.get("/me", response_model=MeOut)
async def read_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    perms = await rbac_service.permission_codes(db, user.id)
    return MeOut(**_user_out(user).model_dump(), permissions=sorted(perms))


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}
