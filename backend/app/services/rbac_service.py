"""RBAC 查询服务：权限点集合判定（架构设计 §6）。

判定只查权限点集合，不写死角色名；2 用户规模无缓存必要，
未来需要时在此加 TTL 缓存，接口不变。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.user import Role, User


async def permission_codes(db: AsyncSession, user_id: int) -> set[str]:
    """某用户全部权限点 code（user_roles → role_permissions，distinct）。"""
    user = (
        await db.execute(
            select(User)
            .options(joinedload(User.roles).joinedload(Role.permissions))
            .where(User.id == user_id)
        )
    ).unique().scalar_one_or_none()
    if user is None:
        return set()
    return {p.code for role in user.roles for p in role.permissions}
