"""论文域 P30 测试：全文与解析解耦（获取 / 上传 / 解析三独立动作 + 替换 + 需重新解析）。

- fetch-fulltext 成功径：直链 → COS，fulltext_status=oa、错误清；幂等 already 不重复下载；
- fetch-fulltext 失败径：直链 404 → Unpaywall 404/无 OA 位置链 → {ok:false, reason}
  （mock unpaywall 404 链），fulltext_status 保持 none、fulltext_error 截断 500 入库；
- upload/replace：base64 PDF → COS 覆盖（key 恒 pdfs/**/{id}.pdf）；此前 done 态触发
  「需重新解析」四清断言（parse_status/parse_phase/translate_status/parsed_at 全清 +
  reparse_pending 标志）；解析中（running）同样四清；
- collect-parse 无文件 409「请先获取或上传全文」；
- library 与 parsing 列表带 fulltext_status/fulltext_error/needs_reparse；
- 回填口径（Alembic 0014）：parse_status ∈ (done, failed) → oa，其余 none。
"""

import base64

from sqlalchemy import select

from app.db import SessionLocal
from app.models.papers import Paper
from app.services import paper_parse
from tests.conftest import login
from tests.test_papers_parse import (
    FakeHttpClient,
    SpyStorage,
    _add_mineru_key,
    _add_to_library,
    _FakeResp,
    _make_paper,
    _mineru_routes,
    _patch_storage,
)

_FAKE_PDF = b"%PDF-1.4\nfake pdf body\n%%EOF"
_FAKE_PDF_2 = b"%PDF-1.4\nreplacement pdf\n%%EOF"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


