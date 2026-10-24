"""记账测试（PRD §4.7 + 架构设计 §5.3）：分类规则 / 幂等入账 / 校验 / 统计 / AI parse。"""

from datetime import date, timedelta

import pytest

from app.services import llm_gateway, route_service
from tests.conftest import login


async def _money_user(client, username="mike"):
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    return await login(client, username, "pass-123")


def _txn(request_id, amount=1580, type_="expense", category_id=1, date_str=None, note="午餐"):
    return {
        "request_id": request_id,
        "amount": amount,
        "type": type_,
        "category_id": category_id,
        "note": note,
        "date": date_str or date.today().isoformat(),
    }


async def _food_category_id(client, headers):
    cats = (await client.get("/money/categories", headers=headers)).json()
    return next(c["id"] for c in cats if c["name"] == "餐饮")


# ── 分类 ────────────────────────────────────────────────
async def test_categories_seeded_and_rules(client):
    headers = await _money_user(client)
    resp = await client.get("/money/categories", headers=headers)
    assert resp.status_code == 200
    cats = resp.json()
    assert [c["name"] for c in cats] == ["餐饮", "交通", "购物", "居住", "工资"]
    assert all(c["built_in"] for c in cats)
    food = next(c for c in cats if c["name"] == "餐饮")
    salary = next(c for c in cats if c["name"] == "工资")

    # 同 kind 重名 409（与预置 餐饮/expense 重名）
    resp = await client.post(
        "/money/categories", json={"name": "餐饮", "kind": "expense"}, headers=headers
    )
    assert resp.status_code == 409

    # 预置分类不可改 kind / 不可删除
    resp = await client.put(
        f"/money/categories/{food['id']}", json={"kind": "income"}, headers=headers
    )
    assert resp.status_code == 400
    resp = await client.delete(f"/money/categories/{food['id']}", headers=headers)
    assert resp.status_code == 403

    # 改名可以；不同 kind 同名可以（PRD 按 kind 查重）
    resp = await client.put(
        f"/money/categories/{salary['id']}", json={"name": "月薪"}, headers=headers
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/money/categories", json={"name": "餐饮", "kind": "both"}, headers=headers
    )
    assert resp.status_code == 201

    # 本人隔离：另一个用户看不到这些分类
    other = await _money_user(client, "nora")
    resp = await client.get("/money/categories", headers=other)
    assert all(c["name"] != "月薪" for c in resp.json())


async def test_delete_category_guarded_by_transactions(client):
    headers = await _money_user(client)
    resp = await client.post(
        "/money/categories", json={"name": "咖啡", "kind": "expense"}, headers=headers
    )
    cid = resp.json()["id"]

    # 有账目时 409 + 账目数
    await client.post("/money/transactions", json=_txn("r-cat-1", category_id=cid), headers=headers)
    resp = await client.delete(f"/money/categories/{cid}", headers=headers)
    assert resp.status_code == 409
    assert "1 笔" in resp.json()["detail"]

    # 删除账目后可删
    page = (await client.get("/money/transactions", headers=headers)).json()
    await client.delete(f"/money/transactions/{page['items'][0]['id']}", headers=headers)
    resp = await client.delete(f"/money/categories/{cid}", headers=headers)
    assert resp.status_code == 200


# ── 账目与幂等 ──────────────────────────────────────────
async def test_transaction_idempotency(client):
    headers = await _money_user(client)
    food_id = await _food_category_id(client, headers)
    body = _txn("idem-001", amount=3200, category_id=food_id)

    resp = await client.post("/money/transactions", json=body, headers=headers)
    assert resp.status_code == 201
    first = resp.json()
    assert first["idempotent"] is False

    # 重复提交（双击/重试）→ 200 + 原记录 + idempotent:true
    resp = await client.post("/money/transactions", json=body, headers=headers)
    assert resp.status_code == 200
    replay = resp.json()
    assert replay["idempotent"] is True
    assert replay["id"] == first["id"]
    assert replay["amount"] == 3200


async def test_transaction_validations(client):
    headers = await _money_user(client)
    today = date.today()

    # 日期晚于今天
    future = (today + timedelta(days=1)).isoformat()
    resp = await client.post(
        "/money/transactions",
        json=_txn("v-future", date_str=future),
        headers=headers,
    )
    assert resp.status_code == 400

    # 分类不属本人（别人的分类 id=1 是 mike 的？用不存在的 id）
    resp = await client.post(
        "/money/transactions", json=_txn("v-cat", category_id=9999), headers=headers
    )
    assert resp.status_code == 400

    # type×kind 不兼容：工资（income）记 expense
    cats = (await client.get("/money/categories", headers=headers)).json()
    salary_id = next(c["id"] for c in cats if c["kind"] == "income")
    resp = await client.post(
        "/money/transactions", json=_txn("v-kind", category_id=salary_id), headers=headers
    )
    assert resp.status_code == 400

    # 收入记到 income 分类 OK
    resp = await client.post(
        "/money/transactions",
        json=_txn("v-ok", amount=800000, type_="income", category_id=salary_id),
        headers=headers,
    )
    assert resp.status_code == 201


