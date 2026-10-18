"""RBAC 与成员管理测试（PRD §4.2）：权限点 / 用户 CRUD / 角色 CRUD / 软删 / 个人设置。"""
from tests.conftest import ADMIN_USERNAME, login


async def _create_user(client, admin_headers, username="bob", role_ids=None):
    resp = await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": role_ids or []},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_member_forbidden_from_admin(client):
    """member 访问 /admin/* → 403。"""
    admin = await login(client)
    await _create_user(client, admin, "bob")
    bob = await login(client, "bob", "pass-123")
    for path in ("/admin/users", "/admin/roles", "/admin/permissions"):
        resp = await client.get(path, headers=bob)
        assert resp.status_code == 403, path


async def test_user_crud_flow(client):
    admin = await login(client)

    # 列表 + 分页结构
    resp = await client.get("/admin/users", headers=admin)
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    assert page["items"][0]["username"] == ADMIN_USERNAME

    # 创建（无 role_ids → 默认 member）
    user = await _create_user(client, admin, "bob")
    assert user["roles"][0]["name"] == "member"
    uid = user["id"]

    # 重名 → 409
    resp = await client.post(
        "/admin/users",
        json={"username": "bob", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code == 409

    # 详情含权限点
    resp = await client.get(f"/admin/users/{uid}", headers=admin)
    assert resp.status_code == 200
    detail = resp.json()
    assert "app:chat" in detail["permissions"]
    assert "admin:users" not in detail["permissions"]

    # 重设角色为 admin → 获得 admin 权限点
    roles = (await client.get("/admin/roles", headers=admin)).json()
    admin_role_id = next(r["id"] for r in roles if r["name"] == "admin")
    resp = await client.put(
        f"/admin/users/{uid}/roles", json={"role_ids": [admin_role_id]}, headers=admin
    )
    assert resp.status_code == 200
    assert [r["name"] for r in resp.json()["roles"]] == ["admin"]

    resp = await client.get(f"/admin/users/{uid}", headers=admin)
    assert "admin:users" in resp.json()["permissions"]

    # 无效角色 ID → 400
    resp = await client.put(
        f"/admin/users/{uid}/roles", json={"role_ids": [9999]}, headers=admin
    )
    assert resp.status_code == 400

    # 更新昵称 / 停用再启用
    resp = await client.put(
        f"/admin/users/{uid}", json={"nickname": "小博", "is_active": False}, headers=admin
    )
    assert resp.json()["nickname"] == "小博"
    assert resp.json()["is_active"] is False
    resp = await client.put(f"/admin/users/{uid}", json={"is_active": True}, headers=admin)
    assert resp.json()["is_active"] is True


async def test_admin_cannot_disable_or_delete_self(client):
    admin = await login(client)
    me = (await client.get("/auth/me", headers=admin)).json()

    resp = await client.put(
        f"/admin/users/{me['id']}", json={"is_active": False}, headers=admin
    )
    assert resp.status_code == 400

    resp = await client.delete(f"/admin/users/{me['id']}", headers=admin)
    assert resp.status_code == 400


async def test_reset_password_returns_once(client):
    admin = await login(client)
    user = await _create_user(client, admin, "carol")
    resp = await client.post(f"/admin/users/{user['id']}/reset-password", headers=admin)
    assert resp.status_code == 200
    new_password = resp.json()["new_password"]
    assert new_password
    resp = await client.post(
        "/auth/login", json={"username": "carol", "password": new_password}
    )
    assert resp.status_code == 200


async def test_soft_delete_user(client):
    admin = await login(client)
    user = await _create_user(client, admin, "dave")

    resp = await client.delete(f"/admin/users/{user['id']}", headers=admin)
    assert resp.status_code == 200

    # 软删后：登录 401、详情 404、列表不见
    resp = await client.post(
        "/auth/login", json={"username": "dave", "password": "pass-123"}
    )
    assert resp.status_code == 401
    resp = await client.get(f"/admin/users/{user['id']}", headers=admin)
    assert resp.status_code == 404
    resp = await client.get("/admin/users", headers=admin)
    assert all(u["username"] != "dave" for u in resp.json()["items"])


async def test_role_crud_flow(client):
    admin = await login(client)
    roles = (await client.get("/admin/roles", headers=admin)).json()
    assert {r["name"] for r in roles} >= {"admin", "member"}
    assert all(r["built_in"] for r in roles if r["name"] in {"admin", "member"})

    # 新建角色
    resp = await client.post(
        "/admin/roles", json={"name": "auditor", "description": "只读"}, headers=admin
    )
    assert resp.status_code == 201
    rid = resp.json()["id"]

    # 重名 → 409
    resp = await client.post("/admin/roles", json={"name": "auditor"}, headers=admin)
    assert resp.status_code == 409

    # 重设权限点
    resp = await client.put(
        f"/admin/roles/{rid}/permissions", json={"permissions": ["app:chat"]}, headers=admin
    )
    assert resp.status_code == 200
    assert [p["code"] for p in resp.json()["permissions"]] == ["app:chat"]

    # 无效权限点 → 400
    resp = await client.put(
        f"/admin/roles/{rid}/permissions",
        json={"permissions": ["nope:bad"]},
        headers=admin,
    )
    assert resp.status_code == 400

    # 改名
    resp = await client.put(f"/admin/roles/{rid}", json={"name": "viewer"}, headers=admin)
    assert resp.json()["name"] == "viewer"

    # 预置角色不可删
    admin_role = next(r for r in roles if r["name"] == "admin")
    resp = await client.delete(f"/admin/roles/{admin_role['id']}", headers=admin)
    assert resp.status_code == 403

    # 自定义角色可删
    resp = await client.delete(f"/admin/roles/{rid}", headers=admin)
    assert resp.status_code == 200


async def test_permissions_list(client):
    admin = await login(client)
    resp = await client.get("/admin/permissions", headers=admin)
    assert resp.status_code == 200
    codes = {p["code"] for p in resp.json()}
    assert codes == {"app:chat", "app:money", "app:papers", "admin:users", "admin:models"}


async def test_me_settings_upsert(client):
    admin = await login(client)
    await _create_user(client, admin, "erin")
    erin = await login(client, "erin", "pass-123")

    # 初始无设置
    resp = await client.get("/me", headers=erin)
    assert resp.status_code == 200
    assert resp.json()["settings"] == {}

    # upsert 已知 key（文献订阅关键词，批次 2 启用）
    payload = {"key": "subscribe_keywords", "value": {"keywords": ["睡眠", "代谢"]}}
    resp = await client.put("/me/settings", json=payload, headers=erin)
    assert resp.status_code == 200

    resp = await client.get("/me", headers=erin)
    assert resp.json()["settings"]["subscribe_keywords"]["keywords"] == ["睡眠", "代谢"]

    # 覆盖更新
    payload["value"] = {"keywords": ["肠道菌群"]}
    resp = await client.put("/me/settings", json=payload, headers=erin)
    assert resp.status_code == 200
    resp = await client.get("/me", headers=erin)
    assert resp.json()["settings"]["subscribe_keywords"]["keywords"] == ["肠道菌群"]

    # 本人隔离：admin 看不到 erin 的设置
    resp = await client.get("/me", headers=admin)
    assert resp.json()["settings"] == {}
