"""SkillHub 代理 + skill 生命周期 + 注入 + 用户上传测试（增量架构 §3.6）。

- catalog：Mock provider 列表 + installed 标记 + 搜索分页；
- install：成功 201、重复 409、平台不存在 404；
- upload：上传 SKILL.md 成功 201（落盘 source=local-upload + 落库）、
  非 md/超 64KB/缺 frontmatter/缺 name/缺 description/重名 409、上传后注入生效；
- mine/enabled/uninstall：列表、开关（关闭即停止注入）、卸载；
- 注入：POST /chat 组装 system 时内置常量在前、已启用 skill 片段在后（用户不可改写）。
- 文件夹库：install 落盘 skills/<slug>/SKILL.md（fixture 重定向 SKILL_LIBRARY_DIR
  到临时目录，避免测试污染仓库 skills/）。
"""

import pytest

from app.services import llm_gateway, skill_library
from tests.conftest import login


@pytest.fixture(autouse=True)
def _skill_library_tmp(tmp_path, monkeypatch):
    """全部 skill 测试走临时技能库（环境变量覆盖，skill_library 每次调用时读取）。"""
    monkeypatch.setenv("SKILL_LIBRARY_DIR", str(tmp_path / "skills"))


async def _chat_user(client, username="skiller"):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    return await login(client, username, "pass-123")


def _sse_events(body: str) -> list[dict]:
    import json

    events = []
    for block in body.strip().split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            events.append({"done": True})
            continue
        events.append(json.loads(data))
    return events


async def test_skill_catalog_and_install_flow(client):
    headers = await _chat_user(client)
    catalog = (await client.get("/skills/catalog", headers=headers)).json()
    assert catalog["total"] >= 4  # Mock 内置 5 个演示 skill
    assert all("installed" in i for i in catalog["items"])
    target = catalog["items"][0]

    # 搜索过滤
    searched = (await client.get(f"/skills/catalog?q={target['name']}", headers=headers)).json()
    assert searched["total"] >= 1
    assert all(target["name"] in i["name"] or target["name"] in i["description"] for i in searched["items"])

    # 安装 → mine 可见 → catalog 标 installed
    resp = await client.post("/skills/install", json={"skillhub_id": target["skillhub_id"]}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["enabled"] is True
    assert "prompt" not in resp.json()  # prompt 不回显（N-增5）

    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert len(mine) == 1 and mine[0]["skillhub_id"] == target["skillhub_id"]

    catalog2 = (await client.get("/skills/catalog", headers=headers)).json()
    assert next(i for i in catalog2["items"] if i["skillhub_id"] == target["skillhub_id"])["installed"] is True

    # 重复安装 → 409；平台不存在 → 404
    resp = await client.post("/skills/install", json={"skillhub_id": target["skillhub_id"]}, headers=headers)
    assert resp.status_code == 409
    resp = await client.post("/skills/install", json={"skillhub_id": "no-such-skill"}, headers=headers)
    assert resp.status_code == 404


async def test_skill_toggle_and_uninstall(client):
    headers = await _chat_user(client, "skiller2")
    catalog = (await client.get("/skills/catalog", headers=headers)).json()
    sid = catalog["items"][0]["skillhub_id"]
    skill = (await client.post("/skills/install", json={"skillhub_id": sid}, headers=headers)).json()

    # 关闭 → mine 状态同步
    resp = await client.put(f"/skills/{skill['id']}/enabled", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert mine[0]["enabled"] is False

    # 他人不可操作（行级隔离）：换一个用户开关同一 id → 404
    other = await _chat_user(client, "skiller3")
    resp = await client.put(f"/skills/{skill['id']}/enabled", json={"enabled": True}, headers=other)
    assert resp.status_code == 404

    # 卸载 → mine 为空
    resp = await client.delete(f"/skills/{skill['id']}", headers=headers)
    assert resp.status_code == 200
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert mine == []


async def test_skill_prompt_injection_into_system(client, monkeypatch):
    """P1-4 ④：开启的 skill prompt 注入 system（内置常量在前、片段在后）。"""
    headers = await _chat_user(client, "injector")
    catalog = (await client.get("/skills/catalog", headers=headers)).json()
    items = catalog["items"][:2]
    for it in items:
        await client.post("/skills/install", json={"skillhub_id": it["skillhub_id"]}, headers=headers)

    captured: dict = {}

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0, usage_out=None):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)

    system = captured["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("你是一个乐于助人的 AI 助手")  # 内置常量在前（Q14）
    for it in items:
        assert it["name"] in system["content"]  # skill 片段在后（按 installed_at 升序）
    # 两个 skill 片段按 installed_at 升序拼接在后
    prompts = [p for p in system["content"].split("\n\n") if p.startswith("【技能：")]
    assert len(prompts) == 2


async def test_skill_disabled_stops_injection(client, monkeypatch):
    headers = await _chat_user(client, "injector2")
    catalog = (await client.get("/skills/catalog", headers=headers)).json()
    it = catalog["items"][0]
    skill = (await client.post("/skills/install", json={"skillhub_id": it["skillhub_id"]}, headers=headers)).json()
    await client.put(f"/skills/{skill['id']}/enabled", json={"enabled": False}, headers=headers)

    captured: dict = {}

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0, usage_out=None):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)
    assert captured["messages"][0]["content"] == "你是一个乐于助人的 AI 助手"  # 无 skill 片段


