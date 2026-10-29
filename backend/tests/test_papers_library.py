"""论文域轮①测试（P22/P23/P24 用户世界隔离 + 我的文献工作台）。

- 抓取按人入库：同关键词两用户各存一份（papers 行级 user_id，去重键
  (user_id, pmid)）；A 抓的 B 看不到（详情/批注/正文/解析状态全 404）；
- 我的文献 CRUD：POST /papers/{id}/library 幂等（重复加入不报错不刷新）；
  GET /papers/library 带元数据 + parse_status + annotations_count；
- 删除级联（P24）：行主删除 = 本人 papers 行 + 本人批注/收藏/归属/库关联 +
  COS 产物四件（parsed/{id} 三件 + pdfs/{yyyy}/{mm}/{id}.pdf，spy 断言）；
  非行主只解除本人归属（共享行对方不受影响，双向断言）；
- 迁移 0011 回填口径：最早 paper_users 归属人；无归属归 admin；origin 回落
  crawl；pmid 全局唯一降级为 (user_id, pmid) 唯一。
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models.papers import Paper, PaperFavorite, PaperLibrary, PaperNote, PaperUser
from app.models.user import User
from app.services import llm_gateway, papers_crawl
from app.services.sources import pubmed as pubmed_source
from app.services.storage import Storage
from tests.conftest import login

INTERNAL_TOKEN = "pytest-internal-token-0123456789abcdef"

# 两篇假文献（与 test_papers_stepb 同构：一篇命中 1 词、一篇命中 2 词）
_FAKE_EFETCH_XML = """<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>920001</PMID><Article>
<ArticleTitle>Isolation alpha cohort</ArticleTitle>
<Abstract><AbstractText>We studied alzheimer biomarkers in cohorts.</AbstractText></Abstract>
<Journal><ISOAbbreviation>J Alzheimers Dis</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Zhang</LastName><Initials>XM</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>920002</PMID><Article>
<ArticleTitle>Isolation dementia pathway</ArticleTitle>
<Abstract><AbstractText>alzheimer dementia care pathway analysis.</AbstractText></Abstract>
<Journal><ISOAbbreviation>Dementia</ISOAbbreviation><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Li</LastName><Initials>Y</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


async def _async(value):
    return value


async def _mkuser(client, admin: dict, username: str) -> dict:
    resp = await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code in (200, 201), resp.text
    return await login(client, username, "pass-123")


async def _mock_pubmed(monkeypatch):
    async def fake_esearch(client, keyword, retmax, days_back):
        return ["920001", "920002"]

    async def fake_efetch(client, pmids_arg):
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


async def _subscribe(client, headers):
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


class DeleteSpyStorage(Storage):
    """级联删 COS 断言替身：记录 delete 调用、按前缀 list。"""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.deleted: list[str] = []

    async def put(self, app: str, key: str, data: bytes) -> None:  # pragma: no cover
        self.files[f"{app}/{key}"] = bytes(data)

    async def get(self, app: str, key: str) -> bytes:  # pragma: no cover
        return self.files[f"{app}/{key}"]

    async def delete(self, app: str, key: str) -> None:
        self.deleted.append(f"{app}/{key}")
        self.files.pop(f"{app}/{key}", None)

    async def exists(self, app: str, key: str) -> bool:  # pragma: no cover
        return f"{app}/{key}" in self.files

    async def list(self, app: str, prefix: str) -> list[str]:
        full = f"{app}/{prefix}"
        return sorted(k[len(app) + 1:] for k in self.files if k.startswith(full))


async def _make_owned_paper(username: str, pmid: str, **kwargs) -> int:
    """插一篇归属指定用户的文献（行级 user_id + paper_users，绕过抓取管线）。"""
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == username))).scalar_one()
        paper = Paper(
            pmid=pmid,
            source="pubmed",
            title=kwargs.get("title", f"Paper {pmid}"),
            abstract=kwargs.get("abstract", "abstract"),
            journal="J Lib",
            user_id=uid,
        )
        db.add(paper)
        await db.commit()
        await db.refresh(paper)
        db.add(PaperUser(paper_id=paper.id, user_id=uid))
        await db.commit()
        return paper.id


