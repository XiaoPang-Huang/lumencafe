"""步 3 网关路由升级测试（架构设计-增量 v2 B1/D2/D3，实施指令 §二.6）。

覆盖：指派解析（含未配置回落默认路由）、兜底切换、熔断触发/冷却/探测/恢复/
重启持久化、记账对账（费用=单价快照×token）、统计接口非 admin 403。
冒烟（验收 §四.3）：主模型注入失败 → 自动切备用 → 连挂摘出 → 冷却探测 →
恢复自动切回，走 /chat 真实 SSE 路径 + mock provider + monkeypatch。
"""
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.llm import LLMCallLog, ModelCircuitState
from app.services import circuit_service, llm_gateway, route_service
from tests.conftest import login

PRIMARY_MOCK_NAME = "mock"  # 种子默认路由模型名


# ── 基建 ────────────────────────────────────────────────
async def _mk_user(client, admin, username):
    resp = await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    return await login(client, username, "pass-123")


async def _mk_mock_model(client, admin, name):
    """建一个 mock 渠道 + 自定义模型（base_url 空 = 本地占位，不联网）。"""
    resp = await client.post(
        "/admin/models/providers",
        json={"name": f"{name} 渠道", "vendor": "mock", "base_url": "", "api_key": ""},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    resp = await client.post(
        f"/admin/models/providers/{pid}/models", json={"name": name}, headers=admin
    )
    assert resp.status_code == 201, resp.text
    return pid, resp.json()["id"]


async def _set_assignment(client, admin, app_key, primary_id, fallback_ids=None):
    resp = await client.put(
        f"/admin/models/assignments/{app_key}",
        json={
            "primary_model_id": primary_id,
            "fallback_chain": fallback_ids or [],
            "enabled": True,
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _default_model_id(client, admin):
    route = (await client.get("/admin/models/default-route", headers=admin)).json()
    return route["model"]["id"]


async def _log_count(**where):
    async with SessionLocal() as db:
        q = select(func.count(LLMCallLog.id))
        for k, v in where.items():
            q = q.where(getattr(LLMCallLog, k) == v)
        return int((await db.execute(q)).scalar_one())


def _fake_chat_once(fail_names, usage=None):
    """chat_once 替身：指定模型名注入 UpstreamError，其余返回记账 JSON。"""

    async def fake(cfg, messages, timeout=30.0, usage_out=None):
        if cfg.model in fail_names:
            raise llm_gateway.UpstreamError("injected failure")
        if usage_out is not None:
            usage_out.update(usage or {"input_tokens": 0, "output_tokens": 0})
        return json.dumps(
            {"amount": 1250, "type": "expense", "category_suggestion": "餐饮",
             "note": "fake", "date": "2026-10-25", "confidence": 0.99}
        )

    return fake


def _fake_chat_stream(fail_names, fail_after_first=False):
    """chat_stream 替身：fail_names 首帧即失败；fail_after_first = 首帧后断流。"""

    async def fake(cfg, messages, thinking=None, timeout=120.0, usage_out=None):
        if cfg.model in fail_names and not fail_after_first:
            raise llm_gateway.UpstreamError("injected failure")
        if usage_out is not None:
            usage_out.update({"input_tokens": 7, "output_tokens": 13})
        yield llm_gateway.StreamChunk(delta="你")
        if cfg.model in fail_names and fail_after_first:
            raise llm_gateway.UpstreamError("stream interrupted")
        yield llm_gateway.StreamChunk(delta="好")

    return fake


def _sse_events(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        events.append({"done": True} if data == "[DONE]" else json.loads(data))
    return events


# ── 指派解析 ────────────────────────────────────────────
async def test_assignments_seeded_and_resolve(client):
    admin = await login(client)
    resp = await client.get("/admin/models/assignments", headers=admin)
    assert resp.status_code == 200
    data = resp.json()
    keys = {a["app_key"] for a in data["assignments"]}
    assert keys == {"chat", "money_parse", "polish"}  # 种子三行（Q1 拍板）
    default_id = await _default_model_id(client, admin)
    for a in data["assignments"]:
        assert a["primary_model_id"] == default_id  # 主模型 = 当前默认路由
        assert a["fallback_chain"] == []
    assert any(m["name"] == PRIMARY_MOCK_NAME for m in data["model_pool"])

    # resolve_for：已配置 → 指派来源；未配置 app_key → 回落默认路由（兼容期不报错）
    async with SessionLocal() as db:
        plan = await route_service.resolve_for(db, "chat")
        assert plan is not None and plan.source == "assignment"
        assert plan.candidates[0].model_id == default_id
        plan2 = await route_service.resolve_for(db, "not_configured_app")
        assert plan2 is not None and plan2.source == "default"
        assert plan2.candidates[0].model_id == default_id


async def test_assignment_primary_disabled_falls_to_chain(client):
    """主模型停用 → 解析结果直接跳过它（备用链顶上）。"""
    admin = await login(client)
    _, backup_id = await _mk_mock_model(client, admin, "mock-b")
    primary_id = await _default_model_id(client, admin)
    await _set_assignment(client, admin, "money_parse", primary_id, [backup_id])
    # 停用主模型（providers 下 PUT enabled=false）
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    default_pid = next(p["id"] for p in providers if p["is_default"])
    await client.put(
        f"/admin/models/providers/{default_pid}/models/{primary_id}",
        json={"enabled": False},
        headers=admin,
    )
    async with SessionLocal() as db:
        plan = await route_service.resolve_for(db, "money_parse")
        assert plan is not None
        assert [c.model_id for c in plan.candidates] == [backup_id]


async def test_assignment_write_validation(client):
    admin = await login(client)
    pid, mid = await _mk_mock_model(client, admin, "mock-c")
    primary_id = await _default_model_id(client, admin)

    # 未知模型 → 400
    resp = await client.put(
        "/admin/models/assignments/chat",
        json={"primary_model_id": 999999, "fallback_chain": []},
        headers=admin,
    )
    assert resp.status_code == 400
    # 链内重复 → 400
    resp = await client.put(
        "/admin/models/assignments/chat",
        json={"primary_model_id": primary_id, "fallback_chain": [mid, mid]},
        headers=admin,
    )
    assert resp.status_code == 400
    # 停用模型 → 400
    await client.put(
        f"/admin/models/providers/{pid}/models/{mid}",
        json={"enabled": False},
        headers=admin,
    )
    resp = await client.put(
        "/admin/models/assignments/chat",
        json={"primary_model_id": mid, "fallback_chain": []},
        headers=admin,
    )
    assert resp.status_code == 400


# ── 兜底切换（首 token 前失败按序换模型）────────────────────
async def test_parse_falls_back_and_logs_both_attempts(client, monkeypatch):
    admin = await login(client)
    user = await _mk_user(client, admin, "payer")
    _, backup_id = await _mk_mock_model(client, admin, "mock-b")
    primary_id = await _default_model_id(client, admin)
    await _set_assignment(client, admin, "money_parse", primary_id, [backup_id])

    monkeypatch.setattr(
        llm_gateway, "chat_once", _fake_chat_once(fail_names={PRIMARY_MOCK_NAME})
    )
    resp = await client.post("/money/parse", json={"text": "午饭 12.5"}, headers=user)
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == 1250  # 备用模型应答

    # 两次调用尝试各记一条账：主模型失败 + 备用成功
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(LLMCallLog).where(LLMCallLog.app_key == "money_parse")
            )
        ).scalars().all()
    assert len(rows) == 2
    by_success = {r.success: r for r in rows}
    assert by_success[False].model_id == primary_id
    assert "injected failure" in (by_success[False].error or "")
    assert by_success[True].model_id == backup_id


async def test_chat_midstream_failure_no_switch(client, monkeypatch):
    """流式开始输出后不换模型：首帧后断流 → SSE 出 error，半截不落库。"""
    admin = await login(client)
    user = await _mk_user(client, admin, "midstream")
    primary_id = await _default_model_id(client, admin)
    await _set_assignment(client, admin, "chat", primary_id, [])
    monkeypatch.setattr(
        llm_gateway,
        "chat_stream",
        _fake_chat_stream(fail_names={PRIMARY_MOCK_NAME}, fail_after_first=True),
    )
    resp = await client.post("/chat", json={"app_id": "chat", "message": "hi"}, headers=user)
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    deltas = [e["delta"] for e in events if "delta" in e]
    assert deltas == ["你"]  # 首帧后断流，未换模型续写
    assert any("error" in e for e in events)
    assert events[-1] == {"done": True}
    # 断流记失败账（success=false），且半截回复不落库
    assert await _log_count(app_key="chat", success=False) == 1
    convs = (await client.get("/chat/conversations?app_id=chat", headers=user)).json()
    history = (
        await client.get(
            f"/chat/history?app_id=chat&conversation_id={convs[0]['id']}", headers=user
        )
    ).json()
    assert [m["role"] for m in history["messages"]] == []


# ── 熔断：单元（注入时钟）────────────────────────────────
async def test_circuit_breaker_lifecycle(client):
    _, mid = await _mk_mock_model(client, await login(client), "mock-cb")
    t0 = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    async with SessionLocal() as db:
        # 连挂 2 次：仍 closed
        for _ in range(2):
            await circuit_service.on_failure(db, mid, now=t0)
        row = (
            await db.execute(
                select(ModelCircuitState).where(ModelCircuitState.model_id == mid)
            )
        ).scalar_one()
        assert row.state == "closed" and row.consecutive_failures == 2
        assert await circuit_service.is_available(db, mid, now=t0)

        # 第 3 次：摘出（open），冷却 60s
        tripped = await circuit_service.on_failure(db, mid, now=t0)
        assert tripped
        row = (
            await db.execute(
                select(ModelCircuitState).where(ModelCircuitState.model_id == mid)
            )
        ).scalar_one()
        assert row.state == "open"
        assert row.next_probe_at == t0 + timedelta(seconds=60)
        assert not await circuit_service.is_available(db, mid, now=t0 + timedelta(seconds=59))
        assert await circuit_service.is_available(db, mid, now=t0 + timedelta(seconds=61))

        # 探测失败：保持 open，进入 30s 探测间隔
        t1 = t0 + timedelta(seconds=61)
        await circuit_service.on_failure(db, mid, now=t1)
        row = (
            await db.execute(
                select(ModelCircuitState).where(ModelCircuitState.model_id == mid)
            )
        ).scalar_one()
        assert row.state == "open"
        assert row.next_probe_at == t1 + timedelta(seconds=30)

        # 探测成功：恢复 closed，计数清零（自动切回）
        await circuit_service.on_success(db, mid)
        row = (
            await db.execute(
                select(ModelCircuitState).where(ModelCircuitState.model_id == mid)
            )
        ).scalar_one()
        assert row.state == "closed" and row.consecutive_failures == 0

    # 重启持久化：状态存库，新会话读回一致
    async with SessionLocal() as db:
        await circuit_service.on_failure(db, mid, now=t0)
        await circuit_service.on_failure(db, mid, now=t0)
        await circuit_service.on_failure(db, mid, now=t0)
    async with SessionLocal() as db:
        assert not await circuit_service.is_available(db, mid, now=t0 + timedelta(seconds=30))
        assert await circuit_service.is_available(db, mid, now=t0 + timedelta(seconds=61))


# ── 冒烟（验收 §四.3）：失败 → 切备用 → 熔断 → 恢复自动切回 ──
async def test_smoke_failover_circuit_recovery(client, monkeypatch):
    admin = await login(client)
    user = await _mk_user(client, admin, "smoker")
    primary_id = await _default_model_id(client, admin)
    _, backup_id = await _mk_mock_model(client, admin, "mock-b")
    await _set_assignment(client, admin, "chat", primary_id, [backup_id])

    failing = {PRIMARY_MOCK_NAME}

    def _patch_stream():
        monkeypatch.setattr(
            llm_gateway, "chat_stream", _fake_chat_stream(fail_names=set(failing))
        )

    # 阶段 1：主模型注入失败 → 自动切备用；连挂 3 次 → 熔断摘出
    _patch_stream()
    for _ in range(3):
        resp = await client.post(
            "/chat", json={"app_id": "chat", "message": "你好"}, headers=user
        )
        assert resp.status_code == 200
        assert any("delta" in e for e in _sse_events(resp.text))
    # 6 条账：3 次主模型失败 + 3 次备用成功
    assert await _log_count(app_key="chat") == 6
    states = (
        await client.get("/admin/models/circuit-states", headers=admin)
    ).json()
    primary_state = next(s for s in states if s["model_id"] == primary_id)
    assert primary_state["state"] == "open"
    assert primary_state["consecutive_failures"] == 3

    # 阶段 2：熔断摘出后不再尝试主模型（每次只打备用，1 条账）
    resp = await client.post("/chat", json={"app_id": "chat", "message": "还在吗"}, headers=user)
    assert resp.status_code == 200
    assert await _log_count(app_key="chat") == 7

    # 阶段 3：冷却 60s 到点 → 探测仍失败 → 30s 探测间隔
    base = datetime.now(UTC)
    monkeypatch.setattr(
        circuit_service, "utcnow", lambda: base + timedelta(seconds=61)
    )
    resp = await client.post("/chat", json={"app_id": "chat", "message": "探测"}, headers=user)
    assert resp.status_code == 200
    assert await _log_count(app_key="chat") == 9  # 探测失败 1 + 备用成功 1
    states = (
        await client.get("/admin/models/circuit-states", headers=admin)
    ).json()
    assert next(s for s in states if s["model_id"] == primary_id)["state"] == "open"

    # 阶段 4：探测成功 → 自动切回主模型（此后主模型打头）
    failing.clear()
    _patch_stream()  # 重新打补丁：fake 的 fail_names 是创建时的快照，需重建
    monkeypatch.setattr(
        circuit_service, "utcnow", lambda: base + timedelta(seconds=92)
    )
    resp = await client.post("/chat", json={"app_id": "chat", "message": "恢复"}, headers=user)
    assert resp.status_code == 200
    assert await _log_count(app_key="chat") == 10
    states = (
        await client.get("/admin/models/circuit-states", headers=admin)
    ).json()
    assert next(s for s in states if s["model_id"] == primary_id)["state"] == "closed"

    resp = await client.post("/chat", json={"app_id": "chat", "message": "确认"}, headers=user)
    assert resp.status_code == 200
    async with SessionLocal() as db:
        last = (
            await db.execute(
                select(LLMCallLog).where(LLMCallLog.app_key == "chat").order_by(LLMCallLog.id.desc()).limit(1)
            )
        ).scalar_one()
    assert last.model_id == primary_id  # 主模型重新打头 = 自动切回


# ── 记账对账（费用 = 单价快照 × token；事后改价不动历史）────────
async def test_metering_cost_snapshot_and_reconcile(client, monkeypatch):
    admin = await login(client)
    user = await _mk_user(client, admin, "accountant")
    pid, mid = await _mk_mock_model(client, admin, "mock-priced")
    await _set_assignment(client, admin, "money_parse", mid, [])

    # 定价：输入 2 元/百万 token，输出 8 元/百万 token（meta.pricing，Q1 拍板）
    resp = await client.put(
        f"/admin/models/providers/{pid}/models/{mid}",
        json={
            "meta": {
                "context": "",
                "vision": False,
                "files": False,
                "pricing": {"input_per_million": 2.0, "output_per_million": 8.0},
            }
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["meta"]["pricing"]["input_per_million"] == 2.0

    usage = {"input_tokens": 1_000_000, "output_tokens": 500_000}
    monkeypatch.setattr(llm_gateway, "chat_once", _fake_chat_once(set(), usage=usage))
    resp = await client.post("/money/parse", json={"text": "午饭 12.5"}, headers=user)
    assert resp.status_code == 200, resp.text

    # 费用 = 1,000,000×2/1e6 + 500,000×8/1e6 = 6.0 元
    async with SessionLocal() as db:
        row = (
            await db.execute(select(LLMCallLog).where(LLMCallLog.model_id == mid))
        ).scalar_one()
    assert row.input_tokens == 1_000_000 and row.output_tokens == 500_000
    assert float(row.cost) == pytest.approx(6.0)
    assert float(row.input_price) == 2.0 and float(row.output_price) == 8.0

    # 事后改价 → 新调用按新价记，历史账不动
    await client.put(
        f"/admin/models/providers/{pid}/models/{mid}",
        json={"meta": {"pricing": {"input_per_million": 1.0, "output_per_million": 8.0}}},
        headers=admin,
    )
    resp = await client.post("/money/parse", json={"text": "晚饭 20"}, headers=user)
    assert resp.status_code == 200
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(LLMCallLog).where(LLMCallLog.model_id == mid).order_by(LLMCallLog.id)
            )
        ).scalars().all()
    assert len(rows) == 2
    assert float(rows[0].cost) == pytest.approx(6.0)  # 旧账不变
    assert float(rows[1].cost) == pytest.approx(5.0)  # 新价：1 + 4

    # 统计对账（验收 §四.4）：summary 与 llm_call_logs 明细一致
    summary = (
        await client.get("/admin/models/usage/summary", headers=admin)
    ).json()
    assert summary["total_calls"] == 2
    assert summary["input_tokens"] == 2_000_000
    assert summary["output_tokens"] == 1_000_000
    assert summary["total_cost"] == pytest.approx(11.0)
    priced = next(m for m in summary["by_model"] if m["model_id"] == mid)
    assert priced["calls"] == 2 and priced["cost"] == pytest.approx(11.0)
    app_stat = next(a for a in summary["by_app"] if a["app_key"] == "money_parse")
    assert app_stat["calls"] == 2

    # 日志明细与时间筛选
    logs = (
        await client.get("/admin/models/usage/logs?page_size=50", headers=admin)
    ).json()
    assert logs["total"] == 2
    assert all(l["app_key"] == "money_parse" for l in logs["items"])
    past = await client.get(
        "/admin/models/usage/logs",
        params={"end": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        headers=admin,
    )
    assert past.status_code == 200 and past.json()["total"] == 0
    bad = await client.get(
        "/admin/models/usage/logs",
        params={"start": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=admin,
    )
    assert bad.status_code == 400


# ── 权限：统计/指派/熔断仅 admin（沿用 admin:models，零新增鉴权面）──
async def test_routing_admin_endpoints_forbidden_for_member(client):
    admin = await login(client)
    bob = await _mk_user(client, admin, "bob")
    for path in (
        "/admin/models/assignments",
        "/admin/models/circuit-states",
        "/admin/models/usage/summary",
        "/admin/models/usage/logs",
    ):
        resp = await client.get(path, headers=bob)
        assert resp.status_code == 403, path
    resp = await client.put(
        "/admin/models/assignments/chat",
        json={"primary_model_id": 1, "fallback_chain": []},
        headers=bob,
    )
    assert resp.status_code == 403