# ================= 用户上传自制 SKILL.md（POST /skills/upload） =================


def _upload_md(name: str = "My Meeting Notes", description: str = "整理会议结论与待办") -> bytes:
    """合法上传用 SKILL.md 字节内容（name 含大写/空格，验证 slug 清洗）。"""
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "version: 1.0.0\n"
        "---\n\n"
        "【技能：会议纪要】当用户提供会议内容时：输出「结论 / 待办 / 待定问题」三部分。\n"
    ).encode()


async def _upload(client, headers, content: bytes, filename: str = "notes.md"):
    return await client.post(
        "/skills/upload",
        files={"file": (filename, content, "text/markdown")},
        headers=headers,
    )


async def test_skill_upload_success_writes_library_and_db(client):
    """上传成功 201：skills/<slug>/SKILL.md 落盘（source=local-upload）+ 落库回显。"""
    headers = await _chat_user(client, "uploader")
    resp = await _upload(client, headers, _upload_md())
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "my-meeting-notes"  # slug 清洗：My Meeting Notes → my-meeting-notes
    assert body["source"] == "local-upload"
    assert body["path"] == f"skills/{body['name']}/"
    assert body["enabled"] is True
    assert "prompt" not in body  # prompt 不回显（N-增5）

    # 磁盘真相源：source 键补写为 local-upload
    skill_md = skill_library.library_dir() / body["name"] / "SKILL.md"
    assert skill_md.is_file()
    parsed = skill_library.parse_skill_md(skill_md.read_text(encoding="utf-8"))
    assert parsed["source"] == "local-upload"
    assert parsed["description"]
    assert parsed["body"].startswith("【技能：")

    # mine 可见（来源=本地上传，可开关/卸载，非只读）
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    row = next(m for m in mine if m["id"] == body["id"])
    assert row["source"] == "local-upload"
    assert row["path"] == body["path"]

    # 开关 → mine 状态同步；卸载 → 记录与目录同删
    resp = await client.put(f"/skills/{body['id']}/enabled", json={"enabled": False}, headers=headers)
    assert resp.status_code == 200
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert next(m for m in mine if m["id"] == body["id"])["enabled"] is False

    resp = await client.delete(f"/skills/{body['id']}", headers=headers)
    assert resp.status_code == 200
    assert not skill_md.parent.exists()  # 目录已删
    mine = (await client.get("/skills/mine?app_id=chat", headers=headers)).json()
    assert mine == []


async def test_skill_upload_keeps_existing_source_key(client):
    """上传文件已带 source 键 → 落盘时替换为 local-upload（不保留原值）。"""
    headers = await _chat_user(client, "uploader-src")
    content = (
        "---\n"
        "name: my-own-skill\n"
        "description: 自带 source 的技能\n"
        "source: somewhere-else\n"
        "---\n\n"
        "【技能：我的】正文指令。\n"
    ).encode()
    resp = await _upload(client, headers, content)
    assert resp.status_code == 201
    assert resp.json()["name"] == "my-own-skill"
    parsed = skill_library.parse_skill_md(
        (skill_library.library_dir() / "my-own-skill" / "SKILL.md").read_text(encoding="utf-8")
    )
    assert parsed["source"] == "local-upload"


async def test_skill_upload_validation_errors(client):
    """非 md / 超 64KB / 缺 frontmatter / 缺 name / 缺 description / 无正文 → 422 不落盘。"""
    headers = await _chat_user(client, "uploader-bad")

    cases = [
        (b"plain text", "notes.txt", 422),  # 非 .md
        (_upload_md() + b"x" * (64 * 1024), "big.md", 422),  # >64KB
        ("纯正文没有元信息\n".encode(), "nofm.md", 422),  # 缺 frontmatter
        (
            "---\nname: no-desc\ndescription: \n---\n\n正文。\n".encode(),
            "nodesc.md",
            422,
        ),  # 缺 description
        (
            "---\ndescription: 只有描述\n---\n\n正文。\n".encode(),
            "noname.md",
            422,
        ),  # 缺 name
        (
            "---\nname: no-body\ndescription: 无正文\n---\n\n".encode(),
            "nobody.md",
            422,
        ),  # 无指令正文
    ]
    for content, filename, status in cases:
        resp = await _upload(client, headers, content, filename)
        assert resp.status_code == status, filename
        assert resp.json()["detail"]
    # 全部失败：库里什么都没有
    assert skill_library.scan_library() == []

    # 重复上传同名 → 409
    resp = await _upload(client, headers, _upload_md("Dup Skill", "重复技能"))
    assert resp.status_code == 201
    resp = await _upload(client, headers, _upload_md("Dup Skill", "换个描述"))
    assert resp.status_code == 409
    assert resp.json()["detail"]


async def test_skill_upload_injects_into_system(client, monkeypatch):
    """上传后 enabled 默认开 → 注入 system（内置常量在前、上传片段在后）。"""
    headers = await _chat_user(client, "uploader-inj")
    resp = await _upload(
        client,
        headers,
        _upload_md("Meeting Notes X", "会议整理注入验证"),
    )
    assert resp.status_code == 201
    slug = resp.json()["name"]
    assert (skill_library.library_dir() / slug / "SKILL.md").is_file()

    captured: dict = {}

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0, usage_out=None):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)

    system = captured["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith("你是一个乐于助人的 AI 助手")  # 内置常量在前（Q14）
    assert "【技能：会议纪要】" in system["content"]  # 上传片段注入在后
