"""pi-runner 主体接入测试（开发计划-pi-runner-v1 步 5）。

- POST /agent/runs：登录 + app:agent 权限；创建 pi_runs 行并异步派发；
- GET /agent/runs/{run_id}：本人可见，他人 404；
- execute_run：pi-runner completed 后，把 result.md/PDF 从输出目录写入 storage。
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models.pi import PiRun
from app.services import pi_client, pi_runner, pipeline
from tests.conftest import login


@pytest.mark.asyncio
async def test_create_agent_run_returns_accepted(client, monkeypatch):
    monkeypatch.setattr(pipeline, "push_pi_run", lambda *args, **kwargs: True)
    headers = await login(client)

    resp = await client.post(
        "/agent/runs",
        json={"task": "下载 arXiv 1706.03762 并写入结果"},
        headers=headers,
    )

    assert resp.status_code == 202
    data = resp.json()
    assert data["run_id"]
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_agent_run_is_visible_only_to_owner(client, monkeypatch):
    monkeypatch.setattr(pipeline, "push_pi_run", lambda *args, **kwargs: True)
    admin = await login(client)
    created = await client.post(
        "/admin/users",
        json={"username": "agent-bob", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    bob = await login(client, "agent-bob", "pass-123")

    resp = await client.post(
        "/agent/runs", json={"task": "总结 example.com"}, headers=admin
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    own = await client.get(f"/agent/runs/{run_id}", headers=admin)
    assert own.status_code == 200
    assert own.json()["task"] == "总结 example.com"

    other = await client.get(f"/agent/runs/{run_id}", headers=bob)
    assert other.status_code == 404


@pytest.mark.asyncio
async def test_event_stream_retries_until_pi_runner_run_exists(monkeypatch):
    payloads = [
        b'data: {"type":"run_end","status":"completed"}\n\n',
        b"data: [DONE]\n\n",
    ]

    class Resp:
        def __init__(self, status: int, body: bytes = b""):
            self.status_code = status
            self._body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def aread(self):
            return self._body

        async def aiter_raw(self):
            for chunk in payloads:
                yield chunk

    responses = [Resp(404, b'{"error":"run missing"}'), Resp(200)]

    class FakeClient:
        def stream(self, method: str, url: str, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr(pi_client, "get_http_client", lambda: FakeClient())
    monkeypatch.setattr(pi_client, "EVENT_START_RETRY_DELAY", 0.01)

    chunks = [chunk async for chunk in pi_client.iter_events("late-run")]
    assert b'"status":"completed"' in b"".join(chunks)


@pytest.mark.asyncio
async def test_execute_run_persists_outputs_to_storage(client, monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []
    stored: dict[str, bytes] = {}

    async def fake_start(run_id: str, task: str):
        calls.append((run_id, task))
        return {"status": "running"}

    async def fake_wait(run_id: str, **kwargs):
        return {"status": "completed", "events": 3}

    class FakeStorage:
        async def put(self, app: str, key: str, data: bytes) -> None:
            assert app == "pi"
            stored[key] = data

    async def fake_get_storage(db):
        return FakeStorage()

    run_id = "testrun001"
    out = tmp_path / run_id
    out.mkdir()
    (out / "result.md").write_text("下载完成", encoding="utf-8")
    (out / "1706.03762.pdf").write_bytes(b"%PDF-fake")

    monkeypatch.setattr(pi_client, "start_run", fake_start)
    monkeypatch.setattr(pi_client, "wait_for_terminal", fake_wait)
    monkeypatch.setattr(pi_runner, "get_storage", fake_get_storage)
    monkeypatch.setattr(settings, "pi_runner_output_dir", str(tmp_path))

    async with SessionLocal() as db:
        db.add(PiRun(run_id=run_id, user_id=1, task="下载论文", status="pending"))
        await db.commit()

        result = await pi_runner.execute_run(db, run_id)

        row = (await db.execute(select(PiRun).where(PiRun.run_id == run_id))).scalar_one()
        assert result["status"] == "completed"
        assert row.status == "completed"
        assert row.result_key == f"runs/{run_id}/result.md"
        assert row.artifacts == [f"runs/{run_id}/1706.03762.pdf", f"runs/{run_id}/result.md"]
        assert stored[row.result_key].decode("utf-8") == "下载完成"
        assert calls[0][0] == run_id
        assert "下载论文" in calls[0][1]
        assert "/output/testrun001" in calls[0][1]
        assert "result.md" in calls[0][1]
