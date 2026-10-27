"""文献测试（PRD §4.8 + 步 A 多源扩展）：抓取入库（mock 源）/归属隔离/收藏/笔记/解读。

步 A 后抓取改为「按有文献权限的用户 × 勾选源 × 订阅关键词」聚合：
- mock 方式：PubMed 走 sources/pubmed.py 的 esearch/efetch monkeypatch；
  其余源/聚合场景走 papers_crawl.get_provider 假 provider（不真连外网）；
- 用户未配置 subscribe_sources 时默认三源（pubmed/arxiv/openalex），
  所以订阅用户必须显式设置 subscribe_sources=["pubmed"] 才能把抓取限定在 mock 源。
"""

from app.services import llm_gateway, papers_crawl
from app.services.sources import pubmed as pubmed_source
from app.services.sources.base import PaperItem
from tests.conftest import login

INTERNAL_TOKEN = "pytest-internal-token-0123456789abcdef"

_FAKE_EFETCH_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>900001</PMID><Article>
<ArticleTitle>Alzheimer disease biomarker study</ArticleTitle>
<Abstract><AbstractText>We studied alzheimer dementia biomarkers in cohorts.</AbstractText></Abstract>
<Journal><ISOAbbreviation>J Alzheimers Dis</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Zhang</LastName><Initials>XM</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>900002</PMID><Article>
<ArticleTitle>Sleep quality and metabolism</ArticleTitle>
<Abstract><AbstractText>Sleep and metabolic outcomes were measured.</AbstractText></Abstract>
<Journal><ISOAbbreviation>Sleep Med</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Li</LastName><Initials>Y</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


async def _mock_pubmed(monkeypatch, pmids=None):
    """mock NCBI 与中译，返回内部触发所需的 monkeypatch 集合。"""

    async def fake_esearch(client, keyword, retmax, days_back):
        return pmids or ["900001", "900002"]

    async def fake_efetch(client, pmids_arg):
        # fake XML 含两篇，按请求的 pmid 过滤
        import re

        arts = re.findall(r"<PubmedArticle>.*?</PubmedArticle>", _FAKE_EFETCH_XML, re.DOTALL)
        wanted = set(pmids_arg)
        keep = [
            a for a in arts if re.search(r"<PMID>(\d+)</PMID>", a).group(1) in wanted
        ]
        return "<PubmedArticleSet>" + "".join(keep) + "</PubmedArticleSet>"

    async def fake_translate(cfg, messages, timeout=30.0):
        return "这是中文摘要译文。"

    monkeypatch.setattr(pubmed_source, "esearch", fake_esearch)
    monkeypatch.setattr(pubmed_source, "efetch", fake_efetch)
    monkeypatch.setattr(llm_gateway, "chat_once", fake_translate)
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)


class _FakeProvider:
    """步 A 聚合测试用假源：固定返回若干 PaperItem。"""

    def __init__(self, name: str, items: list[PaperItem]):
        self.name = name
        self.display_name = name
        self._items = items
        self.calls: list[list[str]] = []  # 记录收到的关键词，断言隔离用

    async def search(self, keywords, since_date):
        self.calls.append(list(keywords))
        return list(self._items)


def _patch_providers(monkeypatch, providers: dict[str, _FakeProvider]):
    """按源 key 挂假 provider；未覆盖的 key 返回 None（抓取跳过）。

    同时清零进程内当日标记：mark_ran_today 的日期戳跨用例存活
    （monkeypatch 只回滚显式 setattr 的值），不清零会命中同日幂等早退。
    """
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)

    def fake_get_provider(name):
        return providers.get(name)

    monkeypatch.setattr(papers_crawl, "get_provider", fake_get_provider)


async def _trigger(client):
    return await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )


async def _subscribe(client, headers, keywords, sources=None):
    """给当前用户配置订阅关键词与勾选源（未配置源 = 默认三源，会打到未 mock 源）。"""
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": keywords}},
        headers=headers,
    )
    if sources is not None:
        await client.put(
            "/me/settings",
            json={"key": "subscribe_sources", "value": {"sources": sources}},
            headers=headers,
        )


