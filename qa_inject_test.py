# QA 取证：skill 注入组装（chat_service.build_messages 真实代码路径 + 真实 DB/磁盘）
import asyncio
import sys

import httpx
from sqlalchemy import select

BASE = "http://127.0.0.1:8000"
TOKEN = open("/tmp/qa_token.txt").read().strip()
H = {"Authorization": f"Bearer {TOKEN}"}

VALID_MD = """---
name: qa-inject-check
description: 注入验证技能
---

【QA-INJECT-MARKER-7f3d】注入正文标记。
"""

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


async def main():
    from app.db import SessionLocal
    from app.models.user import User
    from app.services import chat_service, skill_service

    async with SessionLocal() as db:
        r = httpx.post(BASE + "/chat/conversations", headers=H,
                       json={"app_id": "chat", "title": "qa-inject"})
        check("建会话", r.status_code in (200, 201), r.status_code)
        conv_id = r.json()["id"]
        u = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        uid = u.id

        r = httpx.post(BASE + "/skills/upload", headers=H,
                       files={"file": ("qa-inject.md", VALID_MD.encode(), "text/markdown")})
        check("上传 201", r.status_code == 201, r.text[:150])
        sid = r.json()["id"]

        msgs = await chat_service.build_messages(db, uid, "chat", conv_id, "你好")
        check("开关开 → system 含 skill 正文标记", "【QA-INJECT-MARKER-7f3d】" in msgs[0]["content"])

        httpx.put(BASE + f"/skills/{sid}/enabled", headers=H, json={"enabled": False})
        msgs = await chat_service.build_messages(db, uid, "chat", conv_id, "你好")
        check("开关关 → system 不含标记", "【QA-INJECT-MARKER-7f3d】" not in msgs[0]["content"])

        httpx.put(BASE + f"/skills/{sid}/enabled", headers=H, json={"enabled": True})
        r = httpx.post(BASE + "/skills/install", headers=H,
                       json={"skillhub_id": "mock-translation-polish"})
        check("install mock 201", r.status_code == 201, r.text[:150])
        MD2 = "---\nname: qa-inject-second\ndescription: 第二个\n---\n【QA-SECOND-MARKER-a1b2】\n"
        r = httpx.post(BASE + "/skills/upload", headers=H,
                       files={"file": ("qa-second.md", MD2.encode(), "text/markdown")})
        check("第二个上传 201", r.status_code == 201, r.text[:150])

        prompts = await skill_service.enabled_skill_prompts(db, uid, "chat")
        joined = "\n".join(prompts)
        check("混装两者都注入",
              "【QA-INJECT-MARKER-7f3d】" in joined and "【QA-SECOND-MARKER-a1b2】" in joined,
              len(prompts))
        i1 = joined.find("【QA-INJECT-MARKER-7f3d】")
        i2 = joined.find("【QA-SECOND-MARKER-a1b2】")
        check("注入顺序 installed_at 升序（先装在前）", 0 < i1 < i2, (i1, i2))

        r = httpx.get(BASE + "/skills/mine", headers=H)
        for s in r.json():
            httpx.delete(BASE + f"/skills/{s['id']}", headers=H)
        msgs = await chat_service.build_messages(db, uid, "chat", conv_id, "你好")
        check("全部卸载后 system 无 skill 标记", "QA-INJECT" not in msgs[0]["content"]
              and "QA-SECOND" not in msgs[0]["content"])

    print("\n=== SUMMARY ===")
    print("failed:", fails if fails else "none")
    return 1 if fails else 0


sys.exit(asyncio.run(main()))
