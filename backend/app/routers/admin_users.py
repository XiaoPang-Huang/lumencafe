"""平台管理-成员与 RBAC（PRD §4.2，权限点 admin:users）。

- 删除用户 = 软删除（is_deleted=true + is_active=false，PRD Q6）；
- 预置角色（built_in）不可删除；角色权限点整体重设；
- 管理员不能停用/删除自己（防锁死）。
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserDetailOut,
    AdminUserOut,
    AdminUserUpdate,
    PermissionOut,
    ResetPasswordOut,
    RoleBrief,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    SetPermissionsRequest,
    SetRolesRequest,
    UserPage,
)
from app.security import hash_password
from app.services import rbac_service
from app.services.seed import seed_money_categories

router = APIRouter(prefix="/admin", tags=["admin-users"])


async def _admin(user: User = Depends(require_permission("admin:users"))) -> User:
    """当前管理员（权限点已由依赖校验）。"""
    return user


def _role_briefs(user: User) -> list[RoleBrief]:
    return [RoleBrief(id=r.id, name=r.name) for r in sorted(user.roles, key=lambda r: r.id)]


def _role_out(role: Role) -> RoleOut:
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        built_in=role.built_in,
        permissions=[
            PermissionOut(code=p.code, name=p.name, description=p.description)
            for p in sorted(role.permissions, key=lambda p: p.id)
        ],
    )


def _user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        is_active=user.is_active,
        is_deleted=user.is_deleted,
        roles=_role_briefs(user),
        created_at=user.created_at,
    )


async def _get_user(db: AsyncSession, uid: int) -> User:
    user = (
        await db.execute(select(User).where(User.id == uid, User.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


async def _get_role(db: AsyncSession, rid: int) -> Role:
    role = (await db.execute(select(Role).where(Role.id == rid))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


async def _validate_role_ids(db: AsyncSession, role_ids: list[int]) -> None:
    if not role_ids:
        return
    count = (
        await db.execute(select(func.count(Role.id)).where(Role.id.in_(role_ids)))
    ).scalar_one()
    if count != len(set(role_ids)):
        raise HTTPException(status_code=400, detail="存在无效角色 ID")


async def _validate_perm_codes(db: AsyncSession, codes: list[str]) -> None:
    if not codes:
        return
    count = (
        await db.execute(select(func.count(Permission.id)).where(Permission.code.in_(codes)))
    ).scalar_one()
    if count != len(set(codes)):
        raise HTTPException(status_code=400, detail="存在无效权限点")


# ── 用户管理 ────────────────────────────────────────────
@router.get("/users", response_model=UserPage)
async def list_users(
    admin: User = Depends(_admin),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total = (
        await db.execute(select(func.count(User.id)).where(User.is_deleted.is_(False)))
    ).scalar_one()
    users = (
        await db.execute(
            select(User)
            .where(User.is_deleted.is_(False))
            .order_by(User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return UserPage(
        items=[_user_out(u) for u in users], total=total, page=page, page_size=page_size
    )


@router.post("/users", response_model=AdminUserOut, status_code=201)
async def create_user(
    body: AdminUserCreate,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(User.id).where(User.username == body.username))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    await _validate_role_ids(db, body.role_ids)
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname,
    )
    db.add(user)
    await db.flush()
    role_ids = body.role_ids
    if not role_ids:
        member = (
            await db.execute(select(Role).where(Role.name == "member"))
        ).scalar_one_or_none()
        role_ids = [member.id] if member is not None else []
    for rid in role_ids:
        db.add(UserRole(user_id=user.id, role_id=rid))
    await db.flush()
    await seed_money_categories(db, user.id)  # 新用户补记账内置分类
    await db.commit()
    await db.refresh(user)
    return _user_out(user)


@router.get("/users/{uid}", response_model=AdminUserDetailOut)
async def get_user(uid: int, admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, uid)
    perms = await rbac_service.permission_codes(db, user.id)
    return AdminUserDetailOut(**_user_out(user).model_dump(), permissions=sorted(perms))


@router.put("/users/{uid}", response_model=AdminUserOut)
async def update_user(
    uid: int,
    body: AdminUserUpdate,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user(db, uid)
    if body.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能停用自己")
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.commit()
    await db.refresh(user)
    return _user_out(user)


@router.put("/users/{uid}/roles", response_model=AdminUserOut)
async def set_user_roles(
    uid: int,
    body: SetRolesRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user(db, uid)
    await _validate_role_ids(db, body.role_ids)
    await db.execute(delete(UserRole).where(UserRole.user_id == uid))
    for rid in set(body.role_ids):
        db.add(UserRole(user_id=uid, role_id=rid))
    await db.commit()
    await db.refresh(user)
    return _user_out(user)


@router.post("/users/{uid}/reset-password", response_model=ResetPasswordOut)
async def reset_password(
    uid: int, admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)
):
    user = await _get_user(db, uid)
    new_password = secrets.token_urlsafe(9)  # 12 位，仅本次响应返回一次
    user.password_hash = hash_password(new_password)
    await db.commit()
    return ResetPasswordOut(new_password=new_password)


@router.delete("/users/{uid}")
async def delete_user(uid: int, admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)):
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    user = await _get_user(db, uid)
    user.is_deleted = True  # 软删除：数据保留（PRD Q6）
    user.is_active = False
    await db.commit()
    return {"ok": True}


# ── 角色与权限点 ────────────────────────────────────────
@router.get("/roles", response_model=list[RoleOut])
async def list_roles(admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)):
    roles = (
        await db.execute(select(Role).order_by(Role.id))
    ).scalars().all()
    return [_role_out(r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreate, admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)
):
    exists = (
        await db.execute(select(Role.id).where(Role.name == body.name))
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="角色名已存在")
    role = Role(name=body.name, description=body.description)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return _role_out(role)


@router.put("/roles/{rid}", response_model=RoleOut)
async def update_role(
    rid: int,
    body: RoleUpdate,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    role = await _get_role(db, rid)
    if body.name is not None and body.name != role.name:
        exists = (
            await db.execute(select(Role.id).where(Role.name == body.name))
        ).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(status_code=409, detail="角色名已存在")
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    await db.commit()
    await db.refresh(role)
    return _role_out(role)


@router.put("/roles/{rid}/permissions", response_model=RoleOut)
async def set_role_permissions(
    rid: int,
    body: SetPermissionsRequest,
    admin: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    role = await _get_role(db, rid)
    await _validate_perm_codes(db, body.permissions)
    code_to_id = {
        p.code: p.id
        for p in (await db.execute(select(Permission))).scalars().all()
    }
    await db.execute(delete(RolePermission).where(RolePermission.role_id == rid))
    for code in set(body.permissions):
        db.add(RolePermission(role_id=rid, permission_id=code_to_id[code]))
    await db.commit()
    await db.refresh(role)
    return _role_out(role)


@router.delete("/roles/{rid}")
async def delete_role(rid: int, admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)):
    role = await _get_role(db, rid)
    if role.built_in:
        raise HTTPException(status_code=403, detail="预置角色不可删除")
    await db.delete(role)  # user_roles / role_permissions 级联清理
    await db.commit()
    return {"ok": True}


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    admin: User = Depends(_admin), db: AsyncSession = Depends(get_db)
):
    perms = (
        await db.execute(select(Permission).order_by(Permission.id))
    ).scalars().all()
    return list(perms)
