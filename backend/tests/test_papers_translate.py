"""论文域轮③测试（P27）：段落级中英对照翻译。

- 分批断言：text 块每批 ≤15 段走网关（mock model_caller），批数 = ceil(n/15)；
- JSON 解析失败重试：单批返回非 JSON → 该批失败块重试一次（重试只带缺块）；
  重试仍失败 → 已译进度照常落盘，整体 failed + translate_error；
- 增量跳过已译块：translation.json 已有的 block_id 不再送网关（重解析补译增量）；
- 状态机四态：none→done；done 幂等不重复跑；running 拒重入（API 409）；
  failed 可重跑；force=true（重新翻译）清缓存全量重译；
- COS 落盘断言：SpyStorage 记录 put，key 恒 parsed/{id}/translation.json；
- 接口守卫：非归属 404 / 非库内 403 / 解析未 done 409；
- 真连网关（seed mock 模型）：JSON 键不符 → 缺块失败；llm_call_logs 记账
  app_key=papers_translate（费用随网关记账）；
- auto_translate 开关联动：papers_prefs.auto_translate=true 时解析 done 自动
  触发翻译（mock 网关全链）；默认关不触发。
"""

import json

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models.llm import LLMCallLog
from app.models.papers import Paper
from app.routers import papers as papers_router
from app.services import model_caller, paper_parse, paper_translate
from app.services.storage import Storage, StorageNotFoundError
from tests.conftest import login
from tests.test_papers_parse import (
    FakeHttpClient,
    _add_mineru_key,
    _FakeResp,
    _make_paper,
    _mineru_routes,
)

_FAKE_PDF = b"%PDF-1.4\nfake pdf body\n%%EOF"


async def _async(value):
    return value


class MemoryStorage(Storage):
    """内存存储替身：get/put/delete/exists 全支持（翻译增量读写依赖 get）。"""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.puts: list[tuple[str, str, bytes]] = []

    async def put(self, app: str, key: str, data: bytes) -> None:
        self.objects[(app, key)] = bytes(data)
        self.puts.append((app, key, bytes(data)))

    async def get(self, app: str, key: str) -> bytes:
        try:
            return self.objects[(app, key)]
        except KeyError as exc:
            raise StorageNotFoundError(key) from exc

    async def delete(self, app: str, key: str) -> None:
        self.objects.pop((app, key), None)

    async def exists(self, app: str, key: str) -> bool:
        return (app, key) in self.objects


def _patch_storage(monkeypatch, storage: Storage) -> None:
    """四个命名空间都要补 get_storage（各自 from-import，补丁按模块落）。"""
    from app.services import paper_content as pc
    from app.services import paper_library as pl
    from app.services import paper_translate as pt

    monkeypatch.setattr(pt, "get_storage", lambda db: _async(storage))
    monkeypatch.setattr(pc, "get_storage", lambda db: _async(storage))
    monkeypatch.setattr(pl, "get_storage", lambda db: _async(storage))
    monkeypatch.setattr(papers_router, "get_storage", lambda db: _async(storage))


def _content_list(n: int) -> bytes:
    """n 个 text 块（全在首页）→ block_id p1_b1..p1_b{n}。"""
    return json.dumps(
        [
            {"type": "text", "page_idx": 0, "text": f"English sentence {i} about biomarkers."}
            for i in range(1, n + 1)
        ]
    ).encode()


class FakeGateway:
    """model_caller.chat_once 替身：记录调用，handler(messages, nth) 生成返回。"""

    def __init__(self, handler) -> None:
        self.calls: list[dict] = []
        self._handler = handler

    async def chat_once(self, db, app_key, messages, timeout=30.0):
        self.calls.append(
            {"app_key": app_key, "messages": messages, "timeout": timeout}
        )
        return self._handler(messages, len(self.calls))

    def user_payloads(self) -> list[dict]:
        """全部调用的 user 消息 JSON（块 id → 原文）。"""
        out = []
        for call in self.calls:
            out.append(json.loads(call["messages"][-1]["content"]))
        return out


