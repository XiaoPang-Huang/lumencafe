"""Skill 生命周期与注入组装（架构设计-增量 v1 §3.6；存储升级为文件夹库）。

- catalog：经 SkillHubProvider 代理搜索 + 本人已装集合标注 installed；
- install：provider.get() 拉 skill 包 → 清洗 slug → 落盘 skills/<slug>/SKILL.md
  （Agent Skills 开放标准：文件夹 + SKILL.md，已存在 409）→ user_skills 记录
  （app_id 固定 chat；name=slug 作文件夹库时代标记，用户拍板）；
- 存储真相源：技能库文件夹（SKILL.md）；DB 仅存用户安装关系（索引/开关/顺序）。
  零新增 DB 迁移；
- uninstall：删 user_skills 记录 + 删除 skills/<slug>/ 目录（SkillHub 来源）。
  单用户场景直接删目录；多用户引用计数为预留扩展点；
- 本地 skill：skills/ 下手工放入的合法包（SKILL.md 且 source 非 skillhub:*）
  自动合并进 list_mine（来源=本地，只读）。「扫描注册」预留点见 skill_library；
- enabled_skill_prompts：读盘 ∩ DB enabled。DB 有记录但目录被手动删除
  （文件夹库时代记录，name=slug 可判定）→ 自动清理 DB 记录；
  升级前旧数据（name=展示名、无目录、prompt 存 DB）→ 一次性回退读 DB
  （兼容分支，下版本可删）；正文注入以库为准，用户不可改写。
"""
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_conf import get_logger
from app.models.skill import UserSkill
from app.models.user import User
from app.schemas.skill import SkillItemOut
from app.services import skill_library
from app.services.skillhub import get_provider

logger = get_logger("skill")

# skill 包体积上限（N-增5）：prompt（SKILL.md 正文）≤4KB，安装时校验，超出 400
MAX_SKILL_PROMPT_CHARS = 4096

# 安装位置固定 chat（用户拍板，PRD P1-4 ②）
SKILL_APP_ID = "chat"

# 本地 skill（无 DB 记录）在列表里的占位 id：开关/卸载按钮据此禁用
LOCAL_SKILL_ID = 0


def _is_folder_era_row(row: UserSkill) -> bool:
    """判定是否为「文件夹库时代」安装的记录。

    本期起 install 写 name=slug（清洗后的目录名，如 meeting-notes），
    升级前旧记录的 name 为展示名（如「会议纪要」，清洗后为空串）。
    目录缺失时据此区分：文件夹库时代记录 → 自动清理 DB 记录；
    旧记录 → 走 DB prompt 兼容分支（下版本可删）。
    """
    return bool(row.name) and row.name == skill_library.sanitize_slug(row.name)