# ── 抓取按人入库：同一篇两人抓各存一份；A 抓的 B 看不到（双向）─────────
async def test_crawl_per_user_rows_and_two_way_isolation(client, monkeypatch):
    await _mock_pubmed(monkeypatch)
    admin = await login(client)
    userb = await _mkuser(client, admin, "libiso-b")
    await _subscribe(client, admin)
    await _subscribe(client, userb)

    resp = await client.post(
        "/internal/jobs/papers-crawl", headers={"X-Internal-Token": INTERNAL_TOKEN}
    )
    assert resp.json() == {"added": 4}  # 2 篇 × 2 用户各存一份（P23）

    a_daily = (await client.get("/papers/daily", headers=admin)).json()
    b_daily = (await client.get("/papers/daily", headers=userb)).json()
    a_ids = {p["id"] for p in a_daily}
    b_ids = {p["id"] for p in b_daily}
    assert len(a_ids) == 2 and len(b_ids) == 2
    assert a_ids.isdisjoint(b_ids)  # 行级隔离：不是共享行

    # A 抓的 B 看不到：详情/批注列表/正文/解析状态全部 404（不泄露存在性）
    some_a_pid = next(iter(a_ids))
    for method, url in (
        ("GET", f"/papers/{some_a_pid}"),
        ("GET", f"/papers/{some_a_pid}/annotations"),
        ("GET", f"/papers/{some_a_pid}/content"),
        ("GET", f"/papers/{some_a_pid}/parse-status"),
    ):
        resp = await client.request(method, url, headers=userb)
        assert resp.status_code == 404, f"{method} {url} 应对 B 404，得 {resp.status_code}"
    resp = await client.post(
        f"/papers/{some_a_pid}/annotations",
        json={"anchor_quote": "q", "anchor_block_id": "p1_b1", "body": "b"},
        headers=userb,
    )
    assert resp.status_code == 404  # B 也建不了 A 的批注
    # B 的收藏列表也不含 A 的行（收藏隔离走 paper_favorites user 过滤）
    b_favs = (await client.get("/papers/favorites", headers=userb)).json()
    assert all(p["id"] not in a_ids for p in b_favs)


# ── 我的文献 CRUD + 幂等 ─────────────────────────────────
async def test_library_add_idempotent_and_list_fields(client):
    admin = await login(client)
    pid = await _make_owned_paper("admin", "lib-crud-1", title="CRUD target")

    # 加入幂等：两次加入都 200 且不报错
    for _ in range(2):
        resp = await client.post(f"/papers/{pid}/library", headers=admin)
        assert resp.status_code == 200
        assert resp.json() == {"in_library": True}

    async with SessionLocal() as db:
        rows = (
            await db.execute(select(PaperLibrary).where(PaperLibrary.paper_id == pid))
        ).scalars().all()
        assert len(rows) == 1  # 幂等：仍只有一行
        assert rows[0].added_via == "crawl"

    # 列表带元数据 + parse_status + 批注数
    items = (await client.get("/papers/library", headers=admin)).json()
    (item,) = [i for i in items if i["id"] == pid]
    assert item["title"] == "CRUD target"
    assert item["parse_status"] == "none"
    assert item["annotations_count"] == 0
    assert item["added_via"] == "crawl"
    assert item["added_at"] is not None

    # 批注后计数联动（直接插 annotation 行，单测列表统计口径）
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperNote(
            paper_id=pid, user_id=uid, content="划线", note_kind="annotation",
            anchor_quote="q", anchor_block_id="p1_b1", links=[],
        ))
        await db.commit()
    items = (await client.get("/papers/library", headers=admin)).json()
    (item,) = [i for i in items if i["id"] == pid]
    assert item["annotations_count"] == 1

    # 他人看不到我的库（行级隔离）
    userb = await _mkuser(client, admin, "lib-crud-b")
    assert (await client.get("/papers/library", headers=userb)).json() == []

    # 越权加入他人不可见文献：A 的行 B 加不进（归属校验 404）
    resp = await client.post(f"/papers/{pid}/library", headers=userb)
    assert resp.status_code == 404