def _default_handler(messages, nth: int) -> str:
    """默认假网关：逐块回译（键与请求一致，值带 译- 前缀便于断言）。"""
    payload = json.loads(messages[-1]["content"])
    return json.dumps(
        {bid: f"译-{bid}" for bid in payload}, ensure_ascii=False
    )


def _patch_gateway(monkeypatch, handler=_default_handler) -> FakeGateway:
    gw = FakeGateway(handler)
    monkeypatch.setattr(model_caller, "chat_once", gw.chat_once)
    return gw


async def _make_parsed_paper(n_blocks: int = 20, monkeypatch=None) -> tuple[int, MemoryStorage]:
    """造一篇解析 done 的库内文献 + content_list.json 落内存存储。"""
    pid = await _make_paper(url="https://oa.example/translate.pdf")
    storage = MemoryStorage()
    storage.objects[("papers", f"parsed/{pid}/content_list.json")] = _content_list(n_blocks)
    async with SessionLocal() as db:
        uid = (await db.execute(select(Paper.user_id).where(Paper.id == pid))).scalar_one()
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.parse_status = "done"
        from app.models.papers import PaperLibrary

        db.add(PaperLibrary(paper_id=pid, user_id=uid, added_via="crawl"))
        await db.commit()
    if monkeypatch is not None:
        _patch_storage(monkeypatch, storage)
    return pid, storage


async def _translate_state(pid: int) -> tuple[str, str | None]:
    async with SessionLocal() as db:
        row = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        return row.translate_status or "none", row.translate_error


async def test_translate_batches_and_cos_key(client, monkeypatch):
    """20 个 text 块 → 2 批（15+5）；translation.json 落 COS key 断言；状态 done。"""
    pid, storage = await _make_parsed_paper(20, monkeypatch)
    gw = _patch_gateway(monkeypatch)

    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["translate_status"] == "done"
    assert body["translated_blocks"] == 20 and body["total_blocks"] == 20

    # 分批断言：批数 = ceil(20/15) = 2，批大小 ≤15
    assert len(gw.calls) == 2
    payloads = gw.user_payloads()
    assert len(payloads[0]) == 15 and len(payloads[1]) == 5
    assert all(call["app_key"] == "papers_translate" for call in gw.calls)

    # COS 落盘：key 恒 parsed/{id}/translation.json（每批增量写回一次 = 2 批 2 次），
    # 内容块 id → 译文
    puts = [k for _, k, _ in storage.puts]
    assert puts == [f"parsed/{pid}/translation.json"] * 2
    data = json.loads(storage.objects[("papers", f"parsed/{pid}/translation.json")])
    assert len(data) == 20
    assert data["p1_b1"] == "译-p1_b1" and data["p1_b20"] == "译-p1_b20"

    # 状态机入库 + 轮询接口回读
    status, error = await _translate_state(pid)
    assert status == "done" and error is None
    r = await client.get(f"/papers/{pid}/translate-status", headers=headers)
    assert r.json()["translate_status"] == "done"

    # 阅读器对照译文接口
    t = await client.get(f"/papers/{pid}/translation", headers=headers)
    assert t.status_code == 200
    assert t.json()["translations"]["p1_b1"] == "译-p1_b1"


async def test_translate_skips_existing_blocks(client, monkeypatch):
    """translation.json 已有 5 块 → 只送剩余 15 块（一批），已译块不再走网关。"""
    pid, storage = await _make_parsed_paper(20, monkeypatch)
    existing = {f"p1_b{i}": f"旧译-{i}" for i in range(1, 6)}
    storage.objects[("papers", f"parsed/{pid}/translation.json")] = json.dumps(
        existing, ensure_ascii=False
    ).encode()
    gw = _patch_gateway(monkeypatch)

    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["translate_status"] == "done"

    assert len(gw.calls) == 1  # 只一批（跳过已译 5 块）
    sent = set(gw.user_payloads()[0])
    assert "p1_b1" not in sent and "p1_b5" not in sent
    assert "p1_b6" in sent and "p1_b20" in sent and len(sent) == 15
    # 旧译保留 + 增量合并
    data = json.loads(storage.objects[("papers", f"parsed/{pid}/translation.json")])
    assert data["p1_b1"] == "旧译-1" and data["p1_b20"] == "译-p1_b20"


