"""模型管理测试（PRD §4.3 + Q10/Q12/Q16/Q17）：Provider/默认路由/网关令牌。

测试环境未配置任何 LLM Key → 种子走 Q12 mock 兜底（providers 有一条 mock 默认路由）。
"""

from app.services import llm_gateway
from tests.conftest import login


async def test_seed_mock_provider_with_default_route(client):
    admin = await login(client)
    resp = await client.get("/admin/models/providers", headers=admin)
    assert resp.status_code == 200
    providers = resp.json()
    assert len(providers) == 1
    mock = providers[0]
    assert mock["vendor"] == "mock"
    assert mock["is_default"] is True
    assert mock["has_key"] is False and mock["api_key_masked"] == ""

    resp = await client.get("/admin/models/default-route", headers=admin)
    route = resp.json()
    assert route["provider"]["name"] == mock["name"]
    assert route["model"]["name"] == "mock"


async def test_member_forbidden(client):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "bob", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    bob = await login(client, "bob", "pass-123")
    resp = await client.get("/admin/models/providers", headers=bob)
    assert resp.status_code == 403
    resp = await client.get("/admin/models/gateway-tokens", headers=bob)
    assert resp.status_code == 403


async def test_provider_crud_and_masking(client):
    admin = await login(client)
    resp = await client.post(
        "/admin/models/providers",
        json={
            "name": "DeepSeek 主号",
            "vendor": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-secret-key-1234",
        },
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert resp.json()["api_key_masked"] == "****1234"
    assert "sk-secret" not in resp.text

    # vendor 白名单校验
    resp = await client.post(
        "/admin/models/providers",
        json={"name": "X", "vendor": "hacker"},
        headers=admin,
    )
    assert resp.status_code == 400

    # api_key 留空 = 不修改
    resp = await client.put(
        f"/admin/models/providers/{pid}", json={"api_key": ""}, headers=admin
    )
    assert resp.status_code == 200
    assert resp.json()["api_key_masked"] == "****1234"
    assert resp.json()["has_key"] is True

    # 详情不回显真实 Key
    resp = await client.get(f"/admin/models/providers/{pid}", headers=admin)
    assert "sk-secret-key-1234" not in resp.text


async def test_custom_model_and_dup(client):
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = providers[0]["id"]

    resp = await client.post(
        f"/admin/models/providers/{pid}/models",
        json={"name": "deepseek-reasoner", "meta": {"context": "64K", "vision": False, "files": False}},
        headers=admin,
    )
    assert resp.status_code == 201
    assert resp.json()["custom"] is True

    # 同 Provider 重名 409
    resp = await client.post(
        f"/admin/models/providers/{pid}/models", json={"name": "deepseek-reasoner"}, headers=admin
    )
    assert resp.status_code == 409


async def test_model_update_and_delete(client, monkeypatch):
    """模型级修正（meta/enabled）+ 自定义删除守卫。"""
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = providers[0]["id"]

    # 自定义模型：更新 meta 与开关，随后删除
    resp = await client.post(
        f"/admin/models/providers/{pid}/models",
        json={"name": "temp-model", "meta": {"context": "", "vision": False, "files": False}},
        headers=admin,
    )
    mid = resp.json()["id"]
    resp = await client.put(
        f"/admin/models/providers/{pid}/models/{mid}",
        json={"meta": {"context": "256K", "vision": True, "files": True}, "enabled": False},
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["context"] == "256K"
    assert resp.json()["meta"]["vision"] is True
    assert resp.json()["enabled"] is False

    resp = await client.delete(f"/admin/models/providers/{pid}/models/{mid}", headers=admin)
    assert resp.status_code == 200

    # 官方拉取模型（custom=false）不可删
    async def fake_fetch(cfg):
        return ["official-x"]

    monkeypatch.setattr(llm_gateway, "fetch_model_names", fake_fetch)
    await client.post(f"/admin/models/providers/{pid}/fetch-models", headers=admin)
    detail = (await client.get(f"/admin/models/providers/{pid}", headers=admin)).json()
    official = next(m for m in detail["models"] if m["name"] == "official-x")
    resp = await client.delete(
        f"/admin/models/providers/{pid}/models/{official['id']}", headers=admin
    )
    assert resp.status_code == 400


async def test_default_route_switch(client):
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    mock_pid = providers[0]["id"]

    # 新建第二个 Provider + 模型
    resp = await client.post(
        "/admin/models/providers",
        json={"name": "Kimi 官方", "vendor": "kimi", "base_url": "https://api.moonshot.cn/v1", "api_key": "k-kimi-9"},
        headers=admin,
    )
    kimi_pid = resp.json()["id"]
    resp = await client.post(
        f"/admin/models/providers/{kimi_pid}/models",
        json={"name": "moonshot-v1-8k"},
        headers=admin,
    )
    kimi_mid = resp.json()["id"]

    # 切换到 Kimi 路由
    resp = await client.put(
        "/admin/models/default-route",
        json={"provider_id": kimi_pid, "model_id": kimi_mid},
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["provider"]["id"] == kimi_pid

    # 旧标记已清（部分唯一索引兜底验证：全库至多一个）
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    marks = {p["id"]: p["is_default"] for p in providers}
    assert marks == {mock_pid: False, kimi_pid: True}

    # 默认 Provider 被引用时禁删
    resp = await client.delete(f"/admin/models/providers/{kimi_pid}", headers=admin)
    assert resp.status_code == 409


async def test_provider_test_endpoint_mock(client):
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    resp = await client.post(
        f"/admin/models/providers/{providers[0]['id']}/test", headers=admin
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_fetch_models_upsert(client, monkeypatch):
    admin = await login(client)
    providers = (await client.get("/admin/models/providers", headers=admin)).json()
    pid = providers[0]["id"]

    async def fake_fetch(cfg):
        return ["alpha-model", "beta-model"]

    monkeypatch.setattr(llm_gateway, "fetch_model_names", fake_fetch)
    resp = await client.post(f"/admin/models/providers/{pid}/fetch-models", headers=admin)
    assert resp.status_code == 200
    assert {m["name"] for m in resp.json()} == {"alpha-model", "beta-model"}

    # 拉取结果入库：官方模型 custom=False
    detail = (await client.get(f"/admin/models/providers/{pid}", headers=admin)).json()
    fetched = [m for m in detail["models"] if m["name"] in {"alpha-model", "beta-model"}]
    assert len(fetched) == 2
    assert all(m["custom"] is False for m in fetched)

    # 重复拉取不产生重复行
    await client.post(f"/admin/models/providers/{pid}/fetch-models", headers=admin)
    detail = (await client.get(f"/admin/models/providers/{pid}", headers=admin)).json()
    assert len([m for m in detail["models"] if m["name"] == "alpha-model"]) == 1


async def test_gateway_token_create_list_revoke(client):
    admin = await login(client)

    resp = await client.post(
        "/admin/models/gateway-tokens",
        json={"name": "内部服务令牌", "model_scope": ["mock"]},
        headers=admin,
    )
    assert resp.status_code == 201
    created = resp.json()
    token = created["token"]
    assert token.startswith("sk-")
    assert created["item"]["token_mask"] == f"sk-••••{token[-4:]}"
    assert created["item"]["active"] is True

    # 列表只回显掩码
    resp = await client.get("/admin/models/gateway-tokens", headers=admin)
    body = resp.text
    assert token not in body
    items = resp.json()
    env_seeded = [t for t in items if t["name"].startswith("env 种子")]
    assert len(env_seeded) == 1  # conftest 设了 LUMEN_INTERNAL_TOKEN → 种子一个

    # 吊销立即生效
    tid = created["item"]["id"]
    resp = await client.delete(f"/admin/models/gateway-tokens/{tid}", headers=admin)
    assert resp.status_code == 200
    items = (await client.get("/admin/models/gateway-tokens", headers=admin)).json()
    revoked = next(t for t in items if t["id"] == tid)
    assert revoked["active"] is False
