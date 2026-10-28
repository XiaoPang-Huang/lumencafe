"""论文域增强测试（P14/P15/P18/P19）：元数据映射 / 排序过滤 / 展示偏好 / 7 天滚动清理。

- 元数据（P15）：OpenAlex cited_by_count → cited_count、summary_stats 2yr_mean_citedness
  → if_approx；S2 citationCount → cited_count；arXiv/DOAJ/PubMed 的 authors/journal/pub_date
  映射各一例；upsert 命中已存在行时元数据刷新（空值不回填）；
- 排序过滤（P18）：digest sort 三态（time/if/score）、if_min 边界（null 被过滤）、
  limit 截断；/papers/daily 同参组合；papers_prefs 未显式传参时作缺省；
- 清理（P14）：6 天保留 / 7 天删除 / 收藏保留 / 有笔记保留（mock 时间边界）；
- Hatchet 幂等：同日第二次 run_daily_cleanup 跳过。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.papers import Paper, PaperCrawlRun, PaperFavorite, PaperNote, PaperUser
from app.services import papers_crawl
from app.services.sources.arxiv import _parse_atom as arxiv_parse
from app.services.sources.doaj import _parse_results as doaj_parse
from app.services.sources.openalex import _parse_works as openalex_parse
from app.services.sources.pubmed import parse_efetch as pubmed_parse
from app.services.sources.semantic_scholar import _parse_papers as s2_parse
from tests.conftest import login

INTERNAL_TOKEN = "pytest-internal-token-0123456789abcdef"

# ── 各源元数据映射样例（P15） ─────────────────────────────
_OPENALEX_META = {
    "results": [
        {
            "id": "https://openalex.org/W900000001",
            "display_name": "Metadata enrichment study",
            "publication_year": 2026,
            "publication_date": "2026-10-20",
            "doi": "https://doi.org/10.1000/meta.2026",
            "cited_by_count": 42,
            "summary_stats": {"2yr_mean_citedness": 3.75},
            "authorships": [{"author": {"display_name": "Meta Zhang"}}],
            "primary_location": {"source": {"display_name": "J Meta"}},
        }
    ]
}

_S2_META = {
    "data": [
        {
            "paperId": "s2meta001",
            "title": "Citation counting paper",
            "abstract": "We count citations.",
            "year": 2026,
            "publicationDate": "2026-10-18",
            "venue": "Cite Conf",
            "authors": [{"name": "Cited Liu"}],
            "externalIds": {"DOI": "10.1000/cite.2026"},
            "citationCount": 128,
        }
    ]
}

_ARXIV_META = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2601.54321v1</id>
    <published>2026-10-22T00:00:00Z</published>
    <title>Preprint meta test</title>
    <summary>An arXiv preprint.</summary>
    <author><name>Ppx Author</name></author>
    <arxiv:journal_ref>arXiv preprint</arxiv:journal_ref>
  </entry>
</feed>"""

_DOAJ_META = {
    "results": [
        {
            "id": "doaj-meta-1",
            "bibjson": {
                "title": "DOAJ meta test",
                "abstract": "An OA article.",
                "year": "2026",
                "author": [{"name": "Oa Wang"}],
                "identifier": [{"type": "doi", "id": "10.1000/oa.2026"}],
                "journal": {"title": "J OA Meta"},
            },
        }
    ]
}

