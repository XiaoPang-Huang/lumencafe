"""SkillHub 代理 + 已安装技能管理（架构设计-增量 v1 §3.6，权限同 app:chat）。

- GET    /skills/catalog?q=&page=&page_size=  SkillHub 目录（后端代理，含 installed 标记）
- POST   /skills/install                        {skillhub_id} → 拉 skill 包落库；已装 409
- GET    /skills/mine?app_id=chat               本人已安装列表（prompt 不回显）
- PUT    /skills/{id}/enabled                   {enabled} 开关；关闭即停止注入
- DELETE /skills/{id}                           卸载（删除记录）

写操作限流（N-增5）+ 日志（service 层已记）；安装位置固定 app_id=chat（用户拍板）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.skill import (
    CatalogOut,
    CatalogQuery,
    SkillEnabledIn,
    SkillInstallIn,
    UserSkillOut,
)
from app.services import (
    chat_service,
    rate_limit,
    rbac_service,
    skill_library,
    skill_service,
)

router = APIRouter(prefix="/skills", tags=["skills"])

# 写操作限流（N-增5/N14）：每用户每分钟 20 次安装/开关/卸载
_WRITE_LIMIT = 20


async def _check_chat_permission(db: AsyncSession, user: User) -> None:
    """P2-1：本期不新建权限点，skill 接口复用 app:chat 权限。"""
    app = await chat_service.get_app(db, "chat")
    perms = await rbac_service.permission_codes(db, user.id)
    if app.perm_code not in perms:
        raise HTTPException(status_code=403, detail="权限不足")


def _check_write_limit(user_id: int) -> None:
    if not rate_limit.hit(f"skills-write:{user_id}", limit=_WRITE_LIMIT):
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")


def _user_skill_out(s) -> UserSkillOut:
    return UserSkillOut(
        id=s.id,
        skillhub_id=s.skillhub_id,
        name=s.name,
        icon=s.icon,
        description=s.description,
        enabled=s.enabled,
        installed_at=s.installed_at,
        source=getattr(s, "source", "skillhub"),
        path=getattr(s, "path", ""),
    )


@router.get("/catalog", response_model=CatalogOut)
async def skill_catalog(
    query: CatalogQuery = Depends(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SkillHub 列表（后端代理，避免前端跨域/暴露平台细节）。"""
    await _check_chat_permission(db, user)
    return await skill_service.catalog(db, user, query.q, query.page, query.page_size)


@router.post("/install", response_model=UserSkillOut, status_code=201)
async def skill_install(
    body: SkillInstallIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """安装 skill 到「对话」应用下；已装 409，平台不存在 404，包超 4KB 400。"""
    await _check_chat_permission(db, user)
    _check_write_limit(user.id)
    skill = await skill_service.install(db, user, body.skillhub_id)
    out = _user_skill_out(skill)
    # 回显库内存放位置（skills/<slug>/）
    entry = skill_library.find_by_skillhub_id(skill.skillhub_id)
    if entry is not None:
        out.path = f"skills/{entry.slug}/"
    return out


@router.get("/mine", response_model=list[UserSkillOut])
async def skill_mine(
    app_id: str = "chat",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """本人已安装列表（应用设置 · 对话 · 已安装技能；含库中本地包，只读）。"""
    await _check_chat_permission(db, user)
    rows = await skill_service.list_mine(db, user.id, app_id)
    return [UserSkillOut(**s) for s in rows]


@router.put("/{skill_id}/enabled")
async def skill_set_enabled(
    skill_id: int,
    body: SkillEnabledIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开关 skill；关闭即停止注入（下一次 POST /chat 生效）。"""
    await _check_chat_permission(db, user)
    _check_write_limit(user.id)
    await skill_service.set_enabled(db, user.id, skill_id, body.enabled)
    return {"ok": True}


@router.delete("/{skill_id}")
async def skill_uninstall(
    skill_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """卸载（删除记录）；写操作限流 + 日志。"""
    await _check_chat_permission(db, user)
    _check_write_limit(user.id)
    await skill_service.uninstall(db, user.id, skill_id)
    return {"ok": True}
