"""统计：个人足迹聚合 + 各应用数据空间容量。"""
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    ChatMessage,
    DailyTaskDone,
    FocusCheckin,
    MoodRecord,
    PaperFavorite,
    PaperNote,
    WhitelistUser,
)
from ..routers.focus import compute_streak

router = APIRouter(prefix="/stats", tags=["stats"])

# 各应用 → 所属数据表（展示「独立存放」用；将来拆库后按库统计）
APP_TABLES: list[tuple[str, str, list[str]]] = [
    ("papers", "文献推送", ["papers", "paper_favorites", "paper_notes", "paper_explanations"]),
    ("focus", "专注打卡", ["focus_checkins", "focus_task_done"]),
    ("mood", "心情", ["mood_records"]),
    ("chat", "小岛chat", ["chat_messages"]),
    ("settings", "设置与空间", ["user_settings", "whitelist_users", "categories", "app_registry", "app_visibility", "space_invites", "danger_requests"]),
]

# 各表行数映射（与 APP_TABLES 对齐；papers 主表按全表统计，故不在此表）
TABLE_COUNTERS = {
    "paper_favorites": lambda openid: select(func.count()).select_from(PaperFavorite).where(PaperFavorite.user_id == openid),
    "paper_notes": lambda openid: select(func.count()).select_from(PaperNote).where(PaperNote.user_id == openid),
    "paper_explanations": lambda openid: select(func.count()).select_from(PaperNote).where(PaperNote.user_id == openid),
    "focus_checkins": lambda openid: select(func.count()).select_from(FocusCheckin).where(FocusCheckin.user_id == openid),
    "focus_task_done": lambda openid: select(func.count()).select_from(DailyTaskDone).where(DailyTaskDone.user_id == openid),
    "mood_records": lambda openid: select(func.count()).select_from(MoodRecord).where(MoodRecord.user_id == openid),
    "chat_messages": lambda openid: select(func.count()).select_from(ChatMessage).where(ChatMessage.user_id == openid),
}


@router.get("/footprint")
async def footprint(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    streak, _, _ = await compute_streak(db, user.openid)
    checkins_total = (
        await db.execute(select(func.count()).select_from(FocusCheckin).where(FocusCheckin.user_id == user.openid))
    ).scalar_one()
    favorites = (
        await db.execute(select(func.count()).select_from(PaperFavorite).where(PaperFavorite.user_id == user.openid))
    ).scalar_one()
    tasks_done = (
        await db.execute(
            select(func.count()).select_from(DailyTaskDone).where(
                DailyTaskDone.user_id == user.openid, DailyTaskDone.done.is_(True)
            )
        )
    ).scalar_one()
    moods = (
        await db.execute(select(func.count()).select_from(MoodRecord).where(MoodRecord.user_id == user.openid))
    ).scalar_one()
    return {
        "streak": streak,
        "checkins_total": checkins_total,
        "papers_favorited": favorites,
        "tasks_done": tasks_done,
        "moods_recorded": moods,
    }


@router.get("/storage")
async def storage(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """各应用记录数（按当前用户计）+ 表占用大小（全表物理大小）。

    当前为单库多表；拆分为独立 schema/库后，此处改为按库统计，接口不变。
    """
    apps = []
    for app_id, name, tables in APP_TABLES:
        size = 0
        for t in tables:
            size += (
                await db.execute(text("SELECT pg_total_relation_size(:t)"), {"t": t})
            ).scalar_one()
        # 记录数：能按用户统计的按用户，其余按全表
        records = 0
        for t in tables:
            counter = TABLE_COUNTERS.get(t)
            if counter is not None and t != "papers":
                records += (await db.execute(counter(user.openid))).scalar_one()
            else:
                records += (await db.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar_one()
        apps.append({"id": app_id, "name": name, "records": records, "size_bytes": size})
    return {"apps": apps}
