"""论文域增强②测试：源目录市场（P17）+ key 认证升级 + P21 抓取参数 + NL 语义检索（P13）。

- 市场接口：字段完整性、已实现/待接入划分、key_configured 随 service_keys 两态变化；
- key 注入：OpenAlex Bearer / S2 x-api-key 两态断言（mock httpx 捕获请求头）；
- P21：year 范围折算 since/until 并透传源 API（OpenAlex filter / PubMed maxdate）、
  authors / if_min / year_to 后过滤；
- NL 检索全流程（mock AI 扩词 + mock 源）：结果入库、写 runs(trigger=semantic)、
  不写订阅词。
"""
from datetime import date

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.models.papers import Paper, PaperCrawlRun, PaperUser
from app.models.user_settings import UserSetting
from app.services import papers_crawl
from app.services.sources.catalog import SOURCE_CATALOG
from app.services.sources.doaj import DoajProvider
from app.services.sources.keys import fetch_service_api_key
from app.services.sources.openalex import OpenAlexProvider
from app.services.sources.semantic_scholar import SemanticScholarProvider
from tests.conftest import login

SINCE = date(2026, 1, 1)
IMPLEMENTED_KEYS = {"pubmed", "arxiv", "openalex", "semantic_scholar", "doaj"}


# ── 市场接口（P17） ─────────────────────────────────────
async def test_sources_market_field_completeness(client):
    headers = await login(client)
    resp = await client.get("/papers/sources", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == len(SOURCE_CATALOG)
    # 编目前 5 条 = 已接入源（注册表顺序），其后为待接入源
    for i, it in enumerate(items):
        assert set(it) >= {
            "key", "name", "category", "cost", "key_service",
            "implemented", "description", "key_configured",
        }, f"第 {i} 条字段不全：{it}"
        assert it["category"] in (
            "综合索引", "生物医学", "理工", "社科人文", "中文国内", "商业收费", "开放期刊",
        )
        assert it["cost"] in ("free", "free_key", "paid")
        if it["cost"] == "free":
            assert it["key_service"] is None
        assert it["description"]
    keys = [it["key"] for it in items]
    assert set(keys[:5]) == IMPLEMENTED_KEYS
    assert all(it["implemented"] for it in items[:5])
    assert not any(it["implemented"] for it in items[5:])
    # 未配置任何 key：所有 key 源 key_configured=False
    assert all(not it["key_configured"] for it in items if it["key_service"])


async def test_sources_market_key_configured_two_states(client):
    """service_keys 写入 openalex 钥匙后：仅 openalex 条目 key_configured 翻 True。"""
    headers = await login(client)
    resp = await client.get("/papers/sources", headers=headers)
    before = {it["key"]: it["key_configured"] for it in resp.json() if it["key_service"]}
    assert all(v is False for v in before.values())

    skey_headers = await login(client)
    resp = await client.post(
        "/admin/service-keys",
        headers=skey_headers,
        json={
            "service_key": "openalex", "vendor": "OpenAlex",
            "api_key": "test-openalex-key-0123456789", "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get("/papers/sources", headers=headers)
    after = {it["key"]: it["key_configured"] for it in resp.json() if it["key_service"]}
    assert after["openalex"] is True
    assert all(v is False for k, v in after.items() if k != "openalex")


# ── key 认证升级：请求头注入两态 ──────────────────────────
def _capture_get(monkeypatch):
    """捕获 httpx.AsyncClient.get 的 headers/params；返回捕获列表。"""

    captured: list[dict] = []

    async def fake_get(self, url, **kwargs):
        captured.append({"url": str(url), "headers": kwargs.get("headers"), "params": kwargs.get("params")})
        req = httpx.Request("GET", str(url))
        return httpx.Response(200, request=req, json={"results": [], "data": []})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


async def test_openalex_key_injected_as_bearer(monkeypatch):
    captured = _capture_get(monkeypatch)
    await OpenAlexProvider().search(["dementia"], SINCE, api_key="OA-KEY-123")
    assert captured and captured[0]["headers"] is not None
    assert captured[0]["headers"]["Authorization"] == "Bearer OA-KEY-123"


async def test_openalex_anonymous_without_key(monkeypatch):
    captured = _capture_get(monkeypatch)
    await OpenAlexProvider().search(["dementia"], SINCE)  # 无 key：匿名态
    assert captured and not captured[0]["headers"]  # headers=None：不带认证头


async def test_semantic_scholar_key_injected_as_x_api_key(monkeypatch):
    captured = _capture_get(monkeypatch)
    await SemanticScholarProvider().search(["robotics"], SINCE, api_key="S2-KEY-456")
    assert captured and captured[0]["headers"] is not None
    assert captured[0]["headers"]["x-api-key"] == "S2-KEY-456"


async def test_semantic_scholar_anonymous_without_key(monkeypatch):
    captured = _capture_get(monkeypatch)
    await SemanticScholarProvider().search(["robotics"], SINCE)
    assert captured and not captured[0]["headers"]


async def test_fetch_service_api_key_disabled_row_is_anonymous(client):
    """禁用行的 key 不注入（取匙两态：启用行可取、禁用/无行返回 None）。"""
    headers = await login(client)
    resp = await client.post(
        "/admin/service-keys",
        headers=headers,
        json={"service_key": "semantic_scholar", "vendor": "S2", "api_key": "s2-secret-key"},
    )
    assert resp.status_code == 201, resp.text
    row_id = resp.json()["id"]
    async with SessionLocal() as db:
        assert await fetch_service_api_key(db, "semantic_scholar") == "s2-secret-key"
        assert await fetch_service_api_key(db, "no_such_service") is None
        # 禁用后回到匿名态
        resp2 = await client.put(
            f"/admin/service-keys/{row_id}", headers=headers, json={"enabled": False}
        )
        assert resp2.status_code == 200, resp2.text
        assert await fetch_service_api_key(db, "semantic_scholar") is None


# ── P21：抓取期参数 ──────────────────────────────────────
def _prefs_sub(**kwargs):
    base = {
        "user_id": 1, "keywords": ("k",), "sources": ("pubmed",),
        "year_from": None, "year_to": None, "authors": (), "if_min": None,
    }
    base.update(kwargs)
    return papers_crawl.UserSubscription(**base)


def test_p21_since_until_conversion():
    base = date(2026, 10, 20)
    assert papers_crawl._sub_since_date(_prefs_sub(), base) == base  # 不限 = 全局窗口
    # year_from 折算 1 月 1 日，与全局窗口取更晚者
    assert papers_crawl._sub_since_date(_prefs_sub(year_from=2023), base) == base
    assert papers_crawl._sub_since_date(_prefs_sub(year_from=2026), base) == base
    assert papers_crawl._sub_since_date(_prefs_sub(year_from=2027), base) == date(2027, 1, 1)
    assert papers_crawl._sub_until_date(_prefs_sub()) is None
    assert papers_crawl._sub_until_date(_prefs_sub(year_to=2025)) == date(2025, 12, 31)


def test_p21_apply_crawl_filters_authors_ifmin_yearto():
    from app.services.sources import PaperItem

    items = [
        PaperItem(title="A", source="s", external_id="1", authors=("Alice Zhang",),
                  year=2026, if_approx=5.0),
        PaperItem(title="B", source="s", external_id="2", authors=("Bob Li",),
                  year=2024, if_approx=None),  # 年份超上限 + IF 为空
        PaperItem(title="C", source="s", external_id="3", authors=("Carol Wu",),
                  year=2026, if_approx=1.0),  # IF 低于下限
        PaperItem(title="D", source="s", external_id="4", authors=("Alice Zhang", "Dave"),
                  year=2025, if_approx=8.0),  # 全过
        PaperItem(title="E", source="s", external_id="5", authors=(),
                  year=2026, if_approx=None),  # 无作者：作者过滤不过；IF 空被排除
    ]
    sub = _prefs_sub(year_to=2025, authors=("alice",), if_min=3.0)
    kept = papers_crawl._apply_crawl_filters(items, sub)
    assert [i.title for i in kept] == ["D"]


def test_p21_authors_any_match_and_no_filters_passthrough():
    from app.services.sources import PaperItem

    items = [
        PaperItem(title="A", source="s", external_id="1", authors=("Bob Li",)),
        PaperItem(title="B", source="s", external_id="2", authors=("Carol Wu",)),
    ]
    sub = _prefs_sub(authors=("bob", "carol"))
    assert len(papers_crawl._apply_crawl_filters(items, sub)) == 2  # 任一命中即过
    assert len(papers_crawl._apply_crawl_filters(items, _prefs_sub())) == 2  # 全不限 = 原样


async def test_p21_openalex_passes_until_to_api(monkeypatch):
    captured = _capture_get(monkeypatch)
    await OpenAlexProvider().search(
        ["dementia"], date(2026, 1, 1), until_date=date(2026, 12, 31), api_key="K"
    )
    flt = captured[0]["params"]["filter"]
    assert "from_publication_date:2026-01-01" in flt
    assert "to_publication_date:2026-12-31" in flt  # P21 年份上限走服务端过滤


async def test_p21_pubmed_passes_maxdate_to_esearch(monkeypatch):
    captured = []
    from app.services.sources import pubmed as pubmed_mod

    async def fake_get(self, url, **kwargs):
        captured.append({"url": str(url), "params": kwargs.get("params")})
        req = httpx.Request("GET", str(url))
        if "esearch" in str(url):
            return httpx.Response(200, request=req, json={"esearchresult": {"idlist": []}})
        return httpx.Response(200, request=req, text="<PubmedArticleSet></PubmedArticleSet>")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_get)
    monkeypatch.setattr(pubmed_mod, "RATE_LIMIT_SLEEP", 0)  # 测试提速
    await pubmed_mod.PubMedProvider().search(
        ["alzheimer"], date(2026, 1, 1), until_date=date(2026, 6, 30)
    )
    esearch_calls = [c for c in captured if "esearch" in c["url"]]
    assert esearch_calls
    assert esearch_calls[0]["params"]["maxdate"] == "2026/06/30"
    assert esearch_calls[0]["params"]["datetype"] == "pdat"


async def test_p21_doaj_year_until_post_filter(monkeypatch):
    payload = {
        "results": [
            {"id": "d1", "bibjson": {"title": "T1", "year": "2024"}},
            {"id": "d2", "bibjson": {"title": "T2", "year": "2026"}},
        ]
    }

    async def fake_get(self, url, **kwargs):
        req = httpx.Request("GET", str(url))
        return httpx.Response(200, request=req, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    items = await DoajProvider().search(["x"], date(2023, 1, 1), until_date=date(2025, 12, 31))
    assert [i.title for i in items] == ["T1"]  # 2026 超 year_to 被后过滤


# ── P13：NL 语义检索全流程（mock AI 扩词 + mock 源） ──────
class _FakeProvider:
    """模拟单源命中 2 篇（其中 1 篇 P21 被过滤），不走外网。"""

    name = "fake"
    display_name = "Fake"
    key_service = None

    async def search(self, keywords, since_date, until_date=None, api_key=None):
        from app.services.sources import PaperItem

        assert api_key is None  # 无 key_service 不取匙
        return [
            PaperItem(
                title=f"Semantic hit {k}", source="fake", external_id=f"fake-{k}",
                authors=("Alice Zhang",), year=2026, pub_date=date(2026, 10, 28),
                abstract="abstract",
            )
            for k in keywords
        ]


async def test_semantic_search_full_flow(client, monkeypatch):
    headers = await login(client)
    # mock 1：AI 扩词（绕过模型网关）
    import app.routers.papers as papers_router

    async def fake_suggest(db, description):
        assert description.strip() == "阿尔茨海默症早期血液标志物"
        return ["alzheimer biomarker", "blood marker"]

    monkeypatch.setattr(papers_router, "_suggest_keywords", fake_suggest)
    # mock 2：源（单源双命中）
    monkeypatch.setattr(papers_crawl, "get_provider", lambda name: _FakeProvider())
    monkeypatch.setattr(papers_crawl, "RATE_LIMIT_SLEEP", 0)

    resp = await client.post(
        "/papers/semantic-search",
        headers=headers,
        json={"description": "  阿尔茨海默症早期血液标志物  "},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["keywords"] == ["alzheimer biomarker", "blood marker"]
    assert body["added"] == 2
    assert body["runs_id"]

    async with SessionLocal() as db:
        # 结果照常入库 + 归属本人
        papers = (await db.execute(select(Paper))).scalars().all()
        assert len(papers) == 2
        assert all(p.source == "fake" for p in papers)
        links = (await db.execute(select(PaperUser))).scalars().all()
        assert len(links) == 2
        # 写 runs(trigger=semantic)
        run = (await db.execute(select(PaperCrawlRun))).scalars().one()
        assert run.trigger == "semantic"
        assert run.status == "success"
        # 不写订阅词：subscribe_keywords 保持未配置
        row = (
            await db.execute(
                select(UserSetting).where(UserSetting.key == "subscribe_keywords")
            )
        ).scalar_one_or_none()
        assert row is None


async def test_semantic_search_conflict_409(client, monkeypatch):
    headers = await login(client)
    # 直接持锁模拟「已有轮次进行中」
    async with papers_crawl._crawl_lock:
        import app.routers.papers as papers_router

        async def fake_suggest(db, description):
            return ["kw1"]

        monkeypatch.setattr(papers_router, "_suggest_keywords", fake_suggest)
        resp = await client.post(
            "/papers/semantic-search", headers=headers, json={"description": "x 方向"}
        )
    assert resp.status_code == 409, resp.text
