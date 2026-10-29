"""论文域增强③测试（P16/P20）：收藏并解析全链路。

- 下载双通道：paper.url 直链成功（direct）；直链 404 → Unpaywall 补链（unpaywall）；
  直链返回 HTML（非 PDF 魔数）→ 补链；双通道皆失败 → failed + 原因可见；
- MinerU 三端点全流程（mock）：file-urls/batch → PUT 直传 → extract/task → 轮询 done
  → 下载 zip → 拆存断言（zip 构造 full.md/content_list.json/_meta.json）；
- COS key 断言：SpyStorage 记录全部 put，app 恒 "papers"、key 恒 papers/ 前缀内部结构
  （pdfs/{yyyy}/{mm}/{id}.pdf、parsed/{id}/full.md|content_list.json|meta.json，P20）；
- 状态机：none→done；done 幂等不重复跑；running/pending 拒重入；failed 可重跑；
- 接口：collect-parse（登录 app:papers；自动收藏幂等；running 409；done 直返）、
  parse-status 轮询、/papers/parsed 我的笔记列表（收藏 ∩ done）；
- pipeline：未配置 HATCHET_CLIENT_TOKEN 时 push_parse_event 返回 False（进程内兜底）。
"""

import io
import json
import re
import zipfile

import httpx
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.papers import Paper, PaperFavorite, PaperUser
from app.models.service_key import ServiceKey
from app.models.user import User
from app.services import paper_parse, pipeline
from app.services.storage import Storage
from tests.conftest import login

MINERU_BASE = "https://mineru.net/api/v4"
_FAKE_PDF = b"%PDF-1.4\nfake pdf body\n%%EOF"
_FAKE_HTML = b"<html><body>abs page, not a pdf</body></html>"


