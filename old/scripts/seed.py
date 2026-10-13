"""初始化种子数据：分类、应用注册表、白名单成员（含两个开发账号）。

用法（容器内）：
    docker compose exec api python -m scripts.seed
"""
import asyncio

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import AppRegistry, Category, WhitelistUser

CATEGORIES = ["心情", "科研", "工具"]

APPS = [
    {"id": "chat", "name": "小岛chat", "desc": "随手聊聊的 AI 伙伴", "color": "#FFDDE5", "icon": "聊", "category": "心情", "sort": 1},
    {"id": "breath", "name": "呼吸引导", "desc": "4-7-8 呼吸法，日常放松", "color": "#D8F0E0", "icon": "呼", "category": "心情", "sort": 2},
    {"id": "focus", "name": "专注打卡", "desc": "每日待办，完成打勾", "color": "#FFEFC2", "icon": "卡", "category": "工具", "sort": 3},
    {"id": "papers", "name": "文献推送", "desc": "PubMed 每日新文献，中文摘要", "color": "#D8EAF7", "icon": "文", "category": "科研", "sort": 4},
    {"id": "scales", "name": "量表速查", "desc": "MMSE / MoCA / UPDRS 速查", "color": "#E6DEF8", "icon": "表", "category": "科研", "sort": 5},
]

# dev_login 模式下的两个开发账号（对应小程序端 code 传 "dev:user1" / "dev:user2"）
USERS = [
    {"openid": "dev:user1", "nickname": "岛主"},
    {"openid": "dev:user2", "nickname": "岛民"},
]


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        for i, name in enumerate(CATEGORIES, start=1):
            if not (await db.execute(select(Category).where(Category.name == name))).scalar_one_or_none():
                db.add(Category(name=name, sort=i))
        await db.flush()
        cat_map = {c.name: c.id for c in (await db.execute(select(Category))).scalars().all()}

        for a in APPS:
            row = (
                await db.execute(select(AppRegistry).where(AppRegistry.id == a["id"]))
            ).scalar_one_or_none()
            if row is None:
                db.add(AppRegistry(
                    id=a["id"], name=a["name"], desc=a["desc"], color=a["color"],
                    icon=a["icon"], category_id=cat_map.get(a["category"]), sort=a["sort"],
                ))
            else:
                # 已存在也同步名称/描述等展示字段（应用定位调整时靠它刷新旧数据）
                row.name = a["name"]
                row.desc = a["desc"]
                row.color = a["color"]
                row.icon = a["icon"]
                row.category_id = cat_map.get(a["category"])
                row.sort = a["sort"]

        for u in USERS:
            if not (await db.execute(select(WhitelistUser).where(WhitelistUser.openid == u["openid"]))).scalar_one_or_none():
                db.add(WhitelistUser(openid=u["openid"], nickname=u["nickname"], role="admin"))

        await db.commit()
    print("seed done")


if __name__ == "__main__":
    asyncio.run(main())
