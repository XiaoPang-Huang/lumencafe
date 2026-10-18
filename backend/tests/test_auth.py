"""认证接口测试（PRD §4.1）：注册开关 / 登录 / me / 改密 / 状态守卫。"""
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.money import MoneyCategory
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME, login


async def test_login_ok(client):
    resp = await client.post(
        "/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["username"] == ADMIN_USERNAME
    assert data["user"]["roles"] == ["admin"]
    assert data["token"]


async def test_login_wrong_password(client):
    resp = await client.post(
        "/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong-pass"}
    )
    assert resp.status_code == 401


async def test_register_closed_by_default(client):
    resp = await client.post(
        "/auth/register", json={"username": "newbie", "password": "pass-123"}
    )
    assert resp.status_code == 403
    assert "注册未开放" in resp.json()["detail"]


async def test_register_open_flow(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "registration_open", True)
    resp = await client.post(
        "/auth/register", json={"username": "newbie", "password": "pass-123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["roles"] == ["member"]
    assert data["token"]

    # 重复用户名 → 409
    resp = await client.post(
        "/auth/register", json={"username": "newbie", "password": "pass-123"}
    )
    assert resp.status_code == 409

    # 新用户带 member 权限点，无 admin 权限
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
    assert me.status_code == 200
    perms = me.json()["permissions"]
    assert "app:chat" in perms and "admin:users" not in perms

    # 新用户已补记账内置分类（餐饮/交通/购物/居住/工资）
    async with SessionLocal() as db:
        count = (
            await db.execute(
                select(func.count(MoneyCategory.id)).where(
                    MoneyCategory.user_id == data["user"]["id"],
                    MoneyCategory.built_in.is_(True),
                )
            )
        ).scalar_one()
    assert count == 5


async def test_me_requires_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401

    headers = await login(client)
    resp = await client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == ADMIN_USERNAME
    assert set(data["permissions"]) >= {"admin:users", "admin:models", "app:chat"}


async def test_change_password_flow(client):
    headers = await login(client)
    resp = await client.post(
        "/auth/change-password",
        json={"old_password": "not-the-password", "new_password": "new-pass-123"},
        headers=headers,
    )
    assert resp.status_code == 400

    resp = await client.post(
        "/auth/change-password",
        json={"old_password": ADMIN_PASSWORD, "new_password": "new-pass-123"},
        headers=headers,
    )
    assert resp.status_code == 200

    resp = await client.post(
        "/auth/login", json={"username": ADMIN_USERNAME, "password": "new-pass-123"}
    )
    assert resp.status_code == 200


async def test_disabled_user_cannot_login(client):
    """停用后：登录 403，带旧 token 访问 403。"""
    admin = await login(client)
    resp = await client.post(
        "/admin/users",
        json={"username": "victim", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code == 201
    uid = resp.json()["id"]

    login_resp = await client.post(
        "/auth/login", json={"username": "victim", "password": "pass-123"}
    )
    victim_headers = {"Authorization": f"Bearer {login_resp.json()['token']}"}
    me_resp = await client.get("/auth/me", headers=victim_headers)
    assert me_resp.status_code == 200

    resp = await client.put(
        f"/admin/users/{uid}", json={"is_active": False}, headers=admin
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = await client.post(
        "/auth/login", json={"username": "victim", "password": "pass-123"}
    )
    assert resp.status_code == 403

    resp = await client.get("/auth/me", headers=victim_headers)
    assert resp.status_code == 403


async def test_protected_routes_401(client):
    for path in ("/auth/me", "/me", "/admin/users", "/admin/roles", "/admin/permissions"):
        resp = await client.get(path)
        assert resp.status_code == 401, path
