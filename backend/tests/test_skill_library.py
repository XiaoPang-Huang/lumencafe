"""Skill 文件夹库测试（Agent Skills 开放标准：skills/<slug>/SKILL.md 为真相源）。

覆盖：
- install 真实落盘 + DB 记录（SKILL.md frontmatter 四键 + 正文）；
- 管理列表回显存放位置（skills/<slug>/）与来源（skillhub/local）；
- 对话注入以盘为准（改写 SKILL.md 后注入新正文）；
- 卸载删记录 + 删目录；
- 手工本地包识别（来源=本地，id=0 只读，开关/卸载 404，不被误删）；
- 旧 DB 数据兼容（name=展示名、无目录 → 回退读 DB prompt）；
- 手动删除目录后 DB 记录自动清理（name=slug 的文件夹库时代记录）。

所有用例经 autouse fixture 把 SKILL_LIBRARY_DIR 重定向到 tmp 目录。
"""

import pytest

from app.db import SessionLocal
from app.models.skill import UserSkill
from app.services import llm_gateway, skill_library
from tests.conftest import login


@pytest.fixture(autouse=True)
def _skill_library_tmp(tmp_path, monkeypatch):
    """测试用临时技能库（环境变量每次调用时读取，函数级隔离）。"""
    monkeypatch.setenv("SKILL_LIBRARY_DIR", str(tmp_path / "skills"))


async def _chat_user(client, username="libuser"):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    return await login(client, username, "pass-123")


def _skill_md(slug: str, source: str, body: str, description: str = "测试技能") -> str:
    return (
        "---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        f"source: {source}\n"
        "version: 2.0.0\n"
        "---\n\n"
        f"{body}\n"
    )


async def test_install_writes_library_and_db(client):
    """install → skills/<slug>/SKILL.md 真实落盘（frontmatter 四键）+ DB 记录。"""
    headers = await _chat_user(client)
    resp = await client.post(
        "/skills/install", json={"skillhub_id": "mock-translation-polish"}, headers=headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "skillhub"
    assert body["path"] == "skills/translation-polish/"

    # 磁盘真相源：SKILL.md 存在且 frontmatter 合规
    skill_md = skill_library.library_dir() / "translation-polish" / "SKILL.md"
    assert skill_md.is_file()
    parsed = skill_library.parse_skill_md(skill_md.read_text(encoding="utf-8"))
    assert parsed["name"] == "translation-polish"
    assert parsed["source"] == "skillhub:mock-translation-polish"
    assert parsed["version"] == "1.0.0"
    assert parsed["description"]
    assert parsed["body"].startswith("【技能：")

    # 目录已存在 → 重复安装 409
    resp = await client.post(
        "/skills/install", json={"skillhub_id": "mock-translation-polish"}, headers=headers
    )
    assert resp.status_code == 409


async def test_mine_shows_path_and_local_package(client, tmp_path):
    """管理列表：安装包回显路径；手工放入的本地包出现（来源=本地，只读）。"""
    headers = await _chat_user(client)
    await client.post(
        "/skills/install", json={"skillhub_id": "mock-sql-helper"}, headers=headers
    )

    # 手工放入本地包（合法 SKILL.md，source 非 skillhub:*）
    local_dir = tmp_path / "skills" / "my-local-skill"
    local_dir.mkdir(parents=True)
    (local_dir / "SKILL.md").write_text(
        _skill_md("my-local-skill", "local:my-local-skill", "【技能：本地包】本地指令正文。"),
        encoding="utf-8",
    )
    # 非法包（无正文）不注册、不报错
    bad_dir = tmp_path / "skills" / "bad-empty"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_text("---\nname: bad-empty\n---\n", encoding="utf-8")

    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    by_name = {m["name"]: m for m in mine}
    assert by_name["sql-helper"]["source"] == "skillhub"
    assert by_name["sql-helper"]["path"] == "skills/sql-helper/"
    local = by_name["my-local-skill"]
    assert local["source"] == "local"
    assert local["id"] == 0  # 只读占位：开关/卸载禁用
    assert local["path"] == "skills/my-local-skill/"
    assert "bad-empty" not in by_name

    # 本地包只读：开关/卸载 → 404；目录不被误删
    resp = await client.put("/skills/0/enabled", json={"enabled": False}, headers=headers)
    assert resp.status_code == 404
    resp = await client.delete("/skills/0", headers=headers)
    assert resp.status_code == 404
    assert (local_dir / "SKILL.md").is_file()


async def test_injection_reads_from_disk(client, monkeypatch):
    """对话注入以盘为准：改写 SKILL.md 后注入新正文（DB 冗余不改变结果）。"""
    headers = await _chat_user(client, "diskinject")
    skill = (
        await client.post(
            "/skills/install", json={"skillhub_id": "mock-weekly-report"}, headers=headers
        )
    ).json()
    assert skill["path"] == "skills/weekly-report/"

    # 手动改写库中正文（模拟库是真相源）
    skill_md = skill_library.library_dir() / "weekly-report" / "SKILL.md"
    skill_md.write_text(
        _skill_md("weekly-report", "skillhub:mock-weekly-report", "【技能：周报助手】改写后的磁盘正文。"),
        encoding="utf-8",
    )

    captured: dict = {}

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)
    system = captured["messages"][0]["content"]
    assert "改写后的磁盘正文" in system
    assert "【技能：周报助手】" in system


