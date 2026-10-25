"""思考双流 + 档位映射 + 润色测试（增量架构 §3.3/§3.4/§3.5）。

- build_thinking_params：deepseek/glm/kimi 两态、openai/custom reasoning_effort、
  qwen enable_thinking/budget、mock 空；
- MetaReasoning：default_level 必须在 levels 内（levels 非空时）；
- mock 双流：SSE 产出 reasoning_delta 事件序列 + reasoning 落库 + mock 忽略档位；
- 白名单 400：thinking_level 不在目标模型 meta.reasoning.levels 内；
- polish：mock 占位润色 200、上游失败 502、限流 429。
"""

import pytest
from pydantic import ValidationError

from app.schemas.llm import MetaReasoning
from app.services import chat_service, llm_gateway, route_service
from app.services.llm_gateway import ClientCfg
from app.services.route_service import ResolvedRoute
from tests.conftest import login

# ── 厂商映射表（纯函数）───────────────────────────────────


def test_build_thinking_params_two_state_vendors():
    for vendor in ("deepseek", "glm", "kimi"):
        assert llm_gateway.build_thinking_params(vendor, "off") == {
            "thinking": {"type": "disabled"}
        }
        assert llm_gateway.build_thinking_params(vendor, "high") == {
            "thinking": {"type": "enabled"}
        }
        assert llm_gateway.build_thinking_params(vendor, "max") == {
            "thinking": {"type": "enabled"}
        }


def test_build_thinking_params_openai_compatible():
    assert llm_gateway.build_thinking_params("openai", "xhigh") == {"reasoning_effort": "xhigh"}
    assert llm_gateway.build_thinking_params("custom", "medium") == {
        "reasoning_effort": "medium"
    }
    # 未知厂商兜底 OpenAI 兼容系
    assert llm_gateway.build_thinking_params("", "high") == {"reasoning_effort": "high"}


def test_build_thinking_params_qwen():
    assert llm_gateway.build_thinking_params("qwen", "off") == {"enable_thinking": False}
    assert llm_gateway.build_thinking_params("qwen", "32768") == {
        "enable_thinking": True,
        "thinking_budget": 32768,
    }
    assert llm_gateway.build_thinking_params("qwen", "on") == {"enable_thinking": True}


def test_build_thinking_params_mock_and_none():
    assert llm_gateway.build_thinking_params("mock", "high") == {}
    assert llm_gateway.build_thinking_params("deepseek", None) == {}
    assert llm_gateway.build_thinking_params("", "") == {}


# ── MetaReasoning 结构校验 ────────────────────────────────


def test_meta_reasoning_default_level_must_be_in_levels():
    with pytest.raises(ValidationError):
        MetaReasoning(
            enabled=True,
            levels=[{"value": "high", "label": "高"}],
            default_level="nope",
        )
    ok = MetaReasoning(
        enabled=True,
        levels=[{"value": "high", "label": "高"}, {"value": "max", "label": "超高"}],
        default_level="max",
    )
    assert ok.default_level == "max"


def test_meta_reasoning_empty_levels_allows_switch_only():
    # levels 空 = 官方仅开关（R5 边界①）；default_level 不做集合校验
    switch = MetaReasoning(enabled=True, levels=[], default_level="on")
    assert switch.enabled and switch.levels == []


# ── mock 双流 SSE + reasoning 落库 + mock 忽略档位 ──────────


async def _chat_user(client, username="thinker"):
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