def _make_zip(page_size: int = 2) -> bytes:
    """构造 MinerU 风格产物 zip：外层目录包裹 full.md/content_list.json/_meta.json。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("2601.1/full.md", "# Parsed Title\n\nbody text\n")
        zf.writestr(
            "2601.1/content_list.json",
            json.dumps([
                {"type": "text", "page_idx": 0, "text": "a"},
                {"type": "text", "page_idx": page_size - 1, "text": "b"},
            ]),
        )
        zf.writestr("2601.1/_meta.json", json.dumps({"page_size": page_size}))
    return buf.getvalue()


_FAKE_ZIP = _make_zip(page_size=2)


class _FakeResp:
    """最小 httpx.Response 替身：raise_for_status/json/text/content。"""

    def __init__(self, status_code: int = 200, json_data: object | None = None, content: bytes = b""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.text = content.decode("utf-8", "ignore") if content else json.dumps(self._json)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("GET", "http://fake.local/")
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=req,
                response=httpx.Response(self.status_code, request=req),
            )

    def json(self) -> object:
        return self._json


class _StreamCtx:
    """client.stream 的异步上下文管理器替身（支撑 _fetch_bytes 流式下载）。"""

    def __init__(self, resp: _FakeResp):
        self._resp = resp

    async def __aenter__(self) -> "_StreamCtx":  # noqa: PYI034 - 异步上下文协议，返回 self
        self._resp.raise_for_status()
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        self._resp.raise_for_status()

    async def aiter_bytes(self, chunk_size: int = 65536):
        data = self._resp.content
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]


class FakeHttpClient:
    """按 (method, url 前缀) 路由的假 httpx 总机；记录全部调用供断言。"""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def _handle(self, method: str, url: str) -> _FakeResp:
        self.calls.append((method, url))
        for (m, prefix), handler in self.routes.items():
            if m == method and url.startswith(prefix):
                return handler() if callable(handler) else handler
        raise AssertionError(f"假总机无路由：{method} {url}")

    async def get(self, url: str, **kwargs: object) -> _FakeResp:
        return self._handle("GET", url)

    async def post(self, url: str, **kwargs: object) -> _FakeResp:
        return self._handle("POST", url)

    async def put(self, url: str, **kwargs: object) -> _FakeResp:
        return self._handle("PUT", url)

    def stream(self, method: str, url: str, **kwargs: object) -> _StreamCtx:
        return _StreamCtx(self._handle(method, url))


class SpyStorage(Storage):
    """记录 put 调用的存储替身：app 前缀硬隔离断言（P11）+ P20 key 结构断言。"""

    def __init__(self) -> None:
        self.puts: list[tuple[str, str, bytes]] = []

    async def put(self, app: str, key: str, data: bytes) -> None:
        self.puts.append((app, key, bytes(data)))

    async def get(self, app: str, key: str) -> bytes:  # pragma: no cover - 本批不测
        raise FileNotFoundError(key)

    async def delete(self, app: str, key: str) -> None:  # pragma: no cover
        raise FileNotFoundError(key)

    async def exists(self, app: str, key: str) -> bool:  # pragma: no cover
        return False


def _mineru_routes(extra: dict | None = None) -> dict:
    """MinerU 三端点 + 签名上传 + zip 下载的 mock 路由（extra 覆盖/追加）。"""
    routes: dict = {
        ("POST", f"{MINERU_BASE}/file-urls/batch"): _FakeResp(
            json_data={
                "code": 0,
                "data": {
                    "batch_id": "batch-1",
                    "file_urls": ["https://upload.example/signed/1"],
                },
            }
        ),
        ("PUT", "https://upload.example/signed/1"): _FakeResp(),
        ("GET", f"{MINERU_BASE}/extract-results/batch/batch-1"): _FakeResp(
            json_data={
                "code": 0,
                "data": {
                    "extract_result": [
                        {
                            "file_name": "1.pdf",
                            "state": "done",
                            "full_zip_url": "https://zip.example/out.zip",
                        }
                    ]
                },
            }
        ),
        ("GET", "https://zip.example/out.zip"): _FakeResp(content=_FAKE_ZIP),
    }
    if extra:
        routes.update(extra)
    return routes


async def _add_mineru_key() -> None:
    async with SessionLocal() as db:
        db.add(ServiceKey(
            service_key="mineru", vendor="mineru", api_key="fake-mineru-token",
            base_url=MINERU_BASE, enabled=True,
        ))
        await db.commit()


async def _make_paper(url: str = "", doi: str = "", source: str = "pubmed") -> int:
    """直接插一篇文献并归属 admin（绕过抓取管线，单测解析链路）。"""
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        paper = Paper(
            pmid=f"parse-test:{source}:{url or doi or 'na'}",
            source=source, title="Parse target paper", abstract="abstract text",
            journal="J Parse", url=url, doi=doi,
        )
        db.add(paper)
        await db.commit()
        await db.refresh(paper)
        db.add(PaperUser(paper_id=paper.id, user_id=uid))
        await db.commit()
        return paper.id


async def _paper_status(pid: int) -> tuple[str, str | None]:
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        return row.parse_status, row.parse_error


async def test_download_direct_and_full_pipeline_keys(client, monkeypatch):
    """直链下载（direct）→ 全链 done；COS 拆存 key 断言（SpyStorage，P20 结构）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/paper.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse_status"] == "done"
    assert body["saved"] is True  # 自动收藏回执
    assert body["parsed_at"] is not None

    # P11：app 恒 papers；P20：PDF 年月分层 + 解析产物三件套
    assert len(spy.puts) == 4
    assert all(app == "papers" for app, _, _ in spy.puts)
    keys = [key for _, key, _ in spy.puts]
    assert re.fullmatch(rf"pdfs/\d{{4}}/\d{{2}}/{pid}\.pdf", keys[0]), keys
    assert keys[1:] == [
        f"parsed/{pid}/full.md",
        f"parsed/{pid}/content_list.json",
        f"parsed/{pid}/meta.json",
    ]
    assert spy.puts[0][2].startswith(b"%PDF-")  # 原始 PDF 原样落存储
    meta = json.loads(spy.puts[3][2])
    assert meta["model_version"] == "vlm"
    assert meta["page_count"] == 2  # _meta.json page_size
    assert meta["paper_id"] == pid
    # MinerU 三端点 + 直传 + zip 全走到
    called = [f"{m} {u}" for m, u in fake.calls]
    assert any("file-urls/batch" in c for c in called)
    assert any(c.startswith("PUT https://upload.example") for c in called)
    assert any(c == f"GET {MINERU_BASE}/extract-results/batch/batch-1" for c in called)
    assert any("zip.example/out.zip" in c for c in called)


