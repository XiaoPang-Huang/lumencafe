"""对外模型网关测试（架构设计 §4.9/§5.6/Q13/Q17）。"""

from app.services import llm_gateway
from tests.conftest import login


async def _mk_token(client, admin, name="gw-test", scope=None):
    payload = {"name": name}
    if scope is not None:
        payload["model_scope"] = scope
    resp = await client.post("/admin/models/gateway-tokens", json=payload, headers=admin)
    assert resp.status_code == 201
    return resp.json()["token"]


def _mk_headers(token):
    return {"Authorization": f"Bearer {token}"}


_MSGS = [{"role": "user", "content": "把这段话总结成一句话"}]


async def test_gw_auth_errors(client):
    admin = await login(client)
    await _mk_token(client, admin)  # 保证有活跃令牌（否则先 503）

    # 缺头 / 错令牌 → 401
    resp = await client.post("/gw/v1/chat/completions", json={"model": "default", "messages": _MSGS})
    assert resp.status_code == 401
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "default", "messages": _MSGS},
        headers={"Authorization": "Bearer sk-wrong"},
    )
    assert resp.status_code == 401

    # 吊销后 → 401
    token = await _mk_token(client, admin, name="to-revoke")
    tid = next(
        t["id"]
        for t in (await client.get("/admin/models/gateway-tokens", headers=admin)).json()
        if t["name"] == "to-revoke"
    )
    await client.delete(f"/admin/models/gateway-tokens/{tid}", headers=admin)
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "default", "messages": _MSGS},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 401


async def test_gw_non_stream_default_alias(client):
    admin = await login(client)
    token = await _mk_token(client, admin)
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "default", "messages": _MSGS},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "mock"  # 种子 mock 默认路由
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["finish_reason"] == "stop"


async def test_gw_stream_sse(client):
    admin = await login(client)
    token = await _mk_token(client, admin)
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "mock", "messages": _MSGS, "stream": True},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert 'data: {"' in body
    assert "data: [DONE]" in body
    assert '"object": "chat.completion.chunk"' in body


async def test_gw_model_resolution_and_scope(client):
    admin = await login(client)
    token = await _mk_token(client, admin, scope=["mock"])

    # 白名单内模型 OK
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "mock", "messages": _MSGS},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 200

    # 白名单外（default 别名解析出的模型不在范围）→ 403
    restricted = await _mk_token(client, admin, name="restricted", scope=["not-mock"])
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "default", "messages": _MSGS},
        headers=_mk_headers(restricted),
    )
    assert resp.status_code == 403

    # 不存在的模型 → 404
    full = await _mk_token(client, admin, name="full-scope")
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "no-such-model", "messages": _MSGS},
        headers=_mk_headers(full),
    )
    assert resp.status_code == 404


async def test_gw_zero_key_principle(client):
    """任何响应不得带出真实 provider Key。"""
    admin = await login(client)
    await client.post(
        "/admin/models/providers",
        json={
            "name": "DeepSeek",
            "vendor": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-real-key-topsecret",
        },
        headers=admin,
    )
    token = await _mk_token(client, admin)
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "deepseek-chat", "messages": _MSGS},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 404  # 未给该 provider 配模型
    assert "sk-real-key-topsecret" not in resp.text
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "default", "messages": _MSGS},
        headers=_mk_headers(token),
    )
    assert "sk-real-key-topsecret" not in resp.text


async def test_gw_upstream_failure_502(client, monkeypatch):
    admin = await login(client)
    token = await _mk_token(client, admin)

    async def boom(cfg, messages):
        raise llm_gateway.UpstreamError("boom")
        yield  # pragma: no cover  # 使其成为异步生成器

    monkeypatch.setattr(llm_gateway, "chat_stream", boom)
    resp = await client.post(
        "/gw/v1/chat/completions",
        json={"model": "mock", "messages": _MSGS, "stream": True},
        headers=_mk_headers(token),
    )
    assert resp.status_code == 200  # SSE 流内报错：error 事件 + [DONE]
    assert '"error"' in resp.text
    assert "data: [DONE]" in resp.text