async def test_chat_mock_dual_stream_and_reasoning_persisted(client):
    headers = await _chat_user(client)
    resp = await client.post(
        "/chat", json={"app_id": "chat", "message": "你好"}, headers=headers
    )
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    assert events[-1] == {"done": True}

    reasoning = [e["reasoning_delta"] for e in events if "reasoning_delta" in e]
    deltas = [e["delta"] for e in events if "delta" in e]
    assert reasoning and "".join(reasoning)  # mock 产出思维流（R3）
    assert deltas and "".join(deltas)

    # 思维链随 assistant 消息落库（P0-4 ③）
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=headers
        )
    ).json()
    assistant = history["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["reasoning"] == "".join(reasoning)


async def test_chat_mock_ignores_thinking_level(client):
    """mock vendor 忽略 thinking_level（§3.4 规则⑤）：不报错、不快照。"""
    headers = await _chat_user(client)
    resp = await client.post(
        "/chat",
        json={"app_id": "chat", "message": "hi", "thinking_level": "high"},
        headers=headers,
    )
    assert resp.status_code == 200
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    assert convs[0]["thinking_level"] is None


# ── 白名单校验（不在 levels → 400；命中 → 快照）─────────────


async def _make_reasoning_model(client):
    admin = await login(client)
    resp = await client.post(
        "/admin/models/providers",
        json={
            "name": "自定义渠道",
            "vendor": "custom",
            "base_url": "http://127.0.0.1:9",  # 不可达即可，避免真实外呼
            "api_key": "sk-test",
        },
        headers=admin,
    )
    pid = resp.json()["id"]
    resp = await client.post(
        f"/admin/models/providers/{pid}/models",
        json={
            "name": "reasoner-v1",
            "meta": {
                "context": "128K",
                "vision": False,
                "files": False,
                "reasoning": {
                    "enabled": True,
                    "levels": [{"value": "high", "label": "高"}, {"value": "max", "label": "超高"}],
                    "default_level": "high",
                },
            },
        },
        headers=admin,
    )
    return resp.json()["id"]


async def test_chat_thinking_level_whitelist(client):
    model_id = await _make_reasoning_model(client)
    headers = await _chat_user(client, "leveluser")

    # 不在白名单 → 400
    resp = await client.post(
        "/chat",
        json={
            "app_id": "chat",
            "message": "hi",
            "model_id": model_id,
            "thinking_level": "nope",
        },
        headers=headers,
    )
    assert resp.status_code == 400

    # 命中白名单 → 200（上游不可达，走 error 事件；校验与快照已在返回前完成）
    resp = await client.post(
        "/chat",
        json={
            "app_id": "chat",
            "message": "hi",
            "model_id": model_id,
            "thinking_level": "high",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    assert any("error" in e for e in events)  # 127.0.0.1:9 连接拒绝 → error 事件
    assert events[-1] == {"done": True}

    # 档位快照到会话（P0-2 ⑤，与 model_id 同模式）
    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    assert convs[0]["thinking_level"] == "high"
    assert convs[0]["model_id"] == model_id


async def test_chat_model_without_reasoning_ignores_level(client):
    """meta 无 reasoning 键 → 忽略 thinking_level（§3.4 规则②，不报错）。"""
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = providers[0]["id"]
    resp = await client.post(
        f"/admin/models/providers/{pid}/models",
        json={"name": "plain-model", "meta": {"context": "8K"}},
        headers=admin,
    )
    model_id = resp.json()["id"]
    headers = await _chat_user(client, "plainuser")
    resp = await client.post(
        "/chat",
        json={
            "app_id": "chat",
            "message": "hi",
            "model_id": model_id,
            "thinking_level": "anything",
        },
        headers=headers,
    )
    assert resp.status_code == 200


# ── 模型池 reasoning 字段 ─────────────────────────────────


async def test_chat_models_expose_reasoning(client):
    model_id = await _make_reasoning_model(client)
    headers = await _chat_user(client, "pooluser")
    models = (await client.get("/chat/models", headers=headers)).json()
    reasoner = next(m for m in models if m["id"] == model_id)
    assert reasoner["reasoning"]["enabled"] is True
    assert reasoner["reasoning"]["default_level"] == "high"
    assert {l["value"] for l in reasoner["reasoning"]["levels"]} == {"high", "max"}
    # mock 模型：种子带两态档位
    mock_model = next(m for m in models if m["name"] == "mock")
    assert mock_model["reasoning"]["enabled"] is True


# ── 管理端 meta.reasoning 读写校验 ─────────────────────────


async def test_admin_model_meta_reasoning_validation(client):
    model_id = await _make_reasoning_model(client)
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = next(p["id"] for p in providers if p["vendor"] == "custom")

    # default_level 不在 levels → 400（结构非法不落库）
    resp = await client.put(
        f"/admin/models/providers/{pid}/models/{model_id}",
        json={
            "meta": {
                "reasoning": {
                    "enabled": True,
                    "levels": [{"value": "high", "label": "高"}],
                    "default_level": "max",
                }
            }
        },
        headers=admin,
    )
    assert resp.status_code == 400

    # 合法结构 → 200 且 tools/custom_protocol 预留位落库（R4）
    resp = await client.put(
        f"/admin/models/providers/{pid}/models/{model_id}",
        json={"meta": {"reasoning": {"enabled": True, "levels": [], "default_level": None},
                       "tools": True, "custom_protocol": True}},
        headers=admin,
    )
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["reasoning"]["enabled"] is True
    assert meta["tools"] is True and meta["custom_protocol"] is True
    # 顶层键合并语义：context 不回退
    assert meta["context"] == "128K"


# ── polish（P1-2）────────────────────────────────────────


async def test_polish_mock_success_and_validation(client):
    headers = await _chat_user(client, "polisher")
    resp = await client.post("/chat/polish", json={"text": "帮我把这句话写好看"}, headers=headers)
    assert resp.status_code == 200
    assert "polished" in resp.json()
    assert "mock 润色占位" in resp.json()["polished"]

    resp = await client.post("/chat/polish", json={"text": ""}, headers=headers)
    assert resp.status_code == 422
    resp = await client.post("/chat/polish", json={"text": "x" * 4001}, headers=headers)
    assert resp.status_code == 422


async def test_polish_upstream_failure_502(client, monkeypatch):
    route = ResolvedRoute(
        provider_id=1,
        provider_name="t",
        vendor="openai",
        model_id=1,
        model_name="m",
        cfg=ClientCfg(base_url="http://127.0.0.1:9", api_key="k", model="m", vendor="openai"),
    )

    async def fake_plan(db, app_key):
        return route_service.RoutePlan(candidates=(route,), source="direct")

    monkeypatch.setattr(route_service, "resolve_for", fake_plan)
    headers = await _chat_user(client, "polish502")
    resp = await client.post("/chat/polish", json={"text": "润色我"}, headers=headers)
    assert resp.status_code == 502


async def test_polish_rate_limit_429(client):
    headers = await _chat_user(client, "polish429")
    last = None
    for _ in range(11):
        last = await client.post("/chat/polish", json={"text": "hi"}, headers=headers)
    assert last.status_code == 429


# ── 思维链 64KB 截断 ──────────────────────────────────────


def test_reasoning_truncation_limit():
    assert chat_service.REASONING_MAX_CHARS == 64 * 1024


async def test_persist_exchange_truncates_reasoning(client):
    headers = await _chat_user(client, "truncuser")
    big = "思" * (70 * 1024)

    async def fat_stream(cfg, messages, thinking=None, timeout=120.0, usage_out=None):
        yield llm_gateway.StreamChunk(reasoning_delta=big)
        yield llm_gateway.StreamChunk(delta="回答")

    import app.services.chat_service as cs

    orig = cs.llm_gateway.chat_stream
    cs.llm_gateway.chat_stream = fat_stream
    try:
        resp = await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=headers)
    finally:
        cs.llm_gateway.chat_stream = orig
    assert resp.status_code == 200

    convs = (await client.get("/chat/conversations?app_id=chat", headers=headers)).json()
    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=headers
        )
    ).json()
    reasoning = history["messages"][-1]["reasoning"]
    assert reasoning is not None
    assert len(reasoning) <= chat_service.REASONING_MAX_CHARS
