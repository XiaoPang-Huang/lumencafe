"""文献测试（PRD §4.8）：抓取入库（mock NCBI）/归属隔离/收藏 toggle/笔记/解读缓存。"""

from app.services import llm_gateway, papers_crawl
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


async def _mock_crawl(monkeypatch, pmids=None):
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

    monkeypatch.setattr(papers_crawl, "esearch", fake_esearch)
    monkeypatch.setattr(papers_crawl, "efetch", fake_efetch)
    monkeypatch.setattr(llm_gateway, "chat_once", fake_translate)
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)


async def _trigger(client):
    return await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )


async def _subscribe(client, headers, keywords):
    """给当前用户配置订阅关键词（未配置的用户抓不到文献）。"""
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": keywords}},
        headers=headers,
    )


async def test_crawl_and_daily_list(client, monkeypatch):
    await _mock_crawl(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"])

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
    await _mock_crawl(monkeypatch, pmids=["900001"])
    admin = await login(client)
    # researcher 订阅 alzheimer；admin 未配置 → 无 env 默认时 admin 无归属
    await client.post(
        "/admin/users",
        json={"username": "researcher", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    res = await login(client, "researcher", "pass-123")
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer"]}},
        headers=res,
    )

    resp = await _trigger(client)
    assert resp.json()["added"] == 1

    res_items = (await client.get("/papers/daily", headers=res)).json()
    assert len(res_items) == 1
    admin_items = (await client.get("/papers/daily", headers=admin)).json()
    assert len(admin_items) == 0  # 未配置且无 env 默认 → 无归属


async def test_favorite_toggle_and_list(client, monkeypatch):
    await _mock_crawl(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"])
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
    await _mock_crawl(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"])
    await _trigger(client)
    pid = (await client.get("/papers/daily", headers=headers)).json()[0]["id"]

    await client.post(f"/papers/{pid}/note", json={"content": "样本量偏小"}, headers=headers)
    await client.post(f"/papers/{pid}/note", json={"content": "样本量偏小，待复现"}, headers=headers)
    detail = (await client.get(f"/papers/{pid}", headers=headers)).json()
    assert detail["note"] == "样本量偏小，待复现"
    assert detail["explanation"] is None  # 未生成时 null


async def test_explain_cache_and_isolation(client, monkeypatch):
    await _mock_crawl(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"])
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

    await _mock_crawl(monkeypatch)
    headers = await login(client)
    await _subscribe(client, headers, ["alzheimer"])
    await _trigger(client)
    pid = (await client.get("/papers/daily", headers=headers)).json()[0]["id"]

    async def no_route(db):
        return None

    monkeypatch.setattr(route_service, "resolve_default", no_route)
    resp = await client.post(f"/papers/{pid}/explain", headers=headers)
    assert resp.status_code == 503


async def test_papers_registered_in_apps(client):
    headers = await login(client)
    apps = (await client.get("/apps", headers=headers)).json()["apps"]
    papers_app = next((a for a in apps if a["id"] == "papers"), None)
    assert papers_app is not None
    assert papers_app["mode"] == "data" and papers_app["perm_code"] == "app:papers"