async def _async(value):
    return value


async def test_download_falls_back_to_unpaywall_when_direct_404(client, monkeypatch):
    """直链 404 → Unpaywall 补链成功（source=unpaywall），全链仍 done。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://paywall.example/a.pdf", doi="10.1000/parse.2026")
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://paywall.example/a.pdf"): _FakeResp(status_code=404),
        ("GET", "https://api.unpaywall.org/v2/10.1000/parse.2026"): _FakeResp(
            json_data={"best_oa_location": {"url_for_pdf": "https://oa.example/u.pdf"}}
        ),
        ("GET", "https://oa.example/u.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "done"
    assert result["pdf_source"] == "unpaywall"
    assert any("unpaywall.org" in u for m, u in fake.calls if m == "GET")


async def test_download_falls_back_when_direct_returns_html(client, monkeypatch):
    """直链返回 HTML（非 PDF 魔数）→ 触发补链；魔数校验挡住假全文。"""
    await _add_mineru_key()
    pid = await _make_paper(
        url="https://arxiv.org/abs/2601.99999", doi="10.1000/html.2026", source="arxiv"
    )
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes({
        # arXiv abs 页自动改 pdf 直链：/abs/ → /pdf/
        ("GET", "https://arxiv.org/pdf/2601.99999"): _FakeResp(content=_FAKE_HTML),
        ("GET", "https://api.unpaywall.org/v2/10.1000/html.2026"): _FakeResp(
            json_data={"first_oa_location": {"url": "https://oa.example/h.pdf"}}
        ),
        ("GET", "https://oa.example/h.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "done"
    assert any(u == "https://arxiv.org/pdf/2601.99999" for m, u in fake.calls)


async def test_download_both_channels_fail_marks_failed(client, monkeypatch):
    """双通道皆失败：状态 failed + parse_error 可见（前端错误区/手动下载指引）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://dead.example/x.pdf", doi="10.1000/nofull.2026")
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://dead.example/x.pdf"): _FakeResp(status_code=404),
        ("GET", "https://api.unpaywall.org/v2/10.1000/nofull.2026"): _FakeResp(
            json_data={"best_oa_location": None}
        ),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "failed"
    assert "Unpaywall" in (result["parse_error"] or "")
    status, error = await _paper_status(pid)
    assert status == "failed" and error


async def test_mineru_missing_key_fails_loudly(client, monkeypatch):
    """service_keys 无 mineru 行：MinerUConfigError 落 failed，原因引导配置（不静默）。"""
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    fake = FakeHttpClient({("GET", "https://oa.example/paper.pdf"): _FakeResp(content=_FAKE_PDF)})
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    spy = SpyStorage()
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "failed"
    assert "MinerU 未配置" in (result["parse_error"] or "")
    # PDF 已存（下载成功），失败发生在解析配置——重跑不重下属后续优化，本期允许
    assert len(spy.puts) == 1 and spy.puts[0][1].endswith(".pdf")