async def test_translate_json_failure_retries_once(client, monkeypatch):
    """首批返回非 JSON → 同批失败块重试一次（重试只带缺块）；次批正常。"""
    pid, storage = await _make_parsed_paper(20, monkeypatch)
    retried_payloads: list[dict] = []

    def flaky(messages, nth: int) -> str:
        payload = json.loads(messages[-1]["content"])
        if nth == 1:
            return "抱歉，我无法完成翻译"  # 非 JSON：触发整批重试
        retried_payloads.append(payload)
        return json.dumps({bid: f"译-{bid}" for bid in payload}, ensure_ascii=False)

    gw = _patch_gateway(monkeypatch, flaky)
    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["translate_status"] == "done"

    # 第 1 批：首调 15 块失败 → 重试 1 次（仍是缺块口径的 15 块）；第 2 批：1 次
    assert len(gw.calls) == 3
    assert len(retried_payloads[0]) == 15  # 重试带整批缺块
    data = json.loads(storage.objects[("papers", f"parsed/{pid}/translation.json")])
    assert len(data) == 20  # 重试成功后全量落盘


async def test_translate_retry_still_missing_marks_failed_with_progress(client, monkeypatch):
    """重试仍缺块：已得译文照常落盘，整体 failed + translate_error 可重跑。"""
    pid, _ = await _make_parsed_paper(20, monkeypatch)

    def half_bad(messages, nth: int) -> str:
        payload = json.loads(messages[-1]["content"])
        # 每批只回前一半键（后半缺块），重试也一样 → 稳定缺块
        keys = list(payload)[: max(1, len(payload) // 2)]
        return json.dumps({k: f"译-{k}" for k in keys}, ensure_ascii=False)

    _patch_gateway(monkeypatch, half_bad)
    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["translate_status"] == "failed"
    assert "翻译失败" in (body["translate_error"] or "")
    # 每批首调回半、重试回缺块的半：15→7(+4)=11 缺 4；5→2(+1)=3 缺 2；共译 14
    assert body["translated_blocks"] == 14 and body["total_blocks"] == 20

    # 进度保留：failed 后重跑只补缺块（增量语义）
    status, error = await _translate_state(pid)
    assert status == "failed" and error

    def good(messages, nth: int) -> str:
        payload = json.loads(messages[-1]["content"])
        return json.dumps({bid: f"译-{bid}" for bid in payload}, ensure_ascii=False)

    gw = _patch_gateway(monkeypatch, good)
    resp2 = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["translate_status"] == "done"
    # 重跑只送 6 个缺块（4+2，一批）
    assert len(gw.calls) == 1 and len(gw.user_payloads()[0]) == 6


async def test_translate_state_machine_done_idempotent_and_running_409(client, monkeypatch):
    """done 幂等不重复调网关；running 拒重入（API 409）；force 重新翻译全量重译。"""
    pid, _ = await _make_parsed_paper(20, monkeypatch)
    gw = _patch_gateway(monkeypatch)
    headers = await login(client)

    r1 = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert r1.status_code == 200 and r1.json()["translate_status"] == "done"
    assert len(gw.calls) == 2

    # done 幂等：再触发零网关调用
    r2 = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert r2.status_code == 200 and r2.json()["translate_status"] == "done"
    assert len(gw.calls) == 2

    # running 态：409
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.translate_status = "running"
        await db.commit()
    r3 = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert r3.status_code == 409

    # force（重新翻译）：清缓存全量重译（20 块再分两批）
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one()
        paper.translate_status = "done"
        await db.commit()
    r4 = await client.post(f"/papers/{pid}/translate", json={"force": True}, headers=headers)
    assert r4.status_code == 200 and r4.json()["translate_status"] == "done"
    assert len(gw.calls) == 4  # 又两批


async def test_translate_api_guards(client, monkeypatch):
    """守卫：非归属 404；非库内 403；解析未 done 409；未登录 401。"""
    pid, _ = await _make_parsed_paper(6, monkeypatch)
    gw = _patch_gateway(monkeypatch)
    headers = await login(client)

    # 解析未 done → 409（库里行 parse_status 初始 none）
    pid_raw = await _make_paper(url="https://oa.example/raw.pdf")
    async with SessionLocal() as db:
        uid = (await db.execute(select(Paper.user_id).where(Paper.id == pid_raw))).scalar_one()
        from app.models.papers import PaperLibrary

        db.add(PaperLibrary(paper_id=pid_raw, user_id=uid, added_via="crawl"))
        await db.commit()
    r0 = await client.post(f"/papers/{pid_raw}/translate", json={}, headers=headers)
    assert r0.status_code == 409

    # 非库内（有归属未加库）→ 403
    pid_mine = await _make_paper(url="https://oa.example/mine.pdf")
    async with SessionLocal() as db:
        paper = (await db.execute(select(Paper).where(Paper.id == pid_mine))).scalar_one()
        paper.parse_status = "done"
        await db.commit()
    r1 = await client.post(f"/papers/{pid_mine}/translate", json={}, headers=headers)
    assert r1.status_code == 403

    # 非归属（不存在的 id 走 404 语义）+ 未登录 401
    r2 = await client.post("/papers/999999/translate", json={}, headers=headers)
    assert r2.status_code == 404
    r3 = await client.post(f"/papers/{pid}/translate", json={})
    assert r3.status_code == 401
    assert gw.calls == []  # 守卫拦截零网关调用


async def test_translate_real_gateway_mock_model_logs_and_fails(client, monkeypatch):
    """真连网关（seed mock 模型）：JSON 键不符 → 缺块 failed；llm_call_logs 记账。

    不打 model_caller 补丁，走完整路由解析（默认路由回落）+ 记账链路；
    mock 模型返回记账模板 JSON（键不是块 id）→ 整批缺块 → 重试一次仍缺 →
    failed；调用日志 app_key=papers_translate（费用随网关记账口径）。
    """
    pid, _ = await _make_parsed_paper(6, monkeypatch)  # 单批 6 块
    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["translate_status"] == "failed"
    assert "翻译失败" in (body["translate_error"] or "")

    async with SessionLocal() as db:
        logs = (
            await db.execute(
                select(LLMCallLog).where(LLMCallLog.app_key == "papers_translate")
            )
        ).scalars().all()
    assert len(logs) >= 2  # 首调 + 重试各记一笔
    assert any(log.success for log in logs)  # mock 调用本身成功（HTTP 层）


async def test_auto_translate_pref_on_triggers_after_parse_done(client, monkeypatch):
    """papers_prefs.auto_translate=true：解析 done 自动触发翻译（mock 网关全链）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/auto.pdf")
    storage = MemoryStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/auto.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(storage))
    _patch_storage(monkeypatch, storage)
    gw = _patch_gateway(monkeypatch)

    headers = await login(client)
    # 开启自动翻译（papers_prefs 合并写，保留其他缺省）
    me = await client.get("/me", headers=headers)
    prefs = dict(((me.json().get("settings") or {}).get("papers_prefs")) or {})
    prefs["auto_translate"] = True
    r = await client.put("/me/settings", json={"key": "papers_prefs", "value": prefs}, headers=headers)
    assert r.status_code == 200, r.text

    # 库内发起解析 → done → 自动翻译 → translation.json 落 COS
    async with SessionLocal() as db:
        uid = (await db.execute(select(Paper.user_id).where(Paper.id == pid))).scalar_one()
        from app.models.papers import PaperLibrary

        db.add(PaperLibrary(paper_id=pid, user_id=uid, added_via="crawl"))
        await db.commit()
    resp = await client.post(f"/papers/{pid}/collect-parse", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["parse_status"] == "done"

    status, _ = await _translate_state(pid)
    assert status == "done"
    assert len(gw.calls) >= 1  # 自动触发了网关翻译
    data = json.loads(storage.objects[("papers", f"parsed/{pid}/translation.json")])
    # MinerU mock zip 的 content_list 有 2 个 text 块（a/b）
    assert data == {"p1_b1": "译-p1_b1", "p2_b1": "译-p2_b1"}


async def test_auto_translate_pref_off_no_gateway(client, monkeypatch):
    """默认关：解析 done 不触发翻译（零网关调用，translate_status 保持空）。"""
    await _add_mineru_key()
    pid = await _make_paper(url="https://oa.example/noauto.pdf")
    storage = MemoryStorage()
    fake = FakeHttpClient(_mineru_routes({
        ("GET", "https://oa.example/noauto.pdf"): _FakeResp(content=_FAKE_PDF),
    }))
    monkeypatch.setattr(paper_parse, "get_http_client", lambda: fake)
    monkeypatch.setattr(paper_parse, "get_storage", lambda db: _async(storage))
    _patch_storage(monkeypatch, storage)
    gw = _patch_gateway(monkeypatch)

    async with SessionLocal() as db:
        uid = (await db.execute(select(Paper.user_id).where(Paper.id == pid))).scalar_one()
        from app.models.papers import PaperLibrary

        db.add(PaperLibrary(paper_id=pid, user_id=uid, added_via="crawl"))
        await db.commit()

    async with SessionLocal() as db:
        result = await paper_parse.run_parse_pipeline(db, pid, 1)
    assert result["parse_status"] == "done"
    assert gw.calls == []  # 默认关：零翻译调用
    status, _ = await _translate_state(pid)
    assert status == "none"


async def test_translate_cascade_delete_removes_translation(client, monkeypatch):
    """级联删除回收 translation.json（COS 产物五件口径）。"""
    from app.services import paper_library

    pid, storage = await _make_parsed_paper(4, monkeypatch)
    _patch_gateway(monkeypatch)
    headers = await login(client)
    resp = await client.post(f"/papers/{pid}/translate", json={}, headers=headers)
    assert resp.json()["translate_status"] == "done"
    assert ("papers", f"parsed/{pid}/translation.json") in storage.objects

    # 直接调服务级联删（SpyStorage 语义在 test_papers_library 已覆盖接口层）
    async with SessionLocal() as db:
        uid = (await db.execute(select(Paper.user_id).where(Paper.id == pid))).scalar_one()
        result = await paper_library.delete_from_library(db, pid, uid)
    assert f"parsed/{pid}/translation.json" in result["cos_deleted"]
    assert ("papers", f"parsed/{pid}/translation.json") not in storage.objects


def test_extract_translation_json_unit():
    """纯函数：code fence 剥离 / 首个 {...} 截取 / 非 JSON 抛错。"""
    assert paper_translate.extract_translation_json(
        '```json\n{"p1_b1": "译文"}\n```'
    ) == {"p1_b1": "译文"}
    assert paper_translate.extract_translation_json(
        '说明文字 {"p1_b1": "译文", "p1_b2": "乙"} 尾巴'
    ) == {"p1_b1": "译文", "p1_b2": "乙"}
    with pytest.raises(ValueError):
        paper_translate.extract_translation_json("抱歉无法翻译")
    with pytest.raises(ValueError):
        paper_translate.extract_translation_json("[1,2,3]")
    # 空串值被过滤；全空抛错
    with pytest.raises(ValueError):
        paper_translate.extract_translation_json('{"a": "  "}')