def _relative_path(entry: skill_library.LibraryEntry | None) -> str:
    """管理弹窗展示的存放位置（相对库根，如 skills/pdf-reader/）。"""
    if entry is None:
        return ""
    return f"skills/{entry.slug}/"


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
    """安装 skill：拉包 → 写盘 skills/<slug>/SKILL.md → 落库 user_skills。

    重复安装（DB 记录或目录已存在）409；平台不存在 404；包超 4KB 400。
    """
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

    # 清洗目录名 slug；provider 未给 slug 时回退用平台 id 清洗
    slug = skill_library.sanitize_slug(detail.slug or detail.skillhub_id)
    if not slug:
        raise HTTPException(status_code=400, detail="Skill 包标识非法，无法安装")

    # 落盘技能库（文件夹为真相源）；目录已存在 = 库中已有同名包 → 409。
    # 单用户场景下即「该 skill 已安装」；多用户引用计数为预留扩展点。
    try:
        skill_library.install_to_library(slug, detail.skill_md)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="已安装") from None

    # DB 仅存用户安装关系；prompt 冗余存正文（旧数据兼容分支用，下版本可删）
    # name=slug：文件夹库时代标记（手动删目录后据此自动清理 DB 记录）。
    skill = UserSkill(
        user_id=user.id,
        app_id=SKILL_APP_ID,
        skillhub_id=detail.skillhub_id,
        name=slug,
        icon=detail.icon,
        description=detail.description,
        prompt=detail.prompt,
        enabled=True,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    logger.info("skill install: user=%s skillhub_id=%s slug=%s", user.id, skillhub_id, slug)
    return skill


async def list_mine(db: AsyncSession, user_id: int, app_id: str) -> list[dict[str, object]]:
    """本人已安装列表（installed_at 升序）+ 库中本地 skill（来源=本地，只读）。

    返回 UserSkillOut 字段集 + source（skillhub/local）+ path（skills/<slug>/）。
    副作用：文件夹库时代记录若目录已被手动删除 → 自动清理 DB 记录（注释见
    enabled_skill_prompts；此处同样扫描，保证管理列表所见即真相源）。
    """
    rows = (
        await db.execute(
            select(UserSkill)
            .where(UserSkill.user_id == user_id, UserSkill.app_id == app_id)
            .order_by(UserSkill.installed_at, UserSkill.id)
        )
    ).scalars().all()

    index = skill_library.index_by_source()
    orphan_ids: list[int] = []
    out: list[dict[str, object]] = []
    for row in rows:
        entry = index.get(f"{skill_library.SOURCE_SKILLHUB_PREFIX}{row.skillhub_id}")
        if entry is None and _is_folder_era_row(row):
            # 文件夹库时代记录（name=slug）但目录缺失 = 手动删除 → 自动清理
            orphan_ids.append(row.id)
            continue
        out.append(
            {
                "id": row.id,
                "skillhub_id": row.skillhub_id,
                "name": row.name,
                "icon": row.icon,
                "description": row.description,
                "enabled": row.enabled,
                "installed_at": row.installed_at,
                "source": "skillhub",
                "path": _relative_path(entry),
            }
        )
    if orphan_ids:
        await db.execute(delete(UserSkill).where(UserSkill.id.in_(orphan_ids)))
        await db.commit()
        logger.info("skill orphan cleanup: user=%s ids=%s", user_id, orphan_ids)

    # 本地 skill 包（source 非 skillhub:* 且未被 DB 记录引用）→ 只读条目
    hub_sources = {f"{skill_library.SOURCE_SKILLHUB_PREFIX}{r.skillhub_id}" for r in rows}
    for entry in skill_library.scan_library():
        if entry.source.startswith(skill_library.SOURCE_SKILLHUB_PREFIX):
            continue
        if entry.source in hub_sources:
            continue  # 「扫描注册」预留：本地包若已登记 DB 则不重复展示
        out.append(
            {
                "id": LOCAL_SKILL_ID,
                "skillhub_id": "",
                "name": entry.name,
                "icon": "grid",
                "description": entry.description,
                "enabled": True,
                "installed_at": None,
                "source": "local",
                "path": _relative_path(entry),
            }
        )
    return out


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
    """卸载：删 user_skills 记录 + 删除 skills/<slug>/ 目录（仅 SkillHub 来源）。

    单用户场景直接删目录（文件夹由安装流程独占创建）；多用户引用计数为预留
    扩展点。本地包无 DB 记录，不经此路径（UI 只读）。
    """
    skill = (
        await db.execute(
            select(UserSkill).where(UserSkill.id == skill_id, UserSkill.user_id == user_id)
        )
    ).scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    entry = skill_library.find_by_skillhub_id(skill.skillhub_id)
    await db.delete(skill)
    await db.commit()
    if entry is not None:
        skill_library.remove_from_library(entry)
    logger.info("skill uninstall: user=%s id=%s", user_id, skill_id)


async def enabled_skill_prompts(db: AsyncSession, user_id: int, app_id: str) -> list[str]:
    """注入组装：库中 SKILL.md 正文 ∩ DB enabled，按 installed_at 升序。

    - 目录在库：正文以盘为准（用户不可改写，DB prompt 仅冗余）；
    - 目录缺失 + 文件夹库时代记录（name=slug）：手动删除所致 → 自动清理 DB
      记录，不注入；
    - 目录缺失 + 旧记录（name=展示名）：升级前装的存量 → 回退读 DB prompt
      （兼容分支，下版本迁移完成后删除）。
    """
    rows = (
        await db.execute(
            select(UserSkill)
            .where(
                UserSkill.user_id == user_id,
                UserSkill.app_id == app_id,
                UserSkill.enabled.is_(True),
            )
            .order_by(UserSkill.installed_at, UserSkill.id)
        )
    ).scalars().all()

    index = skill_library.index_by_source()
    prompts: list[str] = []
    orphan_ids: list[int] = []
    for row in rows:
        entry = index.get(f"{skill_library.SOURCE_SKILLHUB_PREFIX}{row.skillhub_id}")
        if entry is not None:
            prompts.append(entry.body)
        elif _is_folder_era_row(row):
            # 文件夹库时代记录但目录缺失（手动删除）→ 自动清理 DB 记录
            orphan_ids.append(row.id)
        else:
            # [兼容分支-下版本可删] 升级前旧数据：无目录、prompt 存 DB，回退读存量
            prompts.append(str(row.prompt))
    if orphan_ids:
        await db.execute(delete(UserSkill).where(UserSkill.id.in_(orphan_ids)))
        await db.commit()
        logger.info("skill orphan cleanup: user=%s ids=%s", user_id, orphan_ids)
    return prompts
