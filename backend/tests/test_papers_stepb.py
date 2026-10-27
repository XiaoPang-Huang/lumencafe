"""论文域步 B 测试：页内 digest / 立即检索 crawl-now / runs 表 / Hatchet 降级。

- digest：今日命中口径（本地今日零点 × 本人归属 × 当前订阅关键词重算）、
  多用户隔离、高相关边界（命中 1 词 vs 2 词）、last_run 回读、旧论文不入 digest；
- crawl-now：force 跳过同日幂等且入库幂等、进程内锁 409、per_source 返回；
- runs 表：schedule/manual 两种 trigger 都落行、stats 各源命中数；
- pipeline：未配置 HATCHET_CLIENT_TOKEN 时 start() 返回 False（降级不炸）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models.papers import Paper, PaperCrawlRun
from app.services import llm_gateway, papers_crawl
from app.services.sources import pubmed as pubmed_source
from tests.conftest import login

INTERNAL_TOKEN = "pytest-internal-token-0123456789abcdef"  # 与 conftest 注入的 LUMEN_INTERNAL_TOKEN 一致

# 两篇假文献：一篇摘要只命中 alzheimer（低相关），一篇命中 alzheimer+dementia（高相关）
_FAKE_EFETCH_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>910001</PMID><Article>
<ArticleTitle>Alzheimer biomarker cohort</ArticleTitle>
<Abstract><AbstractText>We studied alzheimer biomarkers in cohorts.</AbstractText></Abstract>
<Journal><ISOAbbreviation>J Alzheimers Dis</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Zhang</LastName><Initials>XM</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>910002</PMID><Article>
<ArticleTitle>Dementia care pathway</ArticleTitle>
<Abstract><AbstractText>alzheimer dementia care pathway analysis.</AbstractText></Abstract>
<Journal><ISOAbbreviation>Dementia</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Li</LastName><Initials>Y</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


async def _mock_pubmed_digest(monkeypatch):
    """mock NCBI 与中译：返回两篇固定假文献；清零当日幂等标记。"""

    async def fake_esearch(client, keyword, retmax, days_back):
        return ["910001", "910002"]

    async def fake_efetch(client, pmids_arg):
        import re

        arts = re.findall(r"<PubmedArticle>.*?</PubmedArticle>", _FAKE_EFETCH_XML, re.DOTALL)
        wanted = set(pmids_arg)
        keep = [
            a for a in arts if re.search(r"<PMID>(\d+)</PMID>", a).group(1) in wanted
        ]
        return "<PubmedArticleSet>" + "".join(keep) + "</PubmedArticleSet>"

    async def fake_translate(cfg, messages, timeout=30.0):
        return "中文摘要译文。"

    monkeypatch.setattr(pubmed_source, "esearch", fake_esearch)
    monkeypatch.setattr(pubmed_source, "efetch", fake_efetch)
    monkeypatch.setattr(llm_gateway, "chat_once", fake_translate)
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)


async def _subscribe_alzheimer_dementia(client, headers):
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer", "dementia"]}},
        headers=headers,
    )
    await client.put(
        "/me/settings",
        json={"key": "subscribe_sources", "value": {"sources": ["pubmed"]}},
        headers=headers,
    )


async def test_digest_today_hits_and_high_relevance_boundary(client, monkeypatch):
    """digest 口径：今日入库 ∩ 本人归属 ∩ 命中当前关键词；命中 1 词低相关、2 词高相关。"""
    await _mock_pubmed_digest(monkeypatch)
    headers = await login(client)
    await _subscribe_alzheimer_dementia(client, headers)

    resp = await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    assert resp.json() == {"added": 2}

    resp = await client.get("/papers/digest", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_today"] == 2
    assert data["high_relevance_count"] == 1
    assert data["last_run_status"] == "success"
    assert data["last_run_at"] is not None

    by_title = {i["title"]: i for i in data["items"]}
    low = by_title["Alzheimer biomarker cohort"]
    assert low["matched_keywords"] == ["alzheimer"]  # 保序去重
    assert low["score"] == 1
    assert low["is_high_relevance"] is False  # 边界：1 词 < 阈值 2
    assert low["source"] == "pubmed"
    assert low["year"] == 2026
    assert low["url"] == "https://pubmed.ncbi.nlm.nih.gov/910001/"

    high = by_title["Dementia care pathway"]
    assert high["matched_keywords"] == ["alzheimer", "dementia"]
    assert high["score"] == 2
    assert high["is_high_relevance"] is True  # 边界：2 词 ≥ 阈值 2


async def test_digest_multi_user_isolation(client, monkeypatch):
    """digest 归属隔离：用户 A 只见自己订阅抓到的文献；未命中关键词的用户 digest 为空。"""
    await _mock_pubmed_digest(monkeypatch)
    admin = await login(client)
    await client.post(
        "/admin/users",
        json={"username": "digestb", "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    b = await login(client, "digestb", "pass-123")
    await _subscribe_alzheimer_dementia(client, b)  # 只有 digestb 订阅并归属

    await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )

    b_data = (await client.get("/papers/digest", headers=b)).json()
    assert b_data["total_today"] == 2

    admin_data = (await client.get("/papers/digest", headers=admin)).json()
    # admin 无归属（无订阅关键词且无 env 默认）→ 即使库里今日有文献也不出现在 digest
    assert admin_data["total_today"] == 0
    assert admin_data["items"] == []


async def test_digest_empty_before_any_run_and_excludes_old_papers(client, monkeypatch):
    """尚无抓取轮次：last_run 为 null、items 空；昨日入库的论文不入今日 digest。"""
    await _mock_pubmed_digest(monkeypatch)
    headers = await login(client)

    empty = (await client.get("/papers/digest", headers=headers)).json()
    assert empty["last_run_at"] is None
    assert empty["last_run_status"] == ""
    assert empty["total_today"] == 0

    await _subscribe_alzheimer_dementia(client, headers)
    await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    assert (await client.get("/papers/digest", headers=headers)).json()["total_today"] == 2

    # 把其中一篇改成昨天入库 → 今日 digest 只剩 1 篇
    async with SessionLocal() as db:
        await db.execute(
            update(Paper)
            .where(Paper.pmid == "910001")
            .values(created_at=datetime.now(UTC) - timedelta(days=1))
        )
        await db.commit()
    data = (await client.get("/papers/digest", headers=headers)).json()
    assert data["total_today"] == 1
    assert data["items"][0]["title"] == "Dementia care pathway"


async def test_crawl_now_writes_manual_run_and_is_idempotent(client, monkeypatch):
    """立即检索：force 跳同日幂等（第二轮 added=0 但不报错），写 runs(trigger=manual)。"""
    await _mock_pubmed_digest(monkeypatch)
    headers = await login(client)
    await _subscribe_alzheimer_dementia(client, headers)

    resp = await client.post("/papers/crawl-now", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] == 2
    assert data["per_source"] == {"pubmed": 2}
    runs_id = data["runs_id"]

    async with SessionLocal() as db:
        run = (
            await db.execute(select(PaperCrawlRun).where(PaperCrawlRun.id == runs_id))
        ).scalar_one()
    assert run.trigger == "manual"
    assert run.status == "success"
    assert run.stats["per_source"]["pubmed"] == {"fetched": 2, "added": 2}
    assert run.stats["added"] == 2

    # 同日第二轮（内部触发应被 Q11 幂等挡住）+ 手动再跑：入库幂等，新增 0
    resp = await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    assert resp.json() == {"added": 0}
    resp = await client.post("/papers/crawl-now", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["added"] == 0  # 幂等：不重复建行

    # papers 仍只有 2 篇；runs 累计 3 行（2 manual + 0 个 schedule——内部触发被幂等跳过不落行）
    async with SessionLocal() as db:
        papers_count = len((await db.execute(select(Paper))).scalars().all())
        runs = (await db.execute(select(PaperCrawlRun))).scalars().all()
    assert papers_count == 2
    assert len(runs) == 2  # 两次 crawl-now 各一行；被跳过的内部触发不写 runs
    assert all(r.trigger == "manual" for r in runs)


async def test_schedule_run_writes_runs_row(client, monkeypatch):
    """内部触发的 schedule 轮次同样落 runs 行（trigger=schedule）。"""
    await _mock_pubmed_digest(monkeypatch)
    headers = await login(client)
    await _subscribe_alzheimer_dementia(client, headers)
    await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    async with SessionLocal() as db:
        run = (await db.execute(select(PaperCrawlRun))).scalar_one()
    assert run.trigger == "schedule"
    assert run.status == "success"
    assert run.error is None
    assert run.stats["users"] == 1


async def test_crawl_now_conflict_when_lock_held(client, monkeypatch):
    """进程内 asyncio 锁：轮次进行中再点「立即检索」返回 409，不叠加第二轮。"""
    await _mock_pubmed_digest(monkeypatch)
    headers = await login(client)
    await _subscribe_alzheimer_dementia(client, headers)

    await papers_crawl._crawl_lock.acquire()
    try:
        resp = await client.post("/papers/crawl-now", headers=headers)
        assert resp.status_code == 409
        assert "抓取" in resp.json()["detail"]
    finally:
        papers_crawl._crawl_lock.release()

    async with SessionLocal() as db:
        runs = (await db.execute(select(PaperCrawlRun))).scalars().all()
    assert runs == []  # 被锁挡住的请求没有产生轮次


async def test_pipeline_degrades_without_config(client):
    """未配置 HATCHET_CLIENT_TOKEN：pipeline 接线惰性跳过，返回 False 不炸。"""
    from app.services import pipeline

    assert pipeline.is_configured() is False
    assert pipeline.start() is False
    # 未接线时 stop 也是 no-op
    pipeline.stop()
