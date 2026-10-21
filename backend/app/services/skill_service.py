"""Skill 生命周期与注入组装（架构设计-增量 v1 §3.6）。

- catalog：经 SkillHubProvider 代理搜索 + 本人已装集合标注 installed；
- install：provider.get() 拉 skill 包 → 落库 user_skills（app_id 固定 chat，用户拍板）；
  prompt ≤4KB（N-增5）；已装 409；平台不存在 404；
- enabled_skill_prompts：仅 enabled=true 的记录，按 installed_at 升序返回 prompt 片段
  （chat_service.build_messages 注入 system：内置常量在前、片段在后，用户不可改写）。
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from app.models.skill import UserSkill
from app.models.user import User
from app.schemas.skill import SkillItemOut
from app.services.skillhub import get_provider

logger = get_logger("skill")

# skill 包体积上限（N-增5）：prompt ≤4KB，安装时校验，超出 400
MAX_SKILL_PROMPT_CHARS = 4096

# 安装位置固定 chat（用户拍板，PRD P1-4 ②）
SKILL_APP_ID = "chat"


async def catalog(
    db: AsyncSession, user: User, q: str, page: int, page_size: int
) -> dict[str, object]:
    """SkillHub 目录（后端代理）：搜索 + 本人已安装标记。"""
    items, total = await get_provider().search(q, page, page_size)
    installed_rows = (
        await db.execute(
            select(UserSkill.skillhub_id).where(
                UserSkill.user_id == user.id, UserSkill.app_id == SKILL_APP_ID
            )
        )
    ).scalars().all()
    installed_set = set(installed_rows)
    return {
        "items": [
            SkillItemOut(
                skillhub_id=i.skillhub_id,
                name=i.name,
                icon=i.icon,
                description=i.description,
                installed=i.skillhub_id in installed_set,
            )
            for i in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def install(db: AsyncSession, user: User, skillhub_id: str) -> UserSkill:
    """安装 skill 到「对话」应用下（用户级全局生效，Q9）。重复安装 409。"""
    exists = (
        await db.execute(
            select(UserSkill.id).where(
                UserSkill.user_id == user.id,
                UserSkill.app_id == SKILL_APP_ID,
                UserSkill.skillhub_id == skillhub_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="已安装")

    detail = await get_provider().get(skillhub_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Skill 不存在")

    if len(detail.prompt) > MAX_SKILL_PROMPT_CHARS:
        raise HTTPException(status_code=400, detail="Skill 包超过 4KB 上限，无法安装")

    skill = UserSkill(
        user_id=user.id,
        app_id=SKILL_APP_ID,
        skillhub_id=detail.skillhub_id,
        name=detail.name,
        icon=detail.icon,
        description=detail.description,
        prompt=detail.prompt,
        enabled=True,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    logger.info("skill install: user=%s skillhub_id=%s", user.id, skillhub_id)
    return skill


async def list_mine(db: AsyncSession, user_id: int, app_id: str) -> list[UserSkill]:
    """本人已安装列表（installed_at 升序，与注入顺序一致）。"""
    rows = (
        await db.execute(
            select(UserSkill)
            .where(UserSkill.user_id == user_id, UserSkill.app_id == app_id)
            .order_by(UserSkill.installed_at, UserSkill.id)
        )
    ).scalars().all()
    return list(rows)


async def set_enabled(db: AsyncSession, user_id: int, skill_id: int, enabled: bool) -> None:
    """开关 skill；关闭即停止注入。仅本人记录可操作。"""
    skill = (
        await db.execute(
            select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        )
    ).scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    skill.enabled = enabled
    await db.commit()
    logger.info("skill toggle: user=%s id=%s enabled=%s", user_id, skill_id, enabled)


async def uninstall(db: AsyncSession, user_id: int, skill_id: int) -> None:
    """卸载（删除记录）。仅本人记录可操作。"""
    skill = (
        await db.execute(
            select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        )
    ).scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    await db.delete(skill)
    await db.commit()
    logger.info("skill uninstall: user=%s id=%s", user_id, skill_id)


async def enabled_skill_prompts(db: AsyncSession, user_id: int, app_id: str) -> list[str]:
    """注入组装：仅已启用 skill 的 prompt 片段，按 installed_at 升序。"""
    rows = (
        await db.execute(
            select(UserSkill.prompt)
            .where(
                UserSkill.user_id == user_id,
                UserSkill.app_id == app_id,
                UserSkill.enabled.is_(True),
            )
            .order_by(UserSkill.installed_at, UserSkill.id)
        )
    ).scalars().all()
    return [str(p) for p in rows]
