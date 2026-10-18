"""通用对话测试（PRD §4.6，架构设计 §5.2/Q14/Q15）。

种子 mock 默认路由 → /chat 走 mock 流式文案，不联网即可覆盖完整链路。
"""

from app.services import llm_gateway, route_service
from tests.conftest import login


async def _chat_user(client, username="chatter"):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    return await login(client, username, "pass-123")


def _sse_events(body: str) -> list[dict]:
    """解析 SSE 文本为事件列表（忽略 [DONE]）。"""
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


async def test_chat_sse_full_flow(client):
    headers = await _chat_user(client)
    resp = await client.post(
        "/chat", json={"app_id": "chat", "message": "你好，介绍一下你自己"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(resp.text)
    assert events[-1] == {"done": True}
    deltas = [e["delta"] for e in events if "delta" in e]
    assert "".join(deltas)  # mock 回复非空

    # 落库校验：会话 + 消息 + 标题（首条消息截取 16 字）
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    assert len(convs) == 1
    assert convs[0]["title"] == "你好，介绍一下你自己"[:16]

    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=headers
        )
    ).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["content"] == "".join(deltas)


async def test_chat_reuses_latest_conversation(client):
    headers = await _chat_user(client)
    await client.post("/chat", json={"app_id": "chat", "message": "第一轮"}, headers=headers)
    await client.post("/chat", json={"app_id": "chat", "message": "第二轮"}, headers=headers)

    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    assert len(convs) == 1  # 未指定 conversation_id → 复用最近会话
    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=headers
        )
    ).json()
    assert len(history["messages"]) == 4  # 两对问答


async def test_chat_midstream_failure_not_persisted(client, monkeypatch):
    headers = await _chat_user(client)

    async def broken_stream(cfg, messages):
        yield "半截"
        raise llm_gateway.UpstreamError("boom")

    monkeypatch.setattr(llm_gateway, "chat_stream", broken_stream)
    resp = await client.post(
        "/chat", json={"app_id": "chat", "message": "会失败的请求"}, headers=headers
    )
    events = _sse_events(resp.text)
    assert any("error" in e for e in events)
    assert events[-1] == {"done": True}

    # 半截回复不落库
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=headers
        )
    ).json()
    assert history["messages"] == []


async def test_chat_no_default_route_503(client, monkeypatch):
    async def no_route(db):
        return None

    monkeypatch.setattr(route_service, "resolve_default", no_route)
    headers = await _chat_user(client)
    resp = await client.post(
        "/chat", json={"app_id": "chat", "message": "hi"}, headers=headers
    )
    assert resp.status_code == 503


async def test_chat_permission_and_ownership(client):
    admin = await login(client)
    # 建一个无 app:chat 权限的角色并绑给用户
    resp = await client.post("/admin/roles", json={"name": "noper"}, headers=admin)
    rid = resp.json()["id"]
    await client.put(f"/admin/roles/{rid}/permissions", json={"permissions": []}, headers=admin)
    await client.post(
        "/admin/users",
        json={"username": "noper1", "password": "pass-123", "role_ids": [rid]},
        headers=admin,
    )
    noper = await login(client, "noper1", "pass-123")
    resp = await client.post(
        "/chat", json={"app_id": "chat", "message": "hi"}, headers=noper
    )
    assert resp.status_code == 403

    # 他人会话 404
    headers = await _chat_user(client, "owner1")
    convs = (
        await client.post(
            "/chat/conversations", json={"app_id": "chat"}, headers=headers
        )
    ).json()
    stranger = await _chat_user(client, "stranger1")
    resp = await client.get(
        f"/chat/history?app_id=chat&conversation_id={convs['id']}", headers=stranger
    )
    assert resp.status_code == 404


async def test_chat_models_pool(client):
    headers = await _chat_user(client)
    models = (await client.get("/chat/models", headers=headers)).json()
    assert len(models) >= 1
    mock_model = next(m for m in models if m["name"] == "mock")
    assert mock_model["is_default"] is True
    assert mock_model["provider"]  # Provider 条目名
    assert "vision" in mock_model["capabilities"] and "files" in mock_model["capabilities"]


async def test_conversation_crud_and_clear_history(client):
    headers = await _chat_user(client)
    resp = await client.post(
        "/chat/conversations", json={"app_id": "chat", "title": "手动会话"}, headers=headers
    )
    assert resp.status_code == 201
    cid = resp.json()["id"]
    assert resp.json()["title"] == "手动会话"

    resp = await client.get("/chat/conversations?app_id=chat", headers=headers)
    assert any(c["id"] == cid for c in resp.json())

    # 清空历史（保留会话）
    await client.post("/chat", json={"app_id": "chat", "conversation_id": cid, "message": "x"}, headers=headers)
    resp = await client.delete(
        f"/chat/history?app_id=chat&conversation_id={cid}", headers=headers
    )
    assert resp.status_code == 200
    history = (
        await client.get(f"/chat/history?app_id=chat&conversation_id={cid}", headers=headers)
    ).json()
    assert history["messages"] == []

    # 删除会话
    resp = await client.delete(
        f"/chat/conversations/{cid}?app_id=chat", headers=headers
    )
    assert resp.status_code == 200
    resp = await client.get("/chat/conversations?app_id=chat", headers=headers)
    assert all(c["id"] != cid for c in resp.json())


async def test_chat_model_id_binding(client):
    """Q15：model_id 会话级绑定，缺省走默认路由。"""
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = providers[0]["id"]
    resp = await client.post(
        f"/admin/models/providers/{pid}/models",
        json={"name": "mock-v2", "meta": {"context": "8K", "vision": False, "files": False}},
        headers=admin,
    )
    model_id = resp.json()["id"]

    headers = await _chat_user(client, "binder")
    await client.post(
        "/chat",
        json={"app_id": "chat", "message": "用指定模型", "model_id": model_id},
        headers=headers,
    )
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    assert convs[0]["model_id"] == model_id

    # 模型池包含新模型（is_default=False）
    models = (await client.get("/chat/models", headers=headers)).json()
    assert any(m["id"] == model_id and m["is_default"] is False for m in models)
