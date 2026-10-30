"""论文域轮②测试（P25/P26/P28）：文献导入 + 解析入口收紧 + 双进度条。

- 导入两路（mock arXiv Atom / Crossref / Unpaywall / MinerU）：
  PDF 上传（落 COS 断言 + 自动进 library + 触发解析状态机）；
  arXiv / DOI 粘贴（元数据起表 + OA 下载 + 解析）；
- 失败路径（拍板 P25「下载失败必须通知用户」）：条目落 import 失败态
  （papers.origin=import + parse_status=failed + parse_error 记原因）且接口
  返回明确失败信息；元数据拉取失败同口径；请求非法（超大/非 PDF/标识符
  不识）→ 422 不落条目；同用户重复导入同一 arXiv/DOI 幂等直返；
- 解析入口收紧（P28）：collect-parse 非库内 → 403，库内 → 200；
- 解析进度（P26）：papers.parse_phase 随状态机推进（失败保留在出错段）；
  GET /papers/library/parsing 返回非 done 列表含 phase + 失败原因；
- 检索进度条（P26）：runs 轮始 insert + 轮内 update（phase/关键词计数/
  per_source）；GET /papers/crawl-now/status idle / running / done 三态。
"""

import asyncio
import base64
import re

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.papers import Paper, PaperCrawlRun, PaperLibrary
from app.models.user import User
from app.services import paper_import, paper_parse, papers_crawl
from app.services.sources import pubmed as pubmed_source
from tests.conftest import login
from tests.test_papers_parse import (
    FakeHttpClient,
    SpyStorage,
    _add_mineru_key,
    _FakeResp,
    _mineru_routes,
)

_FAKE_PDF = b"%PDF-1.4\nfake imported pdf\n%%EOF"

