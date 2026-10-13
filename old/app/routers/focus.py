from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import DailyTaskDone, FocusCheckin, FocusTodo, MoodRecord, UserSetting, WhitelistUser
from ..schemas import MoodIn, TaskDoneIn, TodoIn, TodoPut

router = APIRouter(tags=["focus"])

# 每日一件小事任务池（服务端按日轮换，跟随用户偏好设置）
TASK_POOLS = {
    "papers": {
        "label": "文献类",
        "tasks": [
            "精读一篇文献摘要，写 3 行笔记",
            "给收藏的文献补 3 个标签",
            "梳理一个研究问题，列出 5 个关键词",
            "读一篇综述的引言，划出核心假设",
        ],
    },
    "tidy": {
        "label": "整理类",
        "tasks": [
            "整理桌面 10 分钟",
            "清理手机相册 10 张截图",
            "归置书架或文件夹 15 分钟",
            "删掉 5 个不再需要的文件",
        ],
    },
}


def pick_task(day: date, pref: str) -> dict:
    """按日轮换挑选今日小事。pref: papers / tidy / 其他按日交替。"""
    if pref not in TASK_POOLS:
        pref = "papers" if day.toordinal() % 2 == 0 else "tidy"
    pool = TASK_POOLS[pref]
    content = pool["tasks"][day.toordinal() % len(pool["tasks"])]
    return {"category": pool["label"], "content": content}


async def get_pref(db: AsyncSession, openid: str) -> str:
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == openid,
                UserSetting.scope == "user",
                UserSetting.key == "daily_task_pref",
            )
        )
    ).scalar_one_or_none()
    if row and isinstance(row.value, dict):
        return str(row.value.get("kind", "mix"))
    return "mix"


async def compute_streak(db: AsyncSession, openid: str) -> tuple[int, list[bool], bool]:
    rows = (
        await db.execute(
            select(FocusCheckin.date)
            .where(FocusCheckin.user_id == openid)
            .order_by(FocusCheckin.date.desc())
        )
    ).scalars().all()
    checked = set(rows)
    today = date.today()
    # 本周圆点：今天往前 7 天（含今天）
    week = [(today - timedelta(days=i)) in checked for i in range(6, -1, -1)]
    # 连续天数：从今天往前数；今天没打卡则从昨天起算（断签当天不打断已有记录）
    cursor = today if today in checked else today - timedelta(days=1)
    streak = 0
    while cursor in checked:
        streak += 1
        cursor -= timedelta(days=1)
    return streak, week, today in checked


async def today_state(user: WhitelistUser, db: AsyncSession) -> dict:
    openid = user.openid
    today = date.today()
    streak, week, checked_today = await compute_streak(db, openid)

    mood_row = (
        await db.execute(
            select(MoodRecord).where(MoodRecord.user_id == openid, MoodRecord.date == today)
        )
    ).scalar_one_or_none()

    task_row = (
        await db.execute(
            select(DailyTaskDone).where(DailyTaskDone.user_id == openid, DailyTaskDone.date == today)
        )
    ).scalar_one_or_none()

    task = pick_task(today, await get_pref(db, openid))
    return {
        "streak": streak,
        "week": week,
        "checked_today": checked_today,
        "mood_today": mood_row.mood if mood_row else None,
        "task": task,
        "task_done": task_row.done if task_row else False,
    }


@router.get("/focus/today")
async def focus_today(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await today_state(user, db)


@router.post("/focus/checkin")
async def focus_checkin(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # ON CONFLICT DO NOTHING：重复打卡幂等，不走异常回滚路径
    stmt = (
        pg_insert(FocusCheckin)
        .values(user_id=user.openid, date=date.today())
        .on_conflict_do_nothing(index_elements=["user_id", "date"])
    )
    await db.execute(stmt)
    await db.commit()
    return await today_state(user, db)


@router.post("/focus/task/done")
async def focus_task_done(
    body: TaskDoneIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        pg_insert(DailyTaskDone)
        .values(user_id=user.openid, date=date.today(), done=body.done)
        .on_conflict_do_update(
            index_elements=["user_id", "date"], set_={"done": body.done}
        )
    )
    await db.execute(stmt)
    await db.commit()
    return await today_state(user, db)


@router.post("/mood")
async def record_mood(
    body: MoodIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        pg_insert(MoodRecord)
        .values(user_id=user.openid, date=date.today(), mood=body.mood)
        .on_conflict_do_update(
            index_elements=["user_id", "date"], set_={"mood": body.mood}
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True, "mood": body.mood, "date": str(date.today())}


@router.get("/mood/history")
async def mood_history(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(MoodRecord)
            .where(MoodRecord.user_id == user.openid)
            .order_by(MoodRecord.date.desc())
            .limit(30)
        )
    ).scalars().all()
    return {"history": [{"date": str(r.date), "mood": r.mood} for r in rows]}


# ---------- 待办事项（自建、打勾、删除） ----------

@router.get("/focus/todos")
async def list_todos(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(FocusTodo)
            .where(FocusTodo.user_id == user.openid)
            .order_by(FocusTodo.created_at.asc())
        )
    ).scalars().all()
    return {"todos": [{"id": r.id, "title": r.title, "done": r.done} for r in rows]}


@router.post("/focus/todos")
async def create_todo(
    body: TodoIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    todo = FocusTodo(user_id=user.openid, title=body.title.strip())
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return {"id": todo.id, "title": todo.title, "done": todo.done}


@router.put("/focus/todos/{todo_id}")
async def update_todo(
    todo_id: int,
    body: TodoPut,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    todo = (
        await db.execute(
            select(FocusTodo).where(
                FocusTodo.id == todo_id, FocusTodo.user_id == user.openid
            )
        )
    ).scalar_one_or_none()
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    if body.title is not None:
        todo.title = body.title.strip()
    if body.done is not None:
        todo.done = body.done
    await db.commit()
    return {"id": todo.id, "title": todo.title, "done": todo.done}


@router.delete("/focus/todos/{todo_id}")
async def delete_todo(
    todo_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    todo = (
        await db.execute(
            select(FocusTodo).where(
                FocusTodo.id == todo_id, FocusTodo.user_id == user.openid
            )
        )
    ).scalar_one_or_none()
    if todo is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    await db.delete(todo)
    await db.commit()
    return {"ok": True}