async def test_uninstall_removes_record_and_directory(client):
    """卸载 → DB 记录删除 + skills/<slug>/ 目录删除。"""
    headers = await _chat_user(client, "libuninstall")
    skill = (
        await client.post(
            "/skills/install", json={"skillhub_id": "mock-code-review"}, headers=headers
        )
    ).json()
    skill_dir = skill_library.library_dir() / "code-review"
    assert (skill_dir / "SKILL.md").is_file()

    resp = await client.delete(f"/skills/{skill['id']}", headers=headers)
    assert resp.status_code == 200
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert mine == []
    assert not skill_dir.exists()


async def test_legacy_db_row_falls_back_to_stored_prompt(client, monkeypatch):
    """旧数据兼容（下版本可删）：name=展示名、无目录 → 回退读 DB prompt 注入。"""
    headers = await _chat_user(client, "legacyuser")
    user_id = 0
    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models.user import User

        row = (
            await db.execute(select(User).where(User.username == "legacyuser"))
        ).scalar_one()
        user_id = row.id
    async with SessionLocal() as db:
        db.add(
            UserSkill(
                user_id=user_id,
                app_id="chat",
                skillhub_id="mock-old-skill",
                name="旧技能",  # 展示名 ≠ slug：旧数据特征
                prompt="【技能：旧技能】升级前安装的存量 prompt。",
                enabled=True,
            )
        )
        await db.commit()

    captured: dict = {}

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)
    assert "升级前安装的存量 prompt" in captured["messages"][0]["content"]


async def test_manual_deleted_directory_auto_cleans_db_row(client):
    """文件夹库时代记录（name=slug）目录被手动删除 → 自动清理 DB 记录。"""
    headers = await _chat_user(client, "orphanuser")
    skill = (
        await client.post(
            "/skills/install", json={"skillhub_id": "mock-meeting-notes"}, headers=headers
        )
    ).json()
    assert skill["name"] == "meeting-notes"  # name=slug：文件夹库时代标记

    # 模拟手动删除目录
    import shutil

    shutil.rmtree(skill_library.library_dir() / "meeting-notes")

    # list_mine 触发自动清理
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert mine == []
    async with SessionLocal() as db:
        from sqlalchemy import select

        row = (
            await db.execute(
                select(UserSkill).where(UserSkill.id == skill["id"])
            )
        ).scalar_one_or_none()
        assert row is None


async def test_slug_sanitize_and_parse_roundtrip():
    """slug 清洗与 frontmatter 解析的纯函数行为。"""
    assert skill_library.sanitize_slug("Mock Translation Polish!") == "mock-translation-polish"
    assert skill_library.sanitize_slug("---a__b---") == "a-b"
    assert skill_library.sanitize_slug("!!!") == ""

    md = "---\r\nname: x\r\ndescription: 'd'\r\nsource: skillhub:s\r\nversion: 1\r\n---\r\n\r\nbody 正文\r\n"
    parsed = skill_library.parse_skill_md(md)
    assert parsed["name"] == "x"
    assert parsed["description"] == "d"
    assert parsed["source"] == "skillhub:s"
    assert parsed["version"] == "1"
    assert parsed["body"] == "body 正文"

    # 无 frontmatter：四键空、正文为全文
    parsed = skill_library.parse_skill_md("纯正文")
    assert parsed["body"] == "纯正文"
    assert parsed["name"] == ""


def test_env_override_priority(monkeypatch, tmp_path):
    """库目录解析：SKILL_LIBRARY_DIR > settings > 默认项目根 skills/。"""
    target = tmp_path / "custom-lib"
    monkeypatch.setenv("SKILL_LIBRARY_DIR", str(target))
    assert skill_library.library_dir() == target

    monkeypatch.delenv("SKILL_LIBRARY_DIR")
    from app.config import Settings

    monkeypatch.setattr(
        "app.services.skill_library.settings", Settings(skill_library_dir=str(target))
    )
    assert skill_library.library_dir() == target