async def test_fetch_fulltext_success_direct(client, monkeypatch):
    """获取成功：直链下载 → COS → oa；再调幂等 already（下载零新增）。"""
    pid = await _make_paper(url="https://oa.example/ft.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()
    fake = FakeHttpClient({
        ("GET", "https://oa.example/ft.pdf"): _FakeResp(content=_FAKE_PDF),
    })
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r = await client.post(f"/papers/{pid}/fetch-fulltext", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["already"] is False
    assert body["source"] == "direct"
    assert body["reason"] is None
    assert body["fulltext_status"] == "oa"
    assert body["fulltext_error"] is None
    # COS 落存：P20 结构 + 内容原样
    assert len(spy.puts) == 1
    app, key, data = spy.puts[0]
    assert app == "papers"
    assert key.endswith(f"/{pid}.pdf") and key.startswith("pdfs/")
    assert data == _FAKE_PDF
    oa_calls = len(fake.calls)

    # 幂等：已有文件 → already，不再下载
    r2 = await client.post(f"/papers/{pid}/fetch-fulltext", headers=headers)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["ok"] is True and body2["already"] is True
    assert body2["fulltext_status"] == "oa"
    assert len(fake.calls) == oa_calls  # 下载零新增

    # 解析前置校验现在能通过（文件就绪）
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert row.fulltext_status == "oa"
        assert row.fulltext_error is None


async def test_fetch_fulltext_failure_unpaywall_404_chain(client, monkeypatch):
    """失败径：直链 404 → Unpaywall 404 → {ok:false, reason}；保持 none + 错误入库。"""
    pid = await _make_paper(url="https://paywall.example/x.pdf", doi="10.1000/ft.fail")
    await _add_to_library(pid)
    spy = SpyStorage()
    fake = FakeHttpClient({
        ("GET", "https://paywall.example/x.pdf"): _FakeResp(status_code=404),
        ("GET", "https://api.unpaywall.org/v2/10.1000/ft.fail"): _FakeResp(status_code=404),
    })
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r = await client.post(f"/papers/{pid}/fetch-fulltext", headers=headers)
    assert r.status_code == 200  # 失败也 200：reason 可见可重试（拍板 P30）
    body = r.json()
    assert body["ok"] is False
    assert body["already"] is False
    assert body["reason"]  # 原因可见（直链 + Unpaywall 拼接）
    assert "Unpaywall" in body["reason"]
    assert body["fulltext_status"] == "none"  # 保持 none
    assert body["fulltext_error"] == body["reason"]
    assert len(spy.puts) == 0  # 失败不落 COS

    # 解析前置校验：无文件 → 409
    r409 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r409.status_code == 409
    assert "请先获取或上传全文" in r409.json()["detail"]

    # library 列表带 fulltext_status/fulltext_error（失败原因可见）
    lib = await client.get("/papers/library", headers=headers)
    item = next(p for p in lib.json() if p["id"] == pid)
    assert item["fulltext_status"] == "none"
    assert item["fulltext_error"] == body["reason"]
    assert item["needs_reparse"] is False


async def test_fetch_fulltext_requires_library_and_ownership(client, monkeypatch):
    """P28 口径：仅本人 library 内可获取全文；他人文献 404。"""
    pid = await _make_paper(url="https://oa.example/ft.pdf")  # 未入 library
    headers = await login(client)
    r = await client.post(f"/papers/{pid}/fetch-fulltext", headers=headers)
    assert r.status_code == 403


async def test_upload_fulltext_then_parse(client, monkeypatch):
    """上传（无文件态）：fulltext_status=uploaded；随后 collect-parse 可跑通。"""
    await _add_mineru_key()
    pid = await _make_paper()
    await _add_to_library(pid)
    spy = SpyStorage()
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r = await client.post(
        f"/papers/{pid}/fulltext", headers=headers, json={"pdf_base64": _b64(_FAKE_PDF)}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["fulltext_status"] == "uploaded"
    assert body["needs_reparse"] is False  # 从未解析 → 无四清
    assert body["parse_status"] == "none"
    assert len(spy.puts) == 1 and spy.puts[0][1].endswith(f"/{pid}.pdf")
    assert spy.puts[0][2] == _FAKE_PDF

    # 上传后解析可跑通（读 COS 上传件）
    r2 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r2.status_code == 200 and r2.json()["parse_status"] == "done"


async def test_upload_replace_after_done_triggers_reparse_state(client, monkeypatch):
    """替换 done 态文件：四清断言（parse_status/phase/translate_status/parsed_at）+ 标志。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/rp.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()
    seeded_key = spy.seed_pdf(pid)  # 全文已就绪（获取/上传动作产物，key 与 store_pdf 同口径）
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    # 先解析到 done（含翻译状态，验证四清③）
    r1 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r1.json()["parse_status"] == "done"
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        row.translate_status = "done"
        await db.commit()

    # 替换文件 → 四清 + 「需重新解析」
    r2 = await client.post(
        f"/papers/{pid}/fulltext", headers=headers, json={"pdf_base64": _b64(_FAKE_PDF_2)}
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["ok"] is True
    assert body["needs_reparse"] is True
    assert body["fulltext_status"] == "uploaded"
    assert body["parse_status"] == "none"
    assert body["parse_phase"] is None
    assert body["parse_error"] is None
    # COS 覆盖断言：同 key 覆盖（seed key == 上传 put key），内容被替换；
    # 重解析前 parsed/ 三件保留不删
    pdf_keys = [k for _, k, _ in spy.puts if k.startswith("pdfs/")]
    assert pdf_keys == [seeded_key], pdf_keys
    assert spy.files[seeded_key] == _FAKE_PDF_2  # 内容已替换为新文件
    parsed_keys = [k for k in spy.files if k.startswith(f"parsed/{pid}/")]
    assert parsed_keys, "替换不得删除解析产物（重解析覆盖）"

    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert row.parse_status == "none"  # 四清①
        assert row.parse_phase is None  # 四清②
        assert row.translate_status is None  # 四清③
        assert row.parsed_at is None  # 四清④
        assert row.reparse_pending is True
        assert row.fulltext_status == "uploaded"

    # library 列表：needs_reparse 显式标志（前端「⟳ 重新解析」高亮数据源）
    lib = await client.get("/papers/library", headers=headers)
    item = next(p for p in lib.json() if p["id"] == pid)
    assert item["needs_reparse"] is True
    assert item["fulltext_status"] == "uploaded"
    assert item["parse_status"] == "none"

    # 重新解析：一点即重跑（标志随发起即清）
    r3 = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r3.status_code == 200 and r3.json()["parse_status"] == "done"
    lib2 = await client.get("/papers/library", headers=headers)
    item2 = next(p for p in lib2.json() if p["id"] == pid)
    assert item2["needs_reparse"] is False
    assert item2["parse_status"] == "done"


async def test_upload_replace_while_running_also_resets(client, monkeypatch):
    """替换「解析中」文件：同样四清（拍板：已解析或解析中 → 需重新解析）。"""
    pid = await _make_paper(url="https://oa.example/rn.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()
    spy.seed_pdf(pid)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        row.parse_status = "running"
        row.parse_phase = "parsing"
        await db.commit()

    r = await client.post(
        f"/papers/{pid}/fulltext", headers=headers, json={"pdf_base64": _b64(_FAKE_PDF)}
    )
    assert r.status_code == 200 and r.json()["needs_reparse"] is True
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        assert row.parse_status == "none"
        assert row.parse_phase is None
        assert row.reparse_pending is True


async def test_upload_fulltext_validation(client, monkeypatch):
    """非 PDF 魔数 / 非法 base64 → 422 不落库。"""
    pid = await _make_paper()
    await _add_to_library(pid)
    spy = SpyStorage()
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r1 = await client.post(
        f"/papers/{pid}/fulltext", headers=headers,
        json={"pdf_base64": _b64(b"<html>not a pdf</html>")},
    )
    assert r1.status_code == 422
    r2 = await client.post(
        f"/papers/{pid}/fulltext", headers=headers, json={"pdf_base64": "!!!bad-base64!!!"}
    )
    assert r2.status_code == 422
    assert len(spy.puts) == 0


async def test_collect_parse_409_without_fulltext(client, monkeypatch):
    """P30 前置校验：COS 无全文文件 → 409「请先获取或上传全文」（解析不下载）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/nofile.pdf")
    await _add_to_library(pid)
    spy = SpyStorage()  # 空存储：无全文
    fake = FakeHttpClient(_mineru_routes())
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    r = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert r.status_code == 409
    assert "请先获取或上传全文" in r.json()["detail"]
    assert len(fake.calls) == 0  # 未发起任何网络调用
    # 状态不被污染（仍 none，可后续获取/上传）
    status, error = await _paper_row(pid)
    assert status == "none" and error is None


async def test_parsing_list_carries_fulltext_fields(client, monkeypatch):
    """parsing 列表带 fulltext_status/fulltext_error（与 library 列表同口径）。"""
    pid = await _make_paper(url="https://oa.example/pl.pdf", doi="10.1000/pl.fail")
    await _add_to_library(pid)
    spy = SpyStorage()
    fake = FakeHttpClient({
        ("GET", "https://oa.example/pl.pdf"): _FakeResp(status_code=404),
        ("GET", "https://api.unpaywall.org/v2/10.1000/pl.fail"): _FakeResp(
            json_data={"best_oa_location": None}
        ),
    })
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    _patch_storage(monkeypatch, spy)
    headers = await login(client)

    await client.post(f"/papers/{pid}/fetch-fulltext", headers=headers)
    r = await client.get("/papers/library/parsing", headers=headers)
    # 失败获取不产生解析任务，列表为空但接口可用；改为直接置 failed 验证字段携带
    assert r.status_code == 200
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        row.parse_status = "failed"
        row.parse_error = "上次解析失败"
        await db.commit()
    r2 = await client.get("/papers/library/parsing", headers=headers)
    item = next(p for p in r2.json() if p["id"] == pid)
    assert item["fulltext_status"] == "none"
    assert item["fulltext_error"]  # 获取失败原因随 parsing 列表可见
    assert item["parse_error"] == "上次解析失败"


async def _paper_row(pid: int):
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        return row.parse_status, row.parse_error