async def test_transaction_isolation_and_crud(client):
    headers = await _money_user(client)
    food_id = await _food_category_id(client, headers)
    resp = await client.post(
        "/money/transactions", json=_txn("iso-1", category_id=food_id), headers=headers
    )
    tid = resp.json()["id"]

    other = await _money_user(client, "olga")
    resp = await client.get(f"/money/transactions/{tid}", headers=other)
    assert resp.status_code == 404
    resp = await client.put(
        f"/money/transactions/{tid}", json={"note": "篡改"}, headers=other
    )
    assert resp.status_code == 404
    resp = await client.delete(f"/money/transactions/{tid}", headers=other)
    assert resp.status_code == 404

    # 本人编辑（部分更新）
    resp = await client.put(
        f"/money/transactions/{tid}", json={"amount": 999, "note": "改价"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["amount"] == 999
    assert resp.json()["request_id"] == "iso-1"  # 幂等键不可变


async def test_transaction_list_filters_and_pagination(client):
    headers = await _money_user(client)
    food_id = await _food_category_id(client, headers)
    today = date.today()
    for i in range(25):
        await client.post(
            "/money/transactions",
            json=_txn(f"page-{i}", amount=100 + i, category_id=food_id, note=f"第{i}笔"),
            headers=headers,
        )

    page1 = (await client.get("/money/transactions?page=1&page_size=10", headers=headers)).json()
    assert page1["total"] == 25 and len(page1["items"]) == 10
    page3 = (await client.get("/money/transactions?page=3&page_size=10", headers=headers)).json()
    assert len(page3["items"]) == 5

    # 倒序：新 id 在前
    assert page1["items"][0]["id"] > page1["items"][-1]["id"]

    # type 过滤
    cats = (await client.get("/money/categories", headers=headers)).json()
    salary_id = next(c["id"] for c in cats if c["kind"] == "income")
    await client.post(
        "/money/transactions",
        json=_txn("filter-1", amount=5000, type_="income", category_id=salary_id),
        headers=headers,
    )
    resp = (await client.get("/money/transactions?type=income", headers=headers)).json()
    assert resp["total"] == 1 and resp["items"][0]["amount"] == 5000

    # from/to 过滤（默认本月不再生效，因为显式给了 from）
    resp = (
        await client.get(
            f"/money/transactions?from={(today - timedelta(days=1)).isoformat()}&to={(today - timedelta(days=1)).isoformat()}",
            headers=headers,
        )
    ).json()
    assert resp["total"] == 0


# ── 统计 ────────────────────────────────────────────────
async def test_monthly_and_trend_stats(client):
    headers = await _money_user(client)
    today = date.today()
    month = today.strftime("%Y-%m")
    cats = (await client.get("/money/categories", headers=headers)).json()
    food_id = next(c["id"] for c in cats if c["name"] == "餐饮")
    traffic_id = next(c["id"] for c in cats if c["name"] == "交通")
    salary_id = next(c["id"] for c in cats if c["kind"] == "income")

    await client.post(
        "/money/transactions", json=_txn("s-1", amount=3200, category_id=food_id), headers=headers
    )
    await client.post(
        "/money/transactions", json=_txn("s-2", amount=6800, category_id=food_id), headers=headers
    )
    await client.post(
        "/money/transactions", json=_txn("s-3", amount=2400, category_id=traffic_id), headers=headers
    )
    await client.post(
        "/money/transactions",
        json=_txn("s-4", amount=800000, type_="income", category_id=salary_id),
        headers=headers,
    )

    resp = await client.get(f"/money/stats/monthly?month={month}", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["expense_total"] == 3200 + 6800 + 2400
    assert stats["income_total"] == 800000
    assert stats["balance"] == 800000 - 12400
    # 支出按分类降序
    assert [c["category_id"] for c in stats["by_category"]] == [food_id, traffic_id]
    assert stats["by_category"][0]["total"] == 10000
    assert stats["by_category"][0]["count"] == 2

    # 跨月归属：上月日期归入上月
    last_month_day = (today.replace(day=1) - timedelta(days=1)).isoformat()
    await client.post(
        "/money/transactions",
        json=_txn("s-last", amount=1111, category_id=food_id, date_str=last_month_day),
        headers=headers,
    )
    resp = (
        await client.get(
            f"/money/stats/monthly?month={last_month_day[:7]}", headers=headers
        )
    ).json()
    assert resp["expense_total"] == 1111

    # 趋势：6 个月补零
    resp = (await client.get("/money/stats/trend?months=6", headers=headers)).json()
    assert len(resp["months"]) == 6
    current = next(m for m in resp["months"] if m["month"] == month)
    assert current["expense_total"] == 12400
    assert len(resp["months"]) == 6
    zero_months = [m for m in resp["months"] if m["expense_total"] == 0 and m["income_total"] == 0]
    assert len(zero_months) == 4  # 其余 4 个月无数据补零


# ── 每日看板聚合（PRD v1.1-rev7：/money/stats/summary）────────
async def test_summary_stats_normal_and_empty(client):
    from app.services import money_service

    headers = await _money_user(client)

    # 空数据：四个值全 0
    resp = await client.get("/money/stats/summary", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "yesterday_expense": 0,
        "week_expense": 0,
        "month_income": 0,
        "month_expense": 0,
    }

    # 固定「今天」= 2026-03-01（周日）→ 覆盖跨月（昨日 2/28）与跨周（本周一 2/23）边界
    fixed_today = date(2026, 3, 1)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(money_service, "_today_local", lambda: fixed_today)
    try:
        cats = (await client.get("/money/categories", headers=headers)).json()
        food_id = next(c["id"] for c in cats if c["name"] == "餐饮")
        salary_id = next(c["id"] for c in cats if c["kind"] == "income")

        async def add(rid, amount, cid, day, type_="expense"):
            resp = await client.post(
                "/money/transactions",
                json=_txn(rid, amount=amount, type_=type_, category_id=cid, date_str=day),
                headers=headers,
            )
            assert resp.status_code == 201, resp.text

        await add("sum-y", 3200, food_id, "2026-02-28")  # 昨日（跨月）
        await add("sum-w1", 6800, food_id, "2026-02-23")  # 本周一
        await add("sum-w0", 1500, food_id, "2026-02-22")  # 上周日（不计入本周）
        await add("sum-t", 2000, food_id, "2026-03-01")  # 今天（计入本周/本月）
        await add("sum-i", 800000, salary_id, "2026-02-28", type_="income")  # 上月收入（不计入本月）

        resp = await client.get("/money/stats/summary", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {
            "yesterday_expense": 3200,  # 仅 2/28 支出
            "week_expense": 6800 + 3200 + 2000,  # 2/23 周一至今，含跨月的昨日
            "month_income": 0,  # 2/28 收入归 2 月
            "month_expense": 2000,  # 仅 3/1 支出
        }

        # 本月收入：3 月入账即计入
        await add("sum-i2", 500000, salary_id, "2026-03-01", type_="income")
        resp = await client.get("/money/stats/summary", headers=headers)
        assert resp.json()["month_income"] == 500000
    finally:
        monkey.undo()


async def test_summary_stats_isolated_per_user(client):
    headers = await _money_user(client)
    other = await _money_user(client, "nora2")
    cats = (await client.get("/money/categories", headers=headers)).json()
    food_id = next(c["id"] for c in cats if c["name"] == "餐饮")
    await client.post(
        "/money/transactions",
        json=_txn("sum-iso", amount=9900, category_id=food_id),
        headers=headers,
    )
    resp = await client.get("/money/stats/summary", headers=other)
    assert resp.json()["week_expense"] == 0


# ── AI 记一笔 ───────────────────────────────────────────


async def test_parse_mock_route(client):
    """种子 mock 默认路由 → parse 走 mock 返回严格 JSON 草稿。"""
    headers = await _money_user(client)
    resp = await client.post("/money/parse", json={"text": "中午吃饭花了15块8"}, headers=headers)
    assert resp.status_code == 200
    draft = resp.json()
    assert draft["amount"] == 1580
    assert draft["type"] == "expense"
    assert draft["category_suggestion"] == "餐饮"
    assert draft["date"] == date.today().isoformat()
    assert draft["confidence"] == 0.99


async def _async_none():
    return None


async def test_parse_no_route_503(client, monkeypatch):
    headers = await _money_user(client)
    monkeypatch.setattr(route_service, "resolve_default", lambda db: _async_none())
    resp = await client.post("/money/parse", json={"text": "test"}, headers=headers)
    assert resp.status_code == 503




async def test_parse_upstream_fail_502(client, monkeypatch):
    headers = await _money_user(client)

    async def boom(cfg, messages, timeout=30.0):
        raise llm_gateway.UpstreamError("boom")

    monkeypatch.setattr(llm_gateway, "chat_once", boom)
    resp = await client.post("/money/parse", json={"text": "test"}, headers=headers)
    assert resp.status_code == 502


async def test_parse_bad_json_502(client, monkeypatch):
    headers = await _money_user(client)

    async def gibberish(cfg, messages, timeout=30.0):
        return "我没有按要求返回"

    monkeypatch.setattr(llm_gateway, "chat_once", gibberish)
    resp = await client.post("/money/parse", json={"text": "test"}, headers=headers)
    assert resp.status_code == 502
