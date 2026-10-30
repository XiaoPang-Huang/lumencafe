"""论文域增强③测试（P16/P20；P30 全文与解析解耦改造）。

P30 后链路语义：获取全文（fetch-fulltext 独立动作，见 test_papers_fulltext.py）
与解析（collect-parse 只读 COS 已存文件，**绝不再下载**）解耦——本文件聚焦解析管
线与状态机，SpyStorage 预置全文文件模拟「获取/上传已完成」。

- 解析读 COS 不下载：collect-parse 全链 done；download_oa_pdf 零调用（spy）；
- MinerU 三端点全流程（mock）：file-urls/batch → PUT 直传 → extract-results/batch
  → 下载 zip → 拆存断言（P20 key 结构）；
- COS key 断言：SpyStorage 记录全部 put，app 恒 "papers"、key 恒 P20 内部结构
  （pdfs/{yyyy}/{mm}/{id}.pdf、parsed/{id}/full.md|content_list.json|meta.json）；
- 状态机：none→done；done 幂等不重复跑；running/pending 拒重入；failed 可重跑；
- 接口：collect-parse（登录 app:papers；自动收藏幂等；running 409；done 直返；
  无全文 409「请先获取或上传全文」）、parse-status 轮询、/papers/parsed 我的笔记列表；
- pipeline：未配置 HATCHET_CLIENT_TOKEN 时 push_parse_event 返回 False（进程内兜底）。
"""

import io
import json
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
    """内存存储替身：put 落 files 字典；记录全部 put/get/delete 供断言。

    P30 起解析管线读 COS（list 定位 + get 取文件），本替身同时服务
    「全文已就绪」前置与「解析不下载」断言。
    """

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.puts: list[tuple[str, str, bytes]] = []
        self.gets: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str]] = []

    async def put(self, app: str, key: str, data: bytes) -> None:
        self.puts.append((app, key, bytes(data)))
        self.files[key] = bytes(data)

    async def get(self, app: str, key: str) -> bytes:
        self.gets.append((app, key))
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    async def delete(self, app: str, key: str) -> None:
        self.deletes.append((app, key))
        self.files.pop(key, None)

    async def exists(self, app: str, key: str) -> bool:
        return key in self.files

    async def list(self, app: str, prefix: str) -> list[str]:
        return sorted(k for k in self.files if k.startswith(prefix))

    def seed_pdf(self, paper_id: int, data: bytes = _FAKE_PDF) -> str:
        """预置已存全文（模拟获取/上传动作已完成），key 与 store_pdf 同口径（当前月）。"""
        key = paper_parse.pdf_object_key(paper_id)
        self.files[key] = data
        return key


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
            journal="J Parse", url=url, doi=doi, user_id=uid,
        )
        db.add(paper)
        await db.commit()
        await db.refresh(paper)
        db.add(PaperUser(paper_id=paper.id, user_id=uid))
        await db.commit()
        return paper.id


async def _add_to_library(pid: int) -> None:
    """轮② P28：collect-parse 收紧为仅库内可发起——测试先加入我的文献。"""
    from app.models.papers import PaperLibrary

    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperLibrary(paper_id=pid, user_id=uid, added_via="crawl"))
        await db.commit()


async def _paper_status(pid: int) -> tuple[str, str | None]:
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        return row.parse_status, row.parse_error


def _patch_storage(monkeypatch, spy: SpyStorage) -> None:
    """路由层与管线层 get_storage 同源替换（collect-parse 前置校验在路由层读存储）。"""
    import app.routers.papers as papers_router

    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))
    monkeypatch.setattr(papers_router, "get_storage", lambda db: _async(spy))


async def test_collect_parse_reads_cos_without_download(client, monkeypatch):
    """P30：解析只读 COS 已存全文——done；download_oa_pdf 零调用（魔数替换为抛错）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()
    pdf_key = spy.seed_pdf(pid)  # 全文已由「获取/上传」独立动作就绪
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)

    def _boom(db, paper):  # P30 断言核心：解析链路绝不再走网络下载
        raise AssertionError("解析管线不应调用 download_oa_pdf（全文与解析已解耦）")

    monkeypatch.setattr(paper_parse, "download_oa_pdf", _boom)

    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse_status"] == "done"
    assert body["saved"] is True  # 自动收藏回执
    assert body["parsed_at"] is not None

    # 全文从 COS 读取（而非 put 重存）：get 命中预置 key，PDF 不再写存储
    assert spy.gets == [("papers", pdf_key)]
    pdf_puts = [k for _, k, _ in spy.puts if k.startswith("pdfs/")]
    assert pdf_puts == [], spy.puts
    # P11：app 恒 papers；P20：解析产物三件套
    assert all(app == "papers" for app, _, _ in spy.puts)
    keys = [key for _, key, _ in spy.puts]
    assert keys == [
        f"parsed/{pid}/full.md",
        f"parsed/{pid}/content_list.json",
        f"parsed/{pid}/meta.json",
    ]
    meta = json.loads(spy.puts[2][2])
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


async def test_mineru_missing_key_fails_loudly(client, monkeypatch):
    """service_keys 无 mineru 行：MinerUConfigError 落 failed，原因引导配置（不静默）。"""
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    spy = SpyStorage()
    spy.seed_pdf(pid)  # P30：全文已就绪，失败只发生在解析配置
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "failed"
    assert "MinerU 未配置" in (result["parse_error"] or "")
    # 全文已在 COS（非解析写入），失败发生在解析配置——解析产物未产生
    assert len(spy.puts) == 0


async def test_state_machine_done_idempotent_and_running_rejected(client, monkeypatch):
    """done 幂等不重复跑（COS 读不再触发）；pending/running 拒重入。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    spy = SpyStorage()
    spy.seed_pdf(pid)
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(spy))

    async with SessionLocal() as db:
        first = await paper_parse.run_parse_pipeline(db, pid, 1)
        assert first["parse_status"] == "done"
        assert first["pdf_source"] == "cos"  # P30：来源 = COS 已存文件

        get_calls = len(spy.gets)
        second = await paper_parse.run_parse_pipeline(db, pid, 1)
        assert second["parse_status"] == "done"
        assert len(spy.gets) == get_calls  # done 幂等直返，不重复读

        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.parse_status = "running"
        await db.commit()
        with pytest.raises(paper_parse.ParseAlreadyRunning):
            await paper_parse.run_parse_pipeline(db, pid, 1)


async def test_collect_parse_api_idempotency_and_409(client, monkeypatch):
    """接口幂等：done 直返 200 不重跑；running 409；failed 可重跑；自动收藏幂等。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/paper.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()
    spy.seed_pdf(pid)
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r1 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r1.status_code == 200 and r1.json()["parse_status"] == "done"
    get_calls = len(spy.gets)

    # done 再点：不重跑（COS 读零新增），仍 200
    r2 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r2.status_code == 200 and r2.json()["parse_status"] == "done"
    assert len(spy.gets) == get_calls

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
    await _add_to_library(pid_done)
    spy = SpyStorage()
    spy.seed_pdf(pid_done)
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
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