# arXiv Atom 响应（id_list 查询单条命中）
_ARXIV_ATOM = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry>
<id>http://arxiv.org/abs/2401.12345v1</id>
<updated>2024-01-16T00:00:00Z</updated>
<published>2024-01-15T00:00:00Z</published>
<title>Imported arXiv Paper Title</title>
<summary>We studied imported biomarkers in cohorts.</summary>
<author><name>Alice Wang</name></author>
<author><name>Bob Li</name></author>
<arxiv:doi>10.1000/arxiv.2024</arxiv:doi>
<arxiv:journal_ref>J Imported 2024</arxiv:journal_ref>
</entry>
</feed>"""

_ARXIV_ATOM_NOT_FOUND = """<feed xmlns="http://www.w3.org/2005/Atom">
<title>Error</title>
</feed>"""

# Crossref works 响应
_CROSSREF_WORKS = {
    "status": "ok",
    "message": {
        "DOI": "10.1000/xyz.2026",
        "title": ["Crossref Imported Title"],
        "container-title": ["J Crossref"],
        "issued": {"date-parts": [[2026, 3, 1]]},
        "author": [{"given": "Carol", "family": "Zhang"}],
        "is-referenced-by-count": 42,
        "abstract": "<jats:p>Jats abstract text here.</jats:p>",
        "URL": "https://doi.org/10.1000/xyz.2026",
    },
}


async def _async(value):
    return value


def _patch_http(monkeypatch, fake: FakeHttpClient, spy: SpyStorage | None = None) -> None:
    """导入 + 解析链路共用的假总机/假存储接线。"""
    monkeypatch.setattr(paper_import, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    if spy is not None:
        monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))


# ── 标识符识别 / 文件名起表（纯函数）─────────────────────────
def test_classify_identifier_forms():
    assert paper_import.classify_identifier("2401.12345") == ("arxiv", "2401.12345")
    assert paper_import.classify_identifier("2401.12345v3") == ("arxiv", "2401.12345")
    assert paper_import.classify_identifier("arXiv:2401.12345") == ("arxiv", "2401.12345")
    assert paper_import.classify_identifier("https://arxiv.org/abs/2401.12345") == (
        "arxiv", "2401.12345",
    )
    assert paper_import.classify_identifier("10.1000/xyz.2026") == ("doi", "10.1000/xyz.2026")
    assert paper_import.classify_identifier("https://doi.org/10.1000/xyz.2026") == (
        "doi", "10.1000/xyz.2026",
    )
    with pytest.raises(paper_import.ImportInputError):
        paper_import.classify_identifier("not-a-real-thing")
    with pytest.raises(paper_import.ImportInputError):
        paper_import.classify_identifier("")


def test_title_from_filename():
    assert paper_import.title_from_filename("attention_is_all_you_need.pdf") == (
        "attention is all you need"
    )
    assert paper_import.title_from_filename("C:\\docs\\My-Paper_v2.PDF") == "My Paper v2"
    assert paper_import.title_from_filename(".pdf") == "导入的 PDF 文献"


# ── PDF 上传导入 ─────────────────────────────────────────
async def test_import_pdf_success_stores_and_parses(client, monkeypatch):
    """PDF 上传：条目落库（origin=import）+ 自动进 library + 解析状态机全链 done。"""
    await _add_mineru_key()
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes())
    _patch_http(monkeypatch, fake, spy)
    headers = await login(client)

    b64 = base64.b64encode(_FAKE_PDF).decode()
    resp = await client.post(
        "/papers/library/import",
        json={"kind": "pdf", "filename": "attention_is_all_you_need.pdf", "pdf_base64": b64},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse_status"] == "done"
    assert body["parse_error"] is None
    assert body["parse_phase"] is None  # 完成清空
    pid = body["paper_id"]

    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert paper.origin == "import"
        assert paper.source == "import"
        assert paper.title == "attention is all you need"  # 元数据从文件名起表
        assert paper.parsed_at is not None
        # 自动进 library（added_via=import）
        lib = (await db.execute(
            select(PaperLibrary).where(PaperLibrary.paper_id == pid)
        )).scalar_one()
        assert lib.added_via == "import"

    # COS 落件断言：PDF 年月分层 + 解析三件套（P20），app 恒 papers（P11）
    keys = [k for _, k, _ in spy.puts]
    assert re.fullmatch(rf"pdfs/\d{{4}}/\d{{2}}/{pid}\.pdf", keys[0]), keys
    assert keys[1:] == [
        f"parsed/{pid}/full.md",
        f"parsed/{pid}/content_list.json",
        f"parsed/{pid}/meta.json",
    ]
    # PDF 上传路不再发外部下载请求（全文来自上传）
    assert not any("arxiv.org" in u or "unpaywall.org" in u for m, u in fake.calls)


async def test_import_pdf_rejects_oversize_and_non_pdf(client, monkeypatch):
    """请求非法 → 422 且不落条目：超 30MB / 内容非 PDF。"""
    headers = await login(client)
    monkeypatch.setattr(paper_parse, "MAX_PDF_BYTES", 64)  # 缩小上限让用例轻量

    big = base64.b64encode(b"x" * 100).decode()
    resp = await client.post(
        "/papers/library/import",
        json={"kind": "pdf", "filename": "big.pdf", "pdf_base64": big},
        headers=headers,
    )
    assert resp.status_code == 422 and "上限" in resp.json()["detail"]

    not_pdf = base64.b64encode(b"<html>not a pdf</html>").decode()
    resp = await client.post(
        "/papers/library/import",
        json={"kind": "pdf", "filename": "fake.pdf", "pdf_base64": not_pdf},
        headers=headers,
    )
    assert resp.status_code == 422 and "PDF" in resp.json()["detail"]

    async with SessionLocal() as db:
        assert (await db.execute(select(Paper))).scalars().all() == []  # 不落条目


# ── arXiv / DOI 粘贴导入（成功路）─────────────────────────
async def test_import_arxiv_success(client, monkeypatch):
    """arXiv 粘贴：Atom 元数据起表 + abs 页落地 + pdf 直链下载 + 解析 done。"""
    await _add_mineru_key()
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://export.arxiv.org/api/query"): _FakeResp(content=_ARXIV_ATOM.encode()),
        ("GET", "https://arxiv.org/pdf/2401.12345"): _FakeResp(content=_FAKE_PDF),
    }))
    _patch_http(monkeypatch, fake, spy)
    headers = await login(client)

    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "arXiv:2401.12345"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse_status"] == "done"
    assert body["title"] == "Imported arXiv Paper Title"
    pid = body["paper_id"]

    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert paper.pmid == "arxiv:2401.12345"
        assert paper.origin == "import" and paper.source == "arxiv"
        assert paper.url == "https://arxiv.org/abs/2401.12345"
        assert paper.doi == "10.1000/arxiv.2024"
        assert paper.authors == ["Alice Wang", "Bob Li"]
        assert paper.journal == "J Imported 2024"
        assert str(paper.pub_date) == "2024-01-15"
        lib = (await db.execute(
            select(PaperLibrary).where(PaperLibrary.paper_id == pid)
        )).scalar_one()
        assert lib.added_via == "import"

    # 同用户重复导入同一 arXiv ID：幂等直返同一篇，不重复建行
    resp2 = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "2401.12345"},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["paper_id"] == pid
    async with SessionLocal() as db:
        rows = (await db.execute(select(Paper).where(Paper.pmid == "arxiv:2401.12345"))).scalars().all()
        assert len(rows) == 1


async def test_import_doi_success_via_crossref_and_unpaywall(client, monkeypatch):
    """DOI 粘贴：Crossref 元数据 + Unpaywall 补链下载 + 解析 done。"""
    await _add_mineru_key()
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://api.crossref.org/works/10.1000/xyz.2026"): _FakeResp(
            json_data=_CROSSREF_WORKS
        ),
        ("GET", "https://api.unpaywall.org/v2/10.1000/xyz.2026"): _FakeResp(
            json_data={"best_oa_location": {"url_for_pdf": "https://oa.example/doi.pdf"}}
        ),
        ("GET", "https://oa.example/doi.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    _patch_http(monkeypatch, fake, spy)
    headers = await login(client)

    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "https://doi.org/10.1000/xyz.2026"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse_status"] == "done"
    pid = body["paper_id"]

    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert paper.pmid == "doi:10.1000/xyz.2026"
        assert paper.source == "doi"
        assert paper.title == "Crossref Imported Title"
        assert paper.journal == "J Crossref"
        assert paper.cited_count == 42
        assert "Jats abstract text here." in paper.abstract  # JATS 粗去标签
        assert paper.url == "https://doi.org/10.1000/xyz.2026"
        assert str(paper.pub_date) == "2026-03-01"


# ── 失败路径（P25：条目落 import 失败态 + 原因可见）──────────
async def test_import_arxiv_download_fails_marks_failed_with_reason(client, monkeypatch):
    """arXiv 全文下载失败：条目仍落库（failed + 原因），接口返回明确失败信息。"""
    await _add_mineru_key()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://export.arxiv.org/api/query"): _FakeResp(content=_ARXIV_ATOM.encode()),
        ("GET", "https://arxiv.org/pdf/2401.12345"): _FakeResp(status_code=404),
    }))
    _patch_http(monkeypatch, fake, SpyStorage())
    headers = await login(client)

    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "2401.12345"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text  # 条目已落库：200 携失败态
    body = resp.json()
    assert body["parse_status"] == "failed"
    assert "全文下载失败" in (body["parse_error"] or "")

    pid = body["paper_id"]
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert paper.origin == "import" and paper.parse_status == "failed"
        assert "全文下载失败" in (paper.parse_error or "")
        assert paper.title == "Imported arXiv Paper Title"  # 元数据已起表
        # 失败条目保留在 library（P25：失败保留可重试）
        lib = (await db.execute(
            select(PaperLibrary).where(PaperLibrary.paper_id == pid)
        )).scalar_one()
        assert lib.added_via == "import"


async def test_import_arxiv_metadata_not_found_fails(client, monkeypatch):
    """arXiv 元数据 404：条目落 failed 态 + 「未找到」原因。"""
    fake = FakeHttpClient({
        ("GET", "https://export.arxiv.org/api/query"): _FakeResp(
            content=_ARXIV_ATOM_NOT_FOUND.encode()
        ),
    })
    _patch_http(monkeypatch, fake)
    headers = await login(client)

    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "2401.99999"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parse_status"] == "failed"
    assert "未找到" in (body["parse_error"] or "")


async def test_import_doi_no_oa_location_fails_with_reason(client, monkeypatch):
    """DOI 无开放获取全文（Unpaywall 空）：条目落 failed 态 + 原因可见。"""
    fake = FakeHttpClient({
        ("GET", "https://api.crossref.org/works/10.1000/xyz.2026"): _FakeResp(
            json_data=_CROSSREF_WORKS
        ),
        ("GET", "https://api.unpaywall.org/v2/10.1000/xyz.2026"): _FakeResp(
            json_data={"best_oa_location": None, "first_oa_location": None}
        ),
    })
    _patch_http(monkeypatch, fake)
    headers = await login(client)

    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "10.1000/xyz.2026"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parse_status"] == "failed"
    assert body["parse_error"]


async def test_import_identifier_unrecognized_422(client):
    headers = await login(client)
    resp = await client.post(
        "/papers/library/import",
        json={"kind": "identifier", "identifier": "hello world"},
        headers=headers,
    )
    assert resp.status_code == 422


# ── 解析入口收紧（P28）：collect-parse 仅库内 ────────────────
async def test_collect_parse_requires_library_membership(client, monkeypatch):
    """非库内 → 403；加入后 → 200。解析入口收紧（拍板 P28）+ P30 全文前置已就绪。"""
    await _add_mineru_key()
    pid = await _make_owned_paper("crawl", "https://oa.example/p28.pdf")
    fake = FakeHttpClient(_mineru_routes())
    spy = SpyStorage()
    spy.seed_pdf(pid)  # P30：解析只读 COS，全文由获取/上传独立动作就绪
    _patch_http(monkeypatch, fake, spy)
    import app.routers.papers as papers_router

    monkeypatch.setattr(papers_router, "get_storage", lambda db: _async(spy))
    headers = await login(client)

    resp = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert resp.status_code == 403

    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperLibrary(paper_id=pid, user_id=uid, added_via="crawl"))
        await db.commit()
    resp = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["parse_status"] == "done"


async def _make_owned_paper(pmid: str, url: str) -> int:
    from app.models.papers import PaperUser

    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        paper = Paper(
            pmid=pmid, source="pubmed", title=f"Paper {pmid}", abstract="a",
            journal="J", url=url, user_id=uid,
        )
        db.add(paper)
        await db.commit()
        await db.refresh(paper)
        db.add(PaperUser(paper_id=paper.id, user_id=uid))
        await db.commit()
        return paper.id


# ── 解析进度（P26）：parse_phase + /library/parsing ─────────
async def test_parse_phase_written_and_parsing_list(client, monkeypatch):
    """状态机写 parse_phase（失败保留在出错段）；/library/parsing 返回非 done 含 phase。"""
    # MinerU 未配置：失败停在 upload 段（全文已在 COS、MinerU 凭证缺失）
    pid_failed = await _make_owned_paper("phase-fail", "https://oa.example/f.pdf")
    fake = FakeHttpClient({})
    spy = SpyStorage()
    spy.seed_pdf(pid_failed)  # P30：全文就绪（获取/上传独立动作），解析只读 COS
    _patch_http(monkeypatch, fake, spy)
    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid_failed, 1)
    assert result["parse_status"] == "failed"
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid_failed))).scalar_one()
        assert paper.parse_phase == "upload"  # 失败保留在出错段

    # pending / running 条目直接置态，验证解析中列表口径
    uid = None
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        for pmid, status, phase in (
            ("phase-pending", "pending", "queue"),
            ("phase-running", "running", "parsing"),
            ("phase-done", "done", None),
        ):
            paper = Paper(
                pmid=pmid, source="pubmed", title=f"T {pmid}", abstract="a",
                user_id=uid, parse_status=status, parse_phase=phase,
            )
            db.add(paper)
            await db.commit()
            await db.refresh(paper)
            db.add(PaperLibrary(paper_id=paper.id, user_id=uid, added_via="crawl"))
            await db.commit()
        # done 那篇补一条 failed 项验证错误原因随列表可见
        failed_lib = (await db.execute(
            select(Paper).where(Paper.pmid == "phase-fail")
        )).scalar_one()
        db.add(PaperLibrary(paper_id=failed_lib.id, user_id=uid, added_via="crawl"))
        await db.commit()

    headers = await login(client)
    items = (await client.get("/papers/library/parsing", headers=headers)).json()
    by_pmid = {}
    async with SessionLocal() as db:
        rows = (await db.execute(select(Paper.pmid, Paper.id))).all()
        by_id = {pid: pmid for pmid, pid in rows}
    for it in items:
        by_pmid[by_id[it["id"]]] = it
    assert "phase-pending" in by_pmid and by_pmid["phase-pending"]["parse_phase"] == "queue"
    assert "phase-running" in by_pmid and by_pmid["phase-running"]["parse_phase"] == "parsing"
    assert "phase-done" not in by_pmid  # done 不在解析中列表
    assert "phase-fail" in by_pmid
    assert "MinerU 未配置" in (by_pmid["phase-fail"]["parse_error"] or "")


# ── 检索进度条（P26）：runs 轮内 progress + status 轮询 ──────
async def _mock_pubmed_slow(monkeypatch, delay: float = 0.3):
    """带延迟的 PubMed 假源：让「轮内 running」状态可被观测。"""

    async def fake_esearch(client, keyword, retmax, days_back):
        await asyncio.sleep(delay)
        return ["920001"]

    async def fake_efetch(client, pmids_arg):
        return (
            "<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>920001</PMID>"
            "<Article><ArticleTitle>Slow alzheimer study</ArticleTitle>"
            "<Abstract><AbstractText>alzheimer slow cohort.</AbstractText></Abstract>"
            "<Journal><ISOAbbreviation>J Slow</ISOAbbreviation><JournalIssue><PubDate>"
            "<Year>2026</Year></PubDate></JournalIssue></Journal>"
            "<AuthorList><Author><LastName>Slow</LastName><Initials>S</Initials></Author>"
            "</AuthorList></Article></MedlineCitation></PubmedArticle>"
            "</PubmedArticleSet>"
        )

    monkeypatch.setattr(pubmed_source, "esearch", fake_esearch)
    monkeypatch.setattr(pubmed_source, "efetch", fake_efetch)
    monkeypatch.setattr(papers_crawl, "_last_run_date", None)


async def test_crawl_status_idle_then_done_with_progress(client, monkeypatch):
    """status 三态：无轮次 idle → 轮内 running（progress 逐源推进）→ 轮末 done。"""
    headers = await login(client)
    resp = await client.get("/papers/crawl-now/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "idle"  # 无运行返回 idle
    assert resp.json()["progress"] is None

    await _mock_pubmed_slow(monkeypatch, delay=0.4)
    await client.put(
        "/me/settings",
        json={"key": "subscribe_keywords", "value": {"keywords": ["alzheimer"]}},
        headers=headers,
    )
    await client.put(
        "/me/settings",
        json={"key": "subscribe_sources", "value": {"sources": ["pubmed"]}},
        headers=headers,
    )

    async def _run():
        async with SessionLocal() as db:
            return await papers_crawl.run_manual_crawl(db)

    task = asyncio.create_task(_run())
    # 轮内观测：runs 行已 insert 且 status=running、progress.phase=fetching
    seen_running = False
    for _ in range(50):
        await asyncio.sleep(0.05)
        async with SessionLocal() as db:
            run = (
                await db.execute(select(PaperCrawlRun).order_by(PaperCrawlRun.id.desc()).limit(1))
            ).scalar_one_or_none()
        if run is not None and run.status == "running":
            seen_running = True
            assert run.progress["phase"] == "fetching"
            assert run.progress["total_keywords"] >= 1
            assert run.progress["done_keywords"] == 0
            break
    result = await task
    assert result["added"] == 1
    assert seen_running, "轮内应能观测到 running 态 runs 行（轮始 insert）"

    # 轮询接口终态：done + progress.phase=done + per_source 计数
    resp = await client.get("/papers/crawl-now/status", headers=headers)
    body = resp.json()
    assert body["state"] == "done"
    assert body["progress"]["phase"] == "done"
    assert body["progress"]["done_keywords"] == body["progress"]["total_keywords"]
    assert body["per_source"] == {"pubmed": 1}
    assert body["added"] == 1
    assert body["runs_id"] == result["runs_id"]

    # 失败轮同样落 failed 态 + error（原位更新同一行，不产生第二行）
    async def _boom(*args, **kwargs):
        raise RuntimeError("源炸了")

    monkeypatch.setattr(pubmed_source, "esearch", _boom)
    async with SessionLocal() as db:
        failed_run = await papers_crawl.run_manual_crawl(db)
    assert failed_run["added"] == 0
    resp = await client.get("/papers/crawl-now/status", headers=headers)
    body = resp.json()
    assert body["state"] == "failed"
    assert "源炸了" in (body["error"] or "")
    async with SessionLocal() as db:
        runs = (await db.execute(select(PaperCrawlRun))).scalars().all()
        assert len(runs) == 2  # success + failed 各一行（原位更新，无重复行）
        assert {r.status for r in runs} == {"success", "failed"}