async def test_crawl_and_daily_list(client, monkeypatch):
    await _mock_pubmed(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"], sources=["pubmed"])

    resp = await _trigger(client)
    assert resp.status_code == 200 and resp.json() == {"added": 2}

    # 同日二次触发：双保险去重
    resp = await _trigger(client)
    assert resp.json() == {"added": 0}
    resp = await client.get("/papers/daily", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    alz = next(i for i in items if i["pmid"] == "900001")
    assert alz["tags"] == ["AD"]  # 打标
    assert alz["abstract_zh"] == "这是中文摘要译文。"  # 中译回填
    assert alz["authors"] == ["Zhang XM"]

    # tag JSONB 筛选
    resp = await client.get("/papers/daily?tag=AD", headers=headers)
    assert len(resp.json()) == 1
    resp = await client.get("/papers/daily?tag=PD", headers=headers)
    assert len(resp.json()) == 0


async def test_keyword_attribution_isolation(client, monkeypatch):
    """订阅关键词决定归属：配置关键词的用户拿到文献，未配置回落 env 默认。"""
    await _mock_pubmed(monkeypatch, pmids=["900001"])
    admin = await login(client)
    # researcher 订阅 alzheimer（member 角色自带 app:papers 权限，源限定 pubmed）；
    # admin 未配置关键词 → 无 env 默认时 admin 无归属
    await client.post(
        "/admin/users",
        json={"username": "researcher", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    res = await login(client, "researcher", "pass-123")
    # 显式限定 pubmed：默认三源里的 arxiv/openalex 未挂 fake，真连外网会污染断言
    await _subscribe(client, res, ["alzheimer"], sources=["pubmed"])

    resp = await _trigger(client)
    assert resp.json()["added"] == 1

    res_items = (await client.get("/papers/daily", headers=res)).json()
    assert len(res_items) == 1
    admin_items = (await client.get("/papers/daily", headers=admin)).json()
    assert len(admin_items) == 0  # 未配置且无 env 默认 → 无归属


async def test_crawl_by_user_sources_aggregation(client, monkeypatch):
    """步 A 拍板：A 勾 arXiv、B 勾 PubMed，互不影响；源 × 关键词按用户隔离。"""
    from app.db import SessionLocal
    from app.models.papers import Paper

    arxiv = _FakeProvider(
        "arxiv",
        [
            PaperItem(
                title="Alpha network study",
                authors=("Alice One",),
                abstract="alpha abstract",
                year=2026,
                arxiv_id="2601.00001",
                source="arxiv",
                external_id="2601.00001",
                pub_date=None,
            )
        ],
    )
    pubmed = _FakeProvider(
        "pubmed",
        [
            PaperItem(
                title="Beta clinical trial",
                authors=("Bob Two",),
                abstract="beta alzheimer cohort",
                year=2026,
                source="pubmed",
                external_id="900010",
            )
        ],
    )
    _patch_providers(monkeypatch, {"arxiv": arxiv, "pubmed": pubmed})

    admin = await login(client)
    for username, kw, src in (("ualice", ["alpha"], ["arxiv"]), ("ubob", ["beta"], ["pubmed"])):
        await client.post(
            "/admin/users",
            json={"username": username, "password": "pass-123", "role_ids": []},
            headers=admin,
        )
        h = await login(client, username, "pass-123")
        await _subscribe(client, h, kw, sources=src)

    resp = await _trigger(client)
    assert resp.json() == {"added": 2}

    # 隔离：alice 只见 arXiv 论文，bob 只见 PubMed 论文
    alice = await login(client, "ualice", "pass-123")
    bob = await login(client, "ubob", "pass-123")
    alice_items = (await client.get("/papers/daily", headers=alice)).json()
    bob_items = (await client.get("/papers/daily", headers=bob)).json()
    assert [i["title"] for i in alice_items] == ["Alpha network study"]
    assert [i["title"] for i in bob_items] == ["Beta clinical trial"]
    assert arxiv.calls == [["alpha"]] and pubmed.calls == [["beta"]]

    # papers 表 source 字段正确
    async with SessionLocal() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(Paper))).scalars().all()
        sources = {p.title: p.source for p in rows}
    assert sources == {"Alpha network study": "arxiv", "Beta clinical trial": "pubmed"}


async def test_cross_source_dedup_by_doi(client, monkeypatch):
    """步 A 拍板：同一篇被 arXiv 与 OpenAlex 同时命中（doi 相同）只入库一次。"""
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models.papers import Paper

    arxiv = _FakeProvider(
        "arxiv",
        [
            PaperItem(
                title="Same paper from arXiv",
                authors=("Coco",),
                abstract="dup abstract alzheimer",
                year=2026,
                doi="10.1000/dup.2026",
                arxiv_id="2601.55555",
                source="arxiv",
                external_id="2601.55555",
            )
        ],
    )
    openalex = _FakeProvider(
        "openalex",
        [
            PaperItem(
                title="Same paper from OpenAlex",
                authors=("Coco",),
                abstract="dup abstract alzheimer",
                year=2026,
                doi="10.1000/dup.2026",
                source="openalex",
                external_id="W55555",
            )
        ],
    )
    _patch_providers(monkeypatch, {"arxiv": arxiv, "openalex": openalex})

    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "udup", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    u = await login(client, "udup", "pass-123")
    await _subscribe(client, u, ["dup keyword"], sources=["arxiv", "openalex"])

    resp = await _trigger(client)
    assert resp.json() == {"added": 1}  # 跨源去重：只新增 1 行

    async with SessionLocal() as db:
        count = (await db.execute(select(func.count(Paper.id)))).scalar_one()
    assert count == 1
    items = (await client.get("/papers/daily", headers=u)).json()
    assert len(items) == 1  # 归属也只有一条


async def test_favorite_toggle_and_list(client, monkeypatch):
    await _mock_pubmed(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"], sources=["pubmed"])
    await _trigger(client)
    items = (await client.get("/papers/daily", headers=headers)).json()
    pid = items[0]["id"]

    resp = await client.post(f"/papers/{pid}/save", headers=headers)
    assert resp.json() == {"saved": True}
    resp = await client.post(f"/papers/{pid}/save", headers=headers)
    assert resp.json() == {"saved": False}  # 幂等 toggle
    resp = await client.post(f"/papers/{pid}/save", headers=headers)
    assert resp.json() == {"saved": True}

    favs = (await client.get("/papers/favorites", headers=headers)).json()
    assert len(favs) == 1 and favs[0]["saved"] is True
    daily = (await client.get("/papers/daily", headers=headers)).json()
    assert next(i for i in daily if i["id"] == pid)["saved"] is True

    # 他人收藏列表隔离
    admin2 = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "rfan", "password": "pass-123", "role_ids": []},
        headers=admin2,
    )
    fan = await login(client, "rfan", "pass-123")
    assert (await client.get("/papers/favorites", headers=fan)).json() == []


async def test_note_upsert_and_detail(client, monkeypatch):
    await _mock_pubmed(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"], sources=["pubmed"])
    await _trigger(client)
    pid = (await client.get("/papers/daily", headers=headers)).json()[0]["id"]

    await client.post(f"/papers/{pid}/note", json={"content": "样本量偏小"}, headers=headers)
    await client.post(f"/papers/{pid}/note", json={"content": "样本量偏小，待复现"}, headers=headers)
    detail = (await client.get(f"/papers/{pid}", headers=headers)).json()
    assert detail["note"] == "样本量偏小，待复现"
    assert detail["explanation"] is None  # 未生成时 null


async def test_explain_cache_and_isolation(client, monkeypatch):
    await _mock_pubmed(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"], sources=["pubmed"])
    await _trigger(client)
    pid = (await client.get("/papers/daily", headers=headers)).json()[0]["id"]

    async def fake_explain(cfg, messages, timeout=30.0):
        return "①背景：……②方法：……③发现：……④局限：……"

    monkeypatch.setattr(llm_gateway, "chat_once", fake_explain)
    resp = await client.post(f"/papers/{pid}/explain", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False and "①" in data["content"]

    # 命中缓存：不再调模型
    async def boom(cfg, messages, timeout=30.0):
        raise AssertionError("缓存未命中")

    monkeypatch.setattr(llm_gateway, "chat_once", boom)
    resp = await client.post(f"/papers/{pid}/explain", headers=headers)
    assert resp.json()["cached"] is True

    detail = (await client.get(f"/papers/{pid}", headers=headers)).json()
    assert detail["explanation"] and detail["explanation_model"]

    # 非归属用户 404（不泄露存在性）
    admin2 = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "rstranger", "password": "pass-123", "role_ids": []},
        headers=admin2,
    )
    stranger = await login(client, "rstranger", "pass-123")
    resp = await client.get(f"/papers/{pid}", headers=stranger)
    assert resp.status_code == 404


async def test_explain_no_route_503(client, monkeypatch):
    from app.services import route_service

    await _mock_pubmed(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"], sources=["pubmed"])
    await _trigger(client)
    pid = (await client.get("/papers/daily", headers=headers)).json()[0]["id"]

    async def no_route(db):
        return None

    monkeypatch.setattr(route_service, "resolve_default", no_route)
    resp = await client.post(f"/papers/{pid}/explain", headers=headers)
    assert resp.status_code == 503


# ── 步 A：源清单 + AI 生成订阅关键词 ──────────────────────
async def test_list_paper_sources(client):
    headers = await login(client)
    resp = await client.get("/papers/sources", headers=headers)
    assert resp.status_code == 200
    sources = resp.json()
    assert [s["key"] for s in sources] == [
        "pubmed", "arxiv", "openalex", "semantic_scholar", "doaj",
    ]
    assert all(s["name"] for s in sources)


async def test_suggest_keywords_ok(client, monkeypatch):
    headers = await login(client)

    async def fake_chat(cfg, messages, timeout=30.0):
        assert "JSON" in messages[0]["content"]  # 系统提示词内置
        return '["阿尔茨海默病", "Alzheimer disease", "认知障碍", "biomarker"]'

    monkeypatch.setattr(llm_gateway, "chat_once", fake_chat)
    resp = await client.post(
        "/papers/suggest-keywords",
        json={"description": "我想看老年痴呆早期诊断相关的研究"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["keywords"] == ["阿尔茨海默病", "Alzheimer disease", "认知障碍", "biomarker"]
    # 不写库：subscribe_keywords 未被设置
    me = (await client.get("/me", headers=headers)).json()
    assert "subscribe_keywords" not in me["settings"]


async def test_suggest_keywords_strips_code_fence_and_dedupes(client, monkeypatch):
    headers = await login(client)

    async def fake_chat(cfg, messages, timeout=30.0):
        return '```json\n["重复词", "重复词", " parkinson ", "  "]\n```'

    monkeypatch.setattr(llm_gateway, "chat_once", fake_chat)
    resp = await client.post(
        "/papers/suggest-keywords", json={"description": "帕金森运动症状"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["keywords"] == ["重复词", "parkinson"]  # 去重 + 去空白


async def test_suggest_keywords_parse_failure_502(client, monkeypatch):
    headers = await login(client)

    async def fake_chat(cfg, messages, timeout=30.0):
        return "对不起，我无法生成关键词。"

    monkeypatch.setattr(llm_gateway, "chat_once", fake_chat)
    resp = await client.post(
        "/papers/suggest-keywords", json={"description": "随便说说"}, headers=headers
    )
    assert resp.status_code == 502
    assert "无法解析" in resp.json()["detail"]


async def test_suggest_keywords_no_route_503(client, monkeypatch):
    from app.services import route_service

    headers = await login(client)

    async def no_plan(db, app_key):
        return None

    monkeypatch.setattr(route_service, "resolve_for", no_plan)
    resp = await client.post(
        "/papers/suggest-keywords", json={"description": "随便说说"}, headers=headers
    )
    assert resp.status_code == 503


async def test_papers_registered_in_apps(client):
    headers = await login(client)
    apps = (await client.get("/apps", headers=headers)).json()["apps"]
    papers_app = next((a for a in apps if a["id"] == "papers"), None)
    assert papers_app is not None
    assert papers_app["mode"] == "data" and papers_app["perm_code"] == "app:papers"