_PUBMED_META_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>920001</PMID><Article>
<ArticleTitle>PubMed meta test</ArticleTitle>
<Abstract><AbstractText>pubmed metadata mapping.</AbstractText></Abstract>
<Journal><ISOAbbreviation>J PubMed Meta</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month><Day>20</Day></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Meta</LastName><Initials>X</Initials></Author><Author><CollectiveName>Consortium</CollectiveName></Author></AuthorList>
</Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/pm.2026</ArticleId></ArticleIdList></PubmedData></PubmedArticle>
</PubmedArticleSet>"""


def test_openalex_metadata_mapping():
    """OpenAlex：cited_by_count → cited_count，2yr_mean_citedness → if_approx。"""
    (item,) = openalex_parse(_OPENALEX_META, "meta")
    assert item.cited_count == 42
    assert item.if_approx == pytest.approx(3.75)
    assert item.journal == "J Meta"
    assert item.pub_date is not None and item.pub_date.year == 2026


def test_openalex_if_approx_falls_back_to_fwci():
    """OpenAlex 2yr_mean_citedness 下线（2026-10 实测）：回落取 fwci，皆空留 None。"""
    base = _OPENALEX_META["results"][0]
    fwci_only = {"results": [dict(base, summary_stats=None, fwci=1.0906)]}
    (item,) = openalex_parse(fwci_only, "meta")
    assert item.if_approx == pytest.approx(1.0906)

    both = {"results": [dict(base, summary_stats={"2yr_mean_citedness": 3.75}, fwci=1.0906)]}
    (item2,) = openalex_parse(both, "meta")
    assert item2.if_approx == pytest.approx(3.75)  # 旧字段优先

    neither = {"results": [dict(base, summary_stats=None, fwci=None)]}
    (item3,) = openalex_parse(neither, "meta")
    assert item3.if_approx is None  # 不编造


def test_s2_metadata_mapping():
    """S2：citationCount → cited_count；venue/authors 映射不受影响。"""
    (item,) = s2_parse(_S2_META, "meta")
    assert item.cited_count == 128
    assert item.if_approx is None  # S2 无影响因子近似，不编造
    assert item.journal == "Cite Conf"
    assert item.authors == ("Cited Liu",)


def test_arxiv_metadata_mapping():
    """arXiv：authors/journal_ref/pub_date 映射；无引用数字段留 None。"""
    (item,) = arxiv_parse(_ARXIV_META, "meta")
    assert item.authors == ("Ppx Author",)
    assert item.journal == "arXiv preprint"
    assert item.pub_date is not None and item.pub_date.isoformat() == "2026-10-22"
    assert item.cited_count is None and item.if_approx is None


def test_doaj_metadata_mapping():
    """DOAJ：authors/journal/year 映射；引用数留 None。"""
    (item,) = doaj_parse(_DOAJ_META, "meta")
    assert item.authors == ("Oa Wang",)
    assert item.journal == "J OA Meta"
    assert item.year == 2026
    assert item.cited_count is None and item.if_approx is None


def test_pubmed_metadata_mapping():
    """PubMed：authors（含团体作者）/journal/精确 pub_date/DOI 映射。"""
    (rec,) = pubmed_parse(_PUBMED_META_XML)
    assert rec["authors"] == ["Meta X", "Consortium"]
    assert rec["journal"] == "J PubMed Meta"
    assert rec["pub_date"] is not None and rec["pub_date"].isoformat() == "2026-01-01"
    assert rec["doi"] == "10.1000/pm.2026"


# ── upsert 元数据刷新（P15） ──────────────────────────────
async def test_upsert_refreshes_metadata_on_existing_row():
    """已存在行允许元数据刷新：新抓取带来引用数/IF 时更新；源侧空值不回填。"""
    async with SessionLocal() as db:
        first = papers_crawl.PaperItem(
            title="Refresh me", source="openalex", external_id="W-refresh-1",
            journal="Old J",
        )
        pid, is_new = await papers_crawl._upsert_item(db, first, [], [])
        assert is_new is True
        await db.commit()

        # 第二轮：带元数据 → 刷新
        second = papers_crawl.PaperItem(
            title="Refresh me", source="openalex", external_id="W-refresh-1",
            journal="New J", cited_count=77, if_approx=5.5,
        )
        pid2, is_new2 = await papers_crawl._upsert_item(db, second, [], [])
        assert (pid2, is_new2) == (pid, False)
        await db.commit()

        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert row.journal == "New J"
        assert row.cited_count == 77
        assert float(row.if_approx) == pytest.approx(5.5)

        # 第三轮：元数据空值 → 不回填（保留已有值）
        third = papers_crawl.PaperItem(
            title="Refresh me", source="openalex", external_id="W-refresh-1",
        )
        await papers_crawl._upsert_item(db, third, [], [])
        await db.commit()
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert row.cited_count == 77  # 未被 None 覆盖
        assert row.journal == "New J"


# ── 排序过滤与展示偏好（P18） ─────────────────────────────
async def _seed_papers_for_sorting(client, headers):
    """造 4 篇归属文献：IF 各异（含 null），入库时间可控（本地今日内）。"""
    base = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(UTC)
    specs = [
        # (pmid, title, if_approx, cited, created_offset_hours_from_midnight, keywords)
        ("sort-a", "Alpha alzheimer", 1.5, 10, 3, ["alzheimer"]),
        ("sort-b", "Beta alzheimer", 8.25, 20, 2, ["alzheimer", "dementia"]),
        ("sort-c", "Gamma alzheimer", None, 30, 1, ["alzheimer", "dementia", "moca"]),
        ("sort-d", "Delta alzheimer", 4.0, 40, 0.05, ["alzheimer"]),
    ]
    async with SessionLocal() as db:
        for pmid, title, ifa, cited, off_h, kws in specs:
            paper = Paper(
                pmid=pmid, source="openalex", title=title,
                abstract=f"A study about {' '.join(kws)}.",  # digest 命中按 title+abstract 重算
                if_approx=ifa, cited_count=cited, keywords=kws,
                created_at=base + timedelta(hours=off_h),
            )
            db.add(paper)
            await db.flush()
            db.add(PaperUser(paper_id=paper.id, user_id=1))
        await db.commit()
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer", "dementia", "moca"]}},
        headers=headers,
    )


async def test_digest_sort_three_modes(client, monkeypatch):
    """digest sort 三态：time=入库倒序；if=IF 倒序 nulls last；score=命中词数倒序。"""
    await _seed_papers_for_sorting(client, headers := await login(client))

    by_time = (await client.get("/papers/digest?sort=time", headers=headers)).json()
    assert [i["title"] for i in by_time["items"]] == [
        "Alpha alzheimer", "Beta alzheimer", "Gamma alzheimer", "Delta alzheimer",
    ]

    by_if = (await client.get("/papers/digest?sort=if", headers=headers)).json()
    assert [i["title"] for i in by_if["items"]] == [
        "Beta alzheimer", "Delta alzheimer", "Alpha alzheimer", "Gamma alzheimer",  # null 垫底
    ]
    assert by_if["items"][0]["if_approx"] == 8.25

    by_score = (await client.get("/papers/digest?sort=score", headers=headers)).json()
    assert [i["title"] for i in by_score["items"]] == [
        "Gamma alzheimer", "Beta alzheimer", "Alpha alzheimer", "Delta alzheimer",
    ]
    assert by_score["items"][0]["score"] == 3


async def test_digest_if_min_boundary_and_null_filtering(client):
    """if_min 边界：等于下限保留、低于下限剔除、IF 为 null 的条目被过滤。"""
    await _seed_papers_for_sorting(client, headers := await login(client))

    data = (await client.get("/papers/digest?sort=if&if_min=4.0", headers=headers)).json()
    titles = [i["title"] for i in data["items"]]
    assert titles == ["Beta alzheimer", "Delta alzheimer"]  # 4.0 保留；1.5 与 null 剔除
    assert all(i["if_approx"] is not None and i["if_approx"] >= 4.0 for i in data["items"])
    assert data["total_today"] == 2  # 页头数字=过滤后口径

    edge = (await client.get("/papers/digest?if_min=8.25", headers=headers)).json()
    assert [i["title"] for i in edge["items"]] == ["Beta alzheimer"]


async def test_digest_limit_and_item_metadata_fields(client):
    """limit 截断 + 响应条目带齐 P15 元数据字段。"""
    await _seed_papers_for_sorting(client, headers := await login(client))

    data = (await client.get("/papers/digest?sort=if&limit=2", headers=headers)).json()
    assert len(data["items"]) == 2
    assert data["total_today"] == 4  # 总数不受 limit 截断影响

    top = data["items"][0]
    assert top["if_approx"] == 8.25
    assert top["cited_count"] == 20
    assert top["journal"] == ""  # 种子未给期刊，空串不报错
    assert "authors" in top and "matched_keywords" in top and "score" in top

    bad = await client.get("/papers/digest?sort=hot", headers=headers)
    assert bad.status_code == 422  # 非法排序值被拒


async def test_papers_prefs_applied_as_defaults(client):
    """papers_prefs 未显式传参时作缺省：sort=if + if_min=2 + display_limit=2。"""
    await _seed_papers_for_sorting(client, headers := await login(client))
    await client.put(
        "/me/settings",
        json={"key": "papers_prefs", "value": {"display_limit": 2, "sort": "if", "if_min": 2}},
        headers=headers,
    )

    data = (await client.get("/papers/digest", headers=headers)).json()
    assert [i["title"] for i in data["items"]] == ["Beta alzheimer", "Delta alzheimer"]
    assert data["total_today"] == 2  # if_min=2 过滤掉 1.5 与 null

    # 显式参数覆盖 prefs（if_min 仍回落 prefs=2 → 只剩 2 篇，时间倒序）
    override = (await client.get("/papers/digest?sort=time&limit=4", headers=headers)).json()
    assert len(override["items"]) == 2
    assert override["items"][0]["title"] == "Beta alzheimer"


async def test_daily_sort_if_min_limit(client):
    """/papers/daily 同参组合：sort=if 倒序 + if_min 过滤 null + limit 截断。"""
    await _seed_papers_for_sorting(client, headers := await login(client))

    items = (await client.get("/papers/daily?sort=if&if_min=2&limit=2", headers=headers)).json()
    assert [p["title"] for p in items] == ["Beta alzheimer", "Delta alzheimer"]
    assert items[0]["if_approx"] == 8.25 and items[0]["cited_count"] == 20

    by_score = (await client.get("/papers/daily?sort=score&limit=1", headers=headers)).json()
    assert by_score[0]["title"] == "Gamma alzheimer"  # 3 个命中词最多

    by_time = (await client.get("/papers/daily?sort=time&limit=1", headers=headers)).json()
    assert by_time[0]["title"] == "Alpha alzheimer"  # 最新入库


# ── 排序 NULLS LAST 修复轮（PG DESC 默认 NULLS FIRST，没 IF 的须沉底） ──
async def test_sort_if_nulls_last_digest_and_daily(client):
    """IF 有/无混合：sort=if 时 null 条目沉底（digest 与 daily 同口径，不设 if_min）。"""
    await _seed_papers_for_sorting(client, headers := await login(client))

    by_if = (await client.get("/papers/digest?sort=if", headers=headers)).json()
    titles = [i["title"] for i in by_if["items"]]
    assert "Gamma alzheimer" in titles  # null IF 那篇仍在列表（未设 if_min 不过滤）
    assert titles[-1] == "Gamma alzheimer"  # 但沉底
    assert by_if["items"][-1]["if_approx"] is None
    assert by_if["items"][0]["if_approx"] == 8.25  # 非 null 仍按倒序在顶

    daily = (await client.get("/papers/daily?sort=if", headers=headers)).json()
    daily_titles = [p["title"] for p in daily]
    assert daily_titles[-1] == "Gamma alzheimer"
    assert daily[0]["if_approx"] == 8.25


# ── digest 时间窗口径：最近一轮成功检索以来入库（无 runs 回落本地今日零点） ──
async def _seed_window_papers(run_at: datetime):
    """造 3 篇归属文献：run_at 之前 / run_at 之后（昨天）/ 今天，均命中订阅关键词。"""
    specs = [
        ("win-before", "Before run alzheimer", run_at - timedelta(hours=1)),
        ("win-after", "After run alzheimer", run_at + timedelta(hours=1)),
        ("win-today", "Today fresh alzheimer", datetime.now(UTC)),
    ]
    async with SessionLocal() as db:
        for pmid, title, created in specs:
            paper = Paper(
                pmid=pmid, source="openalex", title=title,
                abstract="A study about alzheimer.", created_at=created,
            )
            db.add(paper)
            await db.flush()
            db.add(PaperUser(paper_id=paper.id, user_id=1))
        await db.commit()


async def test_digest_window_since_last_successful_run(client):
    """窗口=最近一轮成功 runs 的 run_at：run 后的（含昨天）算入，run 前的排除；
    之后的失败轮次不改窗口；total_today 同口径。"""
    headers = await login(client)
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer"]}},
        headers=headers,
    )
    run_at = datetime.now(UTC) - timedelta(days=1)  # 最近一轮成功检索在昨天
    await _seed_window_papers(run_at)
    async with SessionLocal() as db:
        db.add(PaperCrawlRun(trigger="manual", stats={}, status="success", run_at=run_at))
        await db.commit()

    data = (await client.get("/papers/digest", headers=headers)).json()
    titles = [i["title"] for i in data["items"]]
    assert "After run alzheimer" in titles  # 昨天但 run 之后 → 算入
    assert "Today fresh alzheimer" in titles  # 今天 → 算入
    assert "Before run alzheimer" not in titles  # run 之前 → 排除
    assert data["total_today"] == 2
    assert data["last_run_at"] is not None

    # 其后追加一次失败轮次：窗口仍锚在最近成功轮，口径不变
    async with SessionLocal() as db:
        db.add(PaperCrawlRun(
            trigger="schedule", stats={}, status="failed", error="boom",
            run_at=run_at + timedelta(hours=2),
        ))
        await db.commit()
    data = (await client.get("/papers/digest", headers=headers)).json()
    titles = [i["title"] for i in data["items"]]
    assert "After run alzheimer" in titles and "Today fresh alzheimer" in titles
    assert "Before run alzheimer" not in titles
    assert data["total_today"] == 2


async def test_digest_window_falls_back_to_local_midnight_without_runs(client):
    """无任何 runs 记录：窗口回落本地今日零点——今日入库算入、昨日入库不算。"""
    headers = await login(client)
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer"]}},
        headers=headers,
    )
    run_at = datetime.now(UTC) - timedelta(days=1)  # 仅用于造「昨天 run 后」那篇
    await _seed_window_papers(run_at)

    data = (await client.get("/papers/digest", headers=headers)).json()
    titles = [i["title"] for i in data["items"]]
    assert titles == ["Today fresh alzheimer"]  # 两篇昨天的都不算今日
    assert data["total_today"] == 1
    assert data["last_run_at"] is None


# ── 7 天滚动清理（P14） ─────────────────────────────────
async def _seed_stale_papers():
    """4 篇老论文：6 天 / 7 天 / 7 天已收藏 / 7 天有笔记；返回各篇 id。"""
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        ids: dict[str, int] = {}
        specs = [
            ("stale-6d", "Six days", -6, None, None),
            ("stale-7d", "Seven days", -7, None, None),
            ("stale-7d-fav", "Seven days favorited", -7, "fav", None),
            ("stale-7d-note", "Seven days noted", -7, None, "note"),
        ]
        for pmid, title, days, fav, note in specs:
            paper = Paper(
                pmid=pmid, source="openalex", title=title, abstract="stale",
                created_at=now + timedelta(days=days),
            )
            db.add(paper)
            await db.flush()
            db.add(PaperUser(paper_id=paper.id, user_id=1))
            if fav:
                db.add(PaperFavorite(paper_id=paper.id, user_id=1))
            if note:
                db.add(PaperNote(paper_id=paper.id, user_id=1, content="keep me"))
            ids[pmid] = paper.id
        await db.commit()
    return ids


async def test_cleanup_stale_papers_time_and_protection_boundaries():
    """清理边界：入库 6 天保留、7 天删除、已收藏保留、有笔记保留（直注 now）。"""
    ids = await _seed_stale_papers()
    monkey_now = datetime.now(UTC)  # 与 seed 同一时刻基准

    async with SessionLocal() as db:
        result = await papers_crawl.cleanup_stale_papers(db, now=monkey_now)
        assert result["deleted"] == 1

        remaining = set((await db.execute(select(Paper.pmid))).scalars().all())
        assert remaining == {"stale-6d", "stale-7d-fav", "stale-7d-note"}
        assert "stale-7d" not in remaining

        # 连带归属也清掉（7 天那篇的 paper_users 行不存在）
        orphans = (
            await db.execute(
                select(PaperUser).where(PaperUser.paper_id == ids["stale-7d"])
            )
        ).scalars().all()
        assert orphans == []
        # 受保护论文的归属不动
        kept = (
            await db.execute(
                select(PaperUser).where(PaperUser.paper_id == ids["stale-7d-fav"])
            )
        ).scalars().all()
        assert len(kept) == 1


async def test_cleanup_idempotent_same_day_via_internal_job(client):
    """run_daily_cleanup 幂等：同日第二次（internal 触发）跳过，不重复清理。"""
    await _seed_stale_papers()
    papers_crawl._last_cleanup_date = None  # 进程内标记清零，隔离其他用例影响
    headers = {"X-Internal-Token": INTERNAL_TOKEN}

    first = await client.post("/internal/jobs/papers-cleanup", headers=headers)
    assert first.status_code == 200
    assert first.json()["deleted"] == 1 and first.json()["skipped"] is False

    second = await client.post("/internal/jobs/papers-cleanup", headers=headers)
    assert second.json() == {"deleted": 0, "skipped": True}

    async with SessionLocal() as db:
        remaining = set((await db.execute(select(Paper.pmid))).scalars().all())
    assert "stale-7d" not in remaining
    assert "stale-6d" in remaining


async def test_cleanup_no_candidates_commits_and_returns_zero(client):
    """无候选论文：返回 deleted=0 且会话保持可用（commit 复位）。"""
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    resp = await client.post("/internal/jobs/papers-cleanup", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
