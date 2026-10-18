"""应用注册表与内部任务接口测试（PRD §4.4/§4.8）。"""

from app.config import settings
from app.services import papers_crawl
from tests.conftest import login

INTERNAL_TOKEN = "pytest-internal-token-0123456789abcdef"


# ── /apps 注册表 ────────────────────────────────────────
async def test_apps_list_merged_with_visibility(client):
    headers = await login(client)
    resp = await client.get("/apps", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    app_ids = [a["id"] for a in data["apps"]]
    assert app_ids == ["chat", "money"]  # 批次 1 种子
    chat = next(a for a in data["apps"] if a["id"] == "chat")
    assert chat["mode"] == "chat" and chat["perm_code"] == "app:chat"
    assert chat["hidden"] is False and chat["category_id"] is None


async def test_apps_categories_crud(client):
    headers = await login(client)
    resp = await client.post("/apps/categories", json={"name": "效率"}, headers=headers)
    assert resp.status_code == 201
    cid = resp.json()["id"]

    resp = await client.post("/apps/categories", json={"name": "效率"}, headers=headers)
    assert resp.status_code == 409

    resp = await client.put(f"/apps/categories/{cid}", json={"name": "常用"}, headers=headers)
    assert resp.json()["name"] == "常用"

    # 删除分类：注册表与用户覆盖回落未分类
    await client.put(
        "/apps/chat/config", json={"category_id": cid}, headers=headers
    )
    resp = await client.delete(f"/apps/categories/{cid}", headers=headers)
    assert resp.status_code == 200
    apps = (await client.get("/apps", headers=headers)).json()
    chat = next(a for a in apps["apps"] if a["id"] == "chat")
    assert chat["category_id"] is None  # 覆盖被批量置 NULL


async def test_apps_visibility_override(client):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "appuser", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    headers = await login(client, "appuser", "pass-123")

    resp = await client.put("/apps/money/config", json={"hidden": True}, headers=headers)
    assert resp.status_code == 200
    apps = (await client.get("/apps", headers=headers)).json()
    money = next(a for a in apps["apps"] if a["id"] == "money")
    assert money["hidden"] is True

    # 本人隔离：他人不受影响
    apps = (await client.get("/apps", headers=admin)).json()
    money = next(a for a in apps["apps"] if a["id"] == "money")
    assert money["hidden"] is False

    # 未知应用 404
    resp = await client.put("/apps/nope/config", json={"hidden": True}, headers=headers)
    assert resp.status_code == 404


# ── /internal 任务接口 ──────────────────────────────────
async def test_internal_requires_token_header(client):
    resp = await client.post("/internal/jobs/papers-crawl")
    assert resp.status_code == 401


async def test_internal_wrong_token_401(client):
    resp = await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": "wrong"}
    )
    assert resp.status_code == 401


async def test_internal_disabled_503(client, monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "")
    resp = await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    assert resp.status_code == 503


async def test_internal_same_day_dedup(client, monkeypatch):
    calls = 0

    async def fake_crawl():
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(papers_crawl, "run_daily_crawl", fake_crawl)
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)  # 重置当日标记

    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    resp = await client.post("/internal/jobs/papers-crawl", headers=headers)
    assert resp.status_code == 200 and resp.json() == {"added": 0}
    # 同日重复触发：幂等跳过，执行体只跑一次
    resp = await client.post("/internal/jobs/papers-crawl", headers=headers)
    assert resp.status_code == 200 and resp.json() == {"added": 0}
    assert calls == 1
