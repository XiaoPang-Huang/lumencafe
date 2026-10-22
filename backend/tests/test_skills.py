"""SkillHub 代理 + skill 生命周期 + 注入测试（增量架构 §3.6）。

- catalog：Mock provider 列表 + installed 标记 + 搜索分页；
- install：成功 201、重复 409、平台不存在 404；
- mine/enabled/uninstall：列表、开关（关闭即停止注入）、卸载；
- 注入：POST /chat 组装 system 时内置常量在前、已启用 skill 片段在后（用户不可改写）。
- 文件夹库：install 落盘 skills/<slug>/SKILL.md（fixture 重定向 SKILL_LIBRARY_DIR
  到临时目录，避免测试污染仓库 skills/）。
"""

import pytest

from app.services import llm_gateway
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

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0):
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

    async def spy_stream(cfg, messages, thinking=None, timeout=120.0):
        captured["messages"] = messages
        yield llm_gateway.StreamChunk(delta="ok")

    monkeypatch.setattr(llm_gateway, "chat_stream", spy_stream)
    await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)
    assert captured["messages"][0]["content"] == "你是一个乐于助人的 AI 助手"  # 无 skill 片段
