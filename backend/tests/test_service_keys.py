"""服务 Key 表测试（架构设计-增量 v2.9）：CRUD + 唯一约束 + 掩码不回显 + 权限 + get_key 三态。

- /admin/service-keys 四端点挂现有 admin:models 权限（零新增权限点）；
- 列表/详情掩码：断言响应文本不含完整 key 字符串；
- get_key（app/services/service_keys.py）：启用返回行 / 停用返回 None / 不存在返回 None。
"""

from app.db import SessionLocal
from app.services.service_keys import get_key
from tests.conftest import login

BASE = "/admin/service-keys"
FULL_KEY = "sk-mineru-full-key-12345678"


async def _create(client, headers, service_key: str = "mineru", enabled: bool = True):
    return await client.post(
        BASE,
        json={
            "service_key": service_key,
            "vendor": "MinerU 官方",
            "api_key": FULL_KEY,
            "base_url": "https://mineru.net",
            "note": "PDF 解析",
            "enabled": enabled,
        },
        headers=headers,
    )


async def test_service_key_crud_and_masking(client):
    admin = await login(client)
    resp = await _create(client, admin)
    assert resp.status_code == 201, resp.text
    row = resp.json()
    rid = row["id"]
    # 掩码口径：前 4 + **** + 后 4；创建响应不回显完整 key
    assert row["api_key_masked"] == FULL_KEY[:4] + "****" + FULL_KEY[-4:]
    assert FULL_KEY not in resp.text

    # 列表掩码
    resp = await client.get(BASE, headers=admin)
    assert resp.status_code == 200
    assert FULL_KEY not in resp.text
    assert resp.json()[0]["api_key_masked"] == FULL_KEY[:4] + "****" + FULL_KEY[-4:]

    # PUT：改厂商/备注/网址，钥匙留空 = 不改
    resp = await client.put(
        f"{BASE}/{rid}",
        json={"vendor": "MinerU 新", "note": "轮换备注", "base_url": "https://api.mineru.net"},
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["vendor"] == "MinerU 新"
    assert resp.json()["note"] == "轮换备注"
    assert resp.json()["base_url"] == "https://api.mineru.net"
    assert resp.json()["api_key_masked"] == FULL_KEY[:4] + "****" + FULL_KEY[-4:]
    assert FULL_KEY not in resp.text

    # PUT：钥匙留空字符串 = 不修改
    resp = await client.put(f"{BASE}/{rid}", json={"api_key": ""}, headers=admin)
    assert resp.status_code == 200
    assert resp.json()["api_key_masked"] == FULL_KEY[:4] + "****" + FULL_KEY[-4:]

    # PUT：轮换钥匙（新完整 key 只在写入时出现，响应仍掩码）
    new_key = "sk-rotated-key-987654321"
    resp = await client.put(f"{BASE}/{rid}", json={"api_key": new_key}, headers=admin)
    assert resp.status_code == 200
    assert resp.json()["api_key_masked"] == new_key[:4] + "****" + new_key[-4:]
    assert new_key not in resp.text

    # DELETE
    resp = await client.delete(f"{BASE}/{rid}", headers=admin)
    assert resp.status_code == 200
    resp = await client.get(BASE, headers=admin)
    assert resp.json() == []
    resp = await client.put(f"{BASE}/{rid}", json={"note": "x"}, headers=admin)
    assert resp.status_code == 404


async def test_service_key_unique_and_format(client):
    admin = await login(client)
    assert (await _create(client, admin)).status_code == 201
    resp = await _create(client, admin, service_key="mineru")  # 重复 service_key
    assert resp.status_code == 409

    # 格式校验：小写字母数字下划线
    for bad in ["MinerU", "miner-u", "miner u", "矿工", "-mineru", "mineru-", "a" * 65]:
        resp = await _create(client, admin, service_key=bad)
        assert resp.status_code == 422, f"{bad} 应被拒"

    for good in ["funasr", "dashscope", "mineru_v2", "a1_2"]:
        resp = await _create(client, admin, service_key=good)
        assert resp.status_code == 201, f"{good} 应通过"


async def test_service_key_member_forbidden(client):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "bob", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    bob = await login(client, "bob", "pass-123")
    assert (await client.get(BASE, headers=bob)).status_code == 403
    assert (await _create(client, bob)).status_code == 403
    assert (await client.put(f"{BASE}/1", json={"note": "x"}, headers=bob)).status_code == 403
    assert (await client.delete(f"{BASE}/1", headers=bob)).status_code == 403


async def test_get_key_three_states(client):
    admin = await login(client)
    resp = await _create(client, admin, service_key="funasr", enabled=True)
    assert resp.status_code == 201
    rid = resp.json()["id"]

    async with SessionLocal() as db:
        # 启用：取到行（含完整 api_key/base_url，供服务侧消费）
        row = await get_key(db, "funasr")
        assert row is not None
        assert row.api_key == FULL_KEY
        assert row.base_url == "https://mineru.net"

        # 停用：取不到
        await client.put(f"{BASE}/{rid}", json={"enabled": False}, headers=admin)
        assert await get_key(db, "funasr") is None

        # 不存在：取不到
        assert await get_key(db, "no-such-service") is None
