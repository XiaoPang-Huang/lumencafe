"""步 5 系统状态接口测试（GET /api/status，工作台状态灯数据源）。

覆盖：未登录 401；登录 200 且字段齐全（api/db/version；测试环境未挂载
backup_state 卷 → backup=null）；backup 卷有 last_run.json 时真实解析；
db 探活真打（SELECT 1 抛错 → db=false 且接口仍 200）；非 admin 成员可见。
"""
import json

from sqlalchemy import TextClause
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import SessionLocal, get_db
from app.main import app as fastapi_app
from tests.conftest import login


async def test_status_requires_auth(client):
    resp = await client.get("/status")
    assert resp.status_code == 401


async def test_status_fields_ok(client):
    admin = await login(client)
    resp = await client.get("/status", headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api"] is True
    assert body["db"] is True  # 真实探活：DB 正常必为 true
    assert body["backup"] is None  # 测试环境未挂载 backup_state 卷 → 未配置
    assert isinstance(body["version"], str) and body["version"]


async def test_status_member_visible(client):
    """登录用户可见（拍板：不要求 admin）。"""
    admin = await login(client)
    resp = await client.post(
        "/admin/users",
        json={"username": "status_member", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    member = await login(client, "status_member", "pass-123")
    resp = await client.get("/status", headers=member)
    assert resp.status_code == 200, resp.text
    assert resp.json()["api"] is True


async def test_status_backup_state_parsed(client, tmp_path, monkeypatch):
    """backup_state 卷有 last_run.json → 真实解析（含失败态与中文错误）。"""
    admin = await login(client)
    state = {
        "succeeded": False,
        "at": "2026-10-25T14:27:16Z",
        "error": "pg_dump 失败：connection refused",
    }
    (tmp_path / "last_run.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(settings, "backup_state_dir", str(tmp_path))
    resp = await client.get("/status", headers=admin)
    assert resp.status_code == 200, resp.text
    backup = resp.json()["backup"]
    assert backup is not None
    assert backup["succeeded"] is False
    assert backup["at"] == "2026-10-25T14:27:16Z"
    assert backup["error"] == "pg_dump 失败：connection refused"


class _FlakySession:
    """包装真实会话：只有 TextClause（SELECT 1 探活）抛错，其余查询放行。

    get_current_user 的鉴权查询也走 get_db 依赖，必须放行才能测到探活本身。
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def execute(self, clause, *args, **kwargs):
        if isinstance(clause, TextClause):
            raise SQLAlchemyError("connection lost")
        return await self._inner.execute(clause, *args, **kwargs)


async def test_status_db_probe_failure(client, monkeypatch):
    """探活真打：SELECT 1 抛错 → db=false，接口仍 200（灯红而非 503）。"""
    admin = await login(client)

    async def flaky_db():
        async with SessionLocal() as session:
            yield _FlakySession(session)

    fastapi_app.dependency_overrides[get_db] = flaky_db
    try:
        resp = await client.get("/status", headers=admin)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["api"] is True
        assert body["db"] is False
    finally:
        fastapi_app.dependency_overrides.clear()