# ── 删除级联（P24）：papers 行 + 批注 + COS 四件 + 收藏/归属/库关联 ──
async def test_delete_from_library_cascades_with_cos_spy(client, monkeypatch):
    from app.services import paper_library as lib_service

    admin = await login(client)
    pid = await _make_owned_paper("admin", "lib-del-1")
    uid = None
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperFavorite(paper_id=pid, user_id=uid))
        db.add(PaperNote(
            paper_id=pid, user_id=uid, content="全文笔记", note_kind="note", links=[],
        ))
        db.add(PaperNote(
            paper_id=pid, user_id=uid, content="批注", note_kind="annotation",
            anchor_quote="q", anchor_block_id="p1_b1", links=[],
        ))
        await db.commit()

    # COS 上预置五件产物（P20 目录结构 + 轮③ P27 译文缓存）+ 一篇他人的 PDF 干扰项
    other_pdf_key = "papers/pdfs/2026/10/999999.pdf"
    spy = DeleteSpyStorage(
        {
            f"papers/parsed/{pid}/full.md": b"# full",
            f"papers/parsed/{pid}/content_list.json": b"[]",
            f"papers/parsed/{pid}/meta.json": b"{}",
            f"papers/parsed/{pid}/translation.json": b"{}",
            f"papers/pdfs/2026/11/{pid}.pdf": b"%PDF-",
            other_pdf_key: b"%PDF-",
        }
    )
    monkeypatch.setattr(lib_service, "get_storage", lambda db: _async(spy))

    resp = await client.delete(f"/papers/{pid}/library", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["deleted_paper"] is True
    # COS 五件全清（parsed 四件含译文 + 本人 PDF），他人 PDF 不动
    assert set(body["cos_deleted"]) == {
        f"parsed/{pid}/full.md",
        f"parsed/{pid}/content_list.json",
        f"parsed/{pid}/meta.json",
        f"parsed/{pid}/translation.json",
        f"pdfs/2026/11/{pid}.pdf",
    }
    assert set(spy.deleted) == {f"papers/{k}" for k in body["cos_deleted"]}
    assert other_pdf_key in spy.files  # 干扰项未被误删

    # 库内全清：papers 行 / 批注 / 全文笔记 / 收藏 / 归属 / 库行
    async with SessionLocal() as db:
        assert (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one_or_none() is None
        assert (await db.execute(
            select(PaperNote).where(PaperNote.paper_id == pid)
        )).scalars().all() == []
        assert (await db.execute(
            select(PaperFavorite).where(PaperFavorite.paper_id == pid)
        )).scalars().all() == []
        assert (await db.execute(
            select(PaperUser).where(PaperUser.paper_id == pid)
        )).scalars().all() == []
        assert (await db.execute(
            select(PaperLibrary).where(PaperLibrary.paper_id == pid)
        )).scalars().all() == []
    # 删除后列表为空
    assert (await client.get("/papers/library", headers=admin)).json() == []
    # 再删一次幂等（行已不存在：归属校验 404，不炸 500）
    resp = await client.delete(f"/papers/{pid}/library", headers=admin)
    assert resp.status_code == 404


# ── 删除隔离（P23 双向）：A 删自己的不影响 B ─────────────────
async def test_delete_does_not_affect_other_user(client):
    admin = await login(client)
    userb = await _mkuser(client, admin, "lib-del-b")
    # 同一 pmid 两人各一份（P23：各存一份）
    pid_a = await _make_owned_paper("admin", "lib-shared-pmid")
    pid_b = await _make_owned_paper("lib-del-b", "lib-shared-pmid")
    async with SessionLocal() as db:
        uid_b = (await db.execute(
            select(User.id).where(User.username == "lib-del-b")
        )).scalar_one()
        db.add(PaperFavorite(paper_id=pid_b, user_id=uid_b))
        await db.commit()

    await client.post(f"/papers/{pid_a}/library", headers=admin)
    await client.post(f"/papers/{pid_b}/library", headers=userb)

    # A 删除自己的 → A 的行没了，B 的一切原样
    resp = await client.delete(f"/papers/{pid_a}/library", headers=admin)
    assert resp.status_code == 200

    async with SessionLocal() as db:
        assert (await db.execute(select(Paper).where(Paper.id == pid_a))).scalar_one_or_none() is None
        b_row = (await db.execute(select(Paper).where(Paper.id == pid_b))).scalar_one()
        assert b_row.pmid == "lib-shared-pmid"
        favs = (await db.execute(
            select(PaperFavorite).where(PaperFavorite.paper_id == pid_b)
        )).scalars().all()
        assert len(favs) == 1

    b_items = (await client.get("/papers/library", headers=userb)).json()
    assert [i["id"] for i in b_items] == [pid_b]
    # B 的行 A 从未拥有：A 详情 404 保持
    assert (await client.get(f"/papers/{pid_b}", headers=admin)).status_code == 404


# ── 非行主删除：历史共享行只解除本人归属，不动行与产物 ──────
async def test_delete_non_owner_only_detaches(client, monkeypatch):
    from app.services import paper_library as lib_service

    admin = await login(client)
    userb = await _mkuser(client, admin, "lib-detach-b")
    # 模拟历史公共行：行主是 B，但 A 也有归属（paper_users 双归属）
    pid_b = await _make_owned_paper("lib-detach-b", "lib-detach-1")
    async with SessionLocal() as db:
        uid_a = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperUser(paper_id=pid_b, user_id=uid_a))
        await db.commit()

    spy = DeleteSpyStorage({f"papers/pdfs/2026/11/{pid_b}.pdf": b"%PDF-"})
    monkeypatch.setattr(lib_service, "get_storage", lambda db: _async(spy))

    await client.post(f"/papers/{pid_b}/library", headers=admin)
    resp = await client.delete(f"/papers/{pid_b}/library", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_paper"] is False  # 非行主：不删行
    assert body["cos_deleted"] == []  # 不动产物
    assert spy.deleted == []

    # 行还在，A 的归属/库行已解除，B 的归属还在
    async with SessionLocal() as db:
        assert (await db.execute(select(Paper).where(Paper.id == pid_b))).scalar_one_or_none() is not None
        a_users = (await db.execute(
            select(PaperUser).where(PaperUser.paper_id == pid_b, PaperUser.user_id == uid_a)
        )).scalars().all()
        assert a_users == []
    b_items = (await client.get("/papers/library", headers=userb)).json()  # B 未加库，空
    assert b_items == []
    assert (await client.get(f"/papers/{pid_b}", headers=userb)).status_code == 200  # B 仍可见


# ── 迁移 0011：存量行回填口径（最早归属人 / 无归属归 admin）────
async def test_migration_0011_backfill_user_id(client):
    """降级到 0010 → 造存量数据 → 升级到 head：回填口径逐条断言。"""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")  # 要求 CWD = backend/
    await asyncio.to_thread(command.downgrade, cfg, "0010")
    try:
        async with SessionLocal() as db:
            admin_id = (
                await db.execute(select(User.id).where(User.username == "admin"))
            ).scalar_one()
            bob = (await client.post(
                "/admin/users",
                json={"username": "bf-bob", "password": "pass-123", "role_ids": []},
                headers=await login(client),
            ))
            assert bob.status_code in (200, 201), bob.text
            bob_id = bob.json()["id"]

            # 0010 态的 papers 没有 user_id/origin 列：裸 SQL 插三篇
            await db.execute(text("INSERT INTO papers (pmid, source, title) VALUES ('bf-a', 'pubmed', 'A')"))
            await db.execute(text("INSERT INTO papers (pmid, source, title) VALUES ('bf-b', 'pubmed', 'B')"))
            await db.execute(text("INSERT INTO papers (pmid, source, title) VALUES ('bf-c', 'pubmed', 'C')"))
            await db.commit()
            id_a = (await db.execute(select(Paper.id).where(Paper.pmid == "bf-a"))).scalar_one()
            id_c = (await db.execute(select(Paper.id).where(Paper.pmid == "bf-c"))).scalar_one()
            now = datetime.now(UTC)
            # bf-a：两个归属人（bob 早、admin 晚）→ 回填 bob（最早归属人）
            await db.execute(text(
                "INSERT INTO paper_users (paper_id, user_id, created_at) VALUES (:pid, :uid, :ts)"
            ), {"pid": id_a, "uid": bob_id, "ts": now - timedelta(hours=2)})
            await db.execute(text(
                "INSERT INTO paper_users (paper_id, user_id, created_at) VALUES (:pid, :uid, :ts)"
            ), {"pid": id_a, "uid": admin_id, "ts": now - timedelta(hours=1)})
            # bf-c：单归属 admin → admin
            await db.execute(text(
                "INSERT INTO paper_users (paper_id, user_id, created_at) VALUES (:pid, :uid, :ts)"
            ), {"pid": id_c, "uid": admin_id, "ts": now - timedelta(hours=3)})
            # bf-b：无归属 → admin
            await db.commit()

        await asyncio.to_thread(command.upgrade, cfg, "head")

        async with SessionLocal() as db:
            rows = (
                await db.execute(select(Paper.id, Paper.pmid, Paper.user_id, Paper.origin))
            ).all()
            by_pmid = {pmid: (pid, uid, origin) for pid, pmid, uid, origin in rows}
            assert by_pmid["bf-a"][1] == bob_id  # 最早归属人
            assert by_pmid["bf-b"][1] == admin_id  # 无归属归 admin
            assert by_pmid["bf-c"][1] == admin_id
            assert all(origin == "crawl" for _, _, origin in by_pmid.values())  # origin 回落
            # user_id 回填后无 NULL
            assert all(uid is not None for _, uid, _ in by_pmid.values())
    finally:
        # 无论断言成败都回到 head，不污染后续用例
        await asyncio.to_thread(command.upgrade, cfg, "head")