async def test_state_machine_done_idempotent_and_running_rejected(client, monkeypatch):
    """done 幂等不重复跑（下载不再触发）；pending/running 拒重入（ParseAlreadyRunning）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/paper.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(SpyStorage()))

    async with SessionLocal() as db:
        first = await paper_parse.run_parse_pipeline(db, pid, 1)
        assert first["parse_status"] == "done"
        download_calls = len([u for m, u in fake.calls if "oa.example" in u])

        second = await paper_parse.run_parse_pipeline(db, pid, 1)
        assert second["parse_status"] == "done"
        assert len([u for m, u in fake.calls if "oa.example" in u]) == download_calls

        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.parse_status = "running"
        await db.commit()
        with pytest.raises(paper_parse.ParseAlreadyRunning):
            await paper_parse.run_parse_pipeline(db, pid, 1)


async def test_collect_parse_api_idempotency_and_409(client, monkeypatch):
    """接口幂等：done 直返 200 不重跑；running 409；failed 可重跑；自动收藏幂等。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/paper.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(SpyStorage()))
    headers = await login(client)

    r1 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r1.status_code == 200 and r1.json()["parse_status"] == "done"
    oa_calls = len([u for m, u in fake.calls if "oa.example" in u])

    # done 再点：不重跑（下载零新增），仍 200
    r2 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r2.status_code == 200 and r2.json()["parse_status"] == "done"
    assert len([u for m, u in fake.calls if "oa.example" in u]) == oa_calls

    # 自动收藏幂等：两次点按钮后收藏仍恰好一行
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        favs = (
            await db.execute(select(PaperFavorite).where(PaperFavorite.paper_id == pid))
        ).scalars().all()
        assert len(favs) == 1 and favs[0].user_id == uid

    # running 态：409
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.parse_status = "running"
        await db.commit()
    r3 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r3.status_code == 409

    # failed 态：允许重跑（200 done）
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.parse_status = "failed"
        paper.parse_error = "上次失败"
        await db.commit()
    r4 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r4.status_code == 200 and r4.json()["parse_status"] == "done"

    # parse-status 轮询接口回读
    r5 = await client.get(f"/papers/{pid}/parse-status", headers=headers)
    assert r5.status_code == 200
    body = r5.json()
    assert body["parse_status"] == "done" and body["parsed_at"]


async def test_parsed_notes_list_and_detail_fields(client, monkeypatch):
    """我的笔记列表 = 收藏 ∩ done；digest/daily/详情带 parse_status，详情带 parse_error。"""
    await _add_mineru_key()
    pid_done = await _make_paper(url="https://oa.example/a.pdf")
    pid_none = await _make_paper(url="https://oa.example/b.pdf")
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/a.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(SpyStorage()))
    headers = await login(client)

    await client.post(f"/papers/{pid_done}/collect-parse", headers=headers)

    # /papers/parsed：只有 done 那篇
    r = await client.get("/papers/parsed", headers=headers)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert pid_done in ids and pid_none not in ids
    item = next(p for p in r.json() if p["id"] == pid_done)
    assert item["parse_status"] == "done" and item["parsed_at"]

    # 详情带 parse_status + parse_error；未解析篇 status=none
    d1 = await client.get(f"/papers/{pid_done}", headers=headers)
    assert d1.json()["parse_status"] == "done" and d1.json()["parse_error"] is None
    d2 = await client.get(f"/papers/{pid_none}", headers=headers)
    assert d2.json()["parse_status"] == "none"

    # daily 列表带 parse_status
    daily = await client.get("/papers/daily", headers=headers)
    assert daily.status_code == 200
    by_id = {p["id"]: p for p in daily.json()}
    assert by_id[pid_done]["parse_status"] == "done"
    assert by_id[pid_none]["parse_status"] == "none"


async def test_store_parsed_page_count_inferred_from_content_list():
    """页数推断回落：无 _meta.json 时从 content_list.json 的 page_idx 最大值 +1。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x/full.md", "# t\n")
        zf.writestr("x/content_list.json", json.dumps([
            {"page_idx": 0}, {"page_idx": 4}, {"page_idx": 2},
        ]))
    spy = SpyStorage()
    result = await paper_parse.store_parsed(spy, 7, buf.getvalue(), "vlm")
    assert result["page_count"] == 5
    assert result["keys"] == [
        "parsed/7/full.md", "parsed/7/content_list.json", "parsed/7/meta.json",
    ]


async def test_pipeline_push_parse_event_degrades_without_hatchet(client):
    """未配置 HATCHET_CLIENT_TOKEN：push_parse_event 返回 False（路由进程内兜底）。"""
    assert pipeline.is_configured() is False
    assert pipeline.push_parse_event(1, 1) is False
