"""论文域后批①测试（P8 批注式笔记 + 知识网）。

- block_id 稳定性：normalize_content_list 对多类型/多页混合块的 `p{页}_b{页内序}`
  标识规则（含 image/table 计数、纯函数幂等）；
- GET /papers/{id}/content：结构化段落（text_level/table 去标签/image caption）、
  无解析产物 404、归属隔离（他人文献 404）；
- 批注 CRUD：建（201，body 可空=纯划线）/列表（id 升序）/改 body/换出链/删除；
  行级隔离（B 看不到改不了删不了 A 的批注，统一 404 不泄露存在性）；
- 校验：锚定段落不在解析产物 422；空 anchor_quote 422；自链 422；越权/不存在
  出链目标 422；出链保序去重；
- 双向链接：A 链 B → B 的 backlinks 含 A 且列表 backlink_count=1（派生，非双写）；
  删除节点级联摘除指向它的出链；/papers/annotations/recent 跨论文倒序；
- 兼容：旧 POST /note upsert 语义不变（每篇至多一条 note_kind='note'，二次 upsert
  仍一行；直接再插 legacy 行撞部分唯一索引）；批注与全文笔记同篇共存；
- /papers/parsed：条目带 annotations_count / last_annotation_at。
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.papers import Paper, PaperFavorite, PaperNote, PaperUser
from app.models.user import User
from app.services import paper_content
from app.services.storage import Storage, StorageNotFoundError
from tests.conftest import login

# 多类型多页混合样例（模拟 MinerU content_list.json 实测结构）
SAMPLE_CONTENT: list[dict] = [
    {"type": "text", "text": "Background on neurodegeneration", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "First paragraph about alpha-synuclein aggregation.", "page_idx": 0},
    {"type": "image", "img_path": "images/fig1.jpg", "image_caption": ["Figure 1: pathway"], "page_idx": 0},
    {"type": "text", "text": "Second paragraph spans methods and cohort.", "page_idx": 0},
    {"type": "table", "table_body": "<table><tr><td>A</td><td>B</td></tr></table>", "page_idx": 1},
    {"type": "text", "text": "Results paragraph with p-values.", "text_level": 2, "page_idx": 1},
]


class DictStorage(Storage):
    """可读存储替身：按 {app}/{key} 查表，未命中抛 StorageNotFoundError。"""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)

    async def get(self, app: str, key: str) -> bytes:
        full = f"{app}/{key}"
        if full not in self.files:
            raise StorageNotFoundError(full)
        return self.files[full]

    async def put(self, app: str, key: str, data: bytes) -> None:  # pragma: no cover
        self.files[f"{app}/{key}"] = bytes(data)

    async def delete(self, app: str, key: str) -> None:  # pragma: no cover
        raise StorageNotFoundError(key)

    async def exists(self, app: str, key: str) -> bool:  # pragma: no cover
        return f"{app}/{key}" in self.files


async def _async(value):
    return value


def _content_storage(*pids: int) -> DictStorage:
    files: dict[str, bytes] = {}
    for pid in (pids or (1,)):
        files[f"papers/parsed/{pid}/content_list.json"] = json.dumps(SAMPLE_CONTENT).encode()
    return DictStorage(files)


async def _mkuser(client, admin: dict, username: str) -> dict:
    resp = await client.post(
        "/admin/users",
        json={"username": username, "password": "pass-123", "role_ids": []},
        headers=admin,
    )
    assert resp.status_code in (200, 201), resp.text
    return await login(client, username, "pass-123")


async def _make_parsed_paper(username: str = "admin") -> int:
    """插一篇 done 文献并归属指定用户（绕过抓取/解析管线，单测批注链路）。"""
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == username))).scalar_one()
        paper = Paper(
            pmid=f"anno-test:{username}",
            source="pubmed",
            title="Annotation target paper",
            abstract="abstract",
            journal="J Anno",
            parse_status="done",
            parsed_at=None,
        )
        db.add(paper)
        await db.commit()
        await db.refresh(paper)
        db.add(PaperUser(paper_id=paper.id, user_id=uid))
        db.add(PaperFavorite(paper_id=paper.id, user_id=uid))
        await db.commit()
        return paper.id


async def _create_annotation(client, headers, pid: int, quote: str, block: str, body: str = ""):
    resp = await client.post(
        f"/papers/{pid}/annotations",
        json={"anchor_quote": quote, "anchor_block_id": block, "body": body},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── block_id 稳定性（纯函数，锚定规则）────────────────────
def test_block_id_rule_mixed_types_and_pages():
    """`p{页}_b{页内序}`：页 1 起、页内序 1 起，image/table 参与计数；幂等。"""
    blocks = paper_content.normalize_content_list(SAMPLE_CONTENT)
    assert [b["block_id"] for b in blocks] == [
        "p1_b1", "p1_b2", "p1_b3", "p1_b4", "p2_b1", "p2_b2",
    ]
    # 纯函数幂等：同一输入恒同输出（稳定性核心断言）
    assert paper_content.normalize_content_list(SAMPLE_CONTENT) == blocks


def test_block_text_extraction_table_html_and_image_caption():
    """table_body HTML 去标签、image_caption 拼接、text_level 透传。"""
    blocks = paper_content.normalize_content_list(SAMPLE_CONTENT)
    assert blocks[0]["text_level"] == 1 and blocks[0]["type"] == "text"
    assert blocks[2]["type"] == "image" and blocks[2]["text"] == "Figure 1: pathway"
    assert blocks[4]["type"] == "table" and blocks[4]["text"] == "A B"
    assert blocks[5]["text_level"] == 2
    assert all(b["page_idx"] in (0, 1) for b in blocks)


def test_normalize_defensive_on_garbage():
    """非法输入（非数组/坏项）不炸：非数组→空数组，坏项跳过，缺字段回落。"""
    assert paper_content.normalize_content_list({"not": "list"}) == []
    assert paper_content.normalize_content_list(None) == []
    blocks = paper_content.normalize_content_list([
        "garbage",
        {"text": "no type no page"},  # type/page_idx 缺省回落
    ])
    assert len(blocks) == 1 and blocks[0]["block_id"] == "p1_b1"
    assert blocks[0]["type"] == "text" and blocks[0]["page_idx"] == 0


def test_build_block_id_direct():
    assert paper_content.build_block_id(0, 1) == "p1_b1"
    assert paper_content.build_block_id(2, 5) == "p3_b5"


# ── GET /papers/{id}/content ─────────────────────────────
async def test_content_endpoint_returns_blocks_and_validates_ownership(client, monkeypatch):
    """content 200 带结构化块；无产物 404；他人文献 404（归属隔离）。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    bob = await _mkuser(client, admin, "anno_bob")
    pid = await _make_parsed_paper("admin")

    resp = await client.get(f"/papers/{pid}/content", headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paper_id"] == pid
    assert body["title"] == "Annotation target paper"
    assert len(body["blocks"]) == len(SAMPLE_CONTENT)
    assert body["blocks"][0]["block_id"] == "p1_b1"
    assert body["blocks"][4]["text"] == "A B"  # table 去标签

    # 他人文献 → 404（paper_users 无行，不泄露存在性）
    resp2 = await client.get(f"/papers/{pid}/content", headers=bob)
    assert resp2.status_code == 404


async def test_content_endpoint_404_without_parse_product(client, monkeypatch):
    """无解析产物（存储未命中）→ 404 明确语义，不返回半成品。"""
    monkeypatch.setattr(paper_content, "get_storage", lambda db: _async(DictStorage({})))
    admin = await login(client)
    pid = await _make_parsed_paper("admin")
    resp = await client.get(f"/papers/{pid}/content", headers=admin)
    assert resp.status_code == 404
    assert "解析产物" in resp.json()["detail"]


# ── 批注 CRUD + 行级隔离 ─────────────────────────────────
async def test_annotation_crud_cycle(client, monkeypatch):
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    pid = await _make_parsed_paper("admin")

    # 建：纯划线（body 空串）+ 带正文
    mark = await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2")
    assert mark["note_kind"] == "annotation" and mark["body"] == ""
    assert mark["backlink_count"] == 0
    full = await _create_annotation(
        client, admin, pid, "Second paragraph spans", "p1_b4", " cohort 很重要"
    )
    assert full["body"] == " cohort 很重要"

    # 列表：id 升序，含 links/backlink_count 字段
    lst = (await client.get(f"/papers/{pid}/annotations", headers=admin)).json()
    assert [a["id"] for a in lst] == sorted(a["id"] for a in lst)
    assert {a["anchor_block_id"] for a in lst} == {"p1_b2", "p1_b4"}

    # 改 body
    r = await client.put(
        f"/papers/annotations/{mark['id']}",
        json={"body": "补写想法"},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["body"] == "补写想法"

    # 删
    r = await client.delete(f"/papers/annotations/{mark['id']}", headers=admin)
    assert r.status_code == 200 and r.json() == {"ok": True}
    lst2 = (await client.get(f"/papers/{pid}/annotations", headers=admin)).json()
    assert [a["id"] for a in lst2] == [full["id"]]


async def test_annotation_isolation_between_users(client, monkeypatch):
    """B 看不到/改不了/删不了 A 的批注（统一 404）；A 列表不含 B 的批注。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    bob = await _mkuser(client, admin, "anno_bob2")
    pid = await _make_parsed_paper("admin")
    # bob 也拥有该文献（同篇推送两人），但批注仍各自私有
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "anno_bob2"))).scalar_one()
        db.add(PaperUser(paper_id=pid, user_id=uid))
        await db.commit()

    mine = await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2", "A 的想法")
    # 同篇共有人 B：列表可见但只含自己的（隔离 = 行级而非篇级）
    assert (await client.get(f"/papers/{pid}/annotations", headers=bob)).json() == []

    for method, path, kwargs in (
        ("PUT", f"/papers/annotations/{mine['id']}", {"json": {"body": "篡改"}}),
        ("DELETE", f"/papers/annotations/{mine['id']}", {}),
        ("GET", f"/papers/annotations/{mine['id']}/backlinks", {}),
    ):
        resp = await client.request(method, path, headers=bob, **kwargs)
        assert resp.status_code == 404, f"{method} {path} 应 404，得 {resp.status_code}"
    # A 的批注原样未动
    still = (
        await client.get(f"/papers/annotations/{mine['id']}/backlinks", headers=admin)
    )
    assert still.status_code == 200


async def test_annotation_validation_errors(client, monkeypatch):
    """锚定段落不存在 422 / 空 quote 422 / 自链 422 / 越权目标 422 / 出链去重。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    pid = await _make_parsed_paper("admin")

    r = await client.post(
        f"/papers/{pid}/annotations",
        json={"anchor_quote": "x", "anchor_block_id": "p9_b9", "body": ""},
        headers=admin,
    )
    assert r.status_code == 422  # 解析产物里没这个块

    r = await client.post(
        f"/papers/{pid}/annotations",
        json={"anchor_quote": "", "anchor_block_id": "p1_b2", "body": ""},
        headers=admin,
    )
    assert r.status_code == 422  # 空选中原文

    a = await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2", "A")
    b = await _create_annotation(client, admin, pid, "Second paragraph spans", "p1_b4", "B")

    r = await client.put(
        f"/papers/annotations/{a['id']}", json={"links": [a["id"]]}, headers=admin
    )
    assert r.status_code == 422  # 自链

    r = await client.put(
        f"/papers/annotations/{a['id']}", json={"links": [999999]}, headers=admin
    )
    assert r.status_code == 422  # 不存在的目标

    # 合法出链：保序去重
    r = await client.put(
        f"/papers/annotations/{a['id']}",
        json={"links": [b["id"], b["id"]]},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["links"] == [b["id"]]


# ── 双向链接（派生 backlinks + 级联摘链）─────────────────
async def test_bidirectional_links_and_cascade_cleanup(client, monkeypatch):
    """A→B 建链：B backlinks 见 A、B backlink_count=1；删 A 后 B 的出链被摘除。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    pid = await _make_parsed_paper("admin")
    a = await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2", "甲")
    b = await _create_annotation(client, admin, pid, "Second paragraph spans", "p1_b4", "乙")

    # 双向：B 链 A，同时 A 链 B（两端各自可见）
    await client.put(
        f"/papers/annotations/{a['id']}", json={"links": [b["id"]]}, headers=admin
    )
    await client.put(
        f"/papers/annotations/{b['id']}", json={"links": [a["id"]]}, headers=admin
    )
    bl_a = (
        await client.get(f"/papers/annotations/{a['id']}/backlinks", headers=admin)
    ).json()
    assert [x["id"] for x in bl_a] == [b["id"]]

    # 列表回读：backlink_count 派生正确（A 被 B 链 1 次）
    lst = {x["id"]: x for x in (
        await client.get(f"/papers/{pid}/annotations", headers=admin)
    ).json()}
    assert lst[a["id"]]["backlink_count"] == 1
    assert lst[b["id"]]["backlink_count"] == 1

    # 删 A：B 的出链里不再含 A（边随节点删，无悬空引用）
    await client.delete(f"/papers/annotations/{a['id']}", headers=admin)
    lst2 = {x["id"]: x for x in (
        await client.get(f"/papers/{pid}/annotations", headers=admin)
    ).json()}
    assert lst2[b["id"]]["links"] == []
    # A→B 边随 A 删除消失，B 的被链数归零
    assert lst2[b["id"]]["backlink_count"] == 0


async def test_recent_annotations_across_papers(client, monkeypatch):
    """互链选择器数据源：跨论文、updated_at 倒序、带篇名。"""
    admin = await login(client)
    pid1 = await _make_parsed_paper("admin")
    async with SessionLocal() as db:
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        p2 = Paper(pmid="anno-test:admin:2", source="pubmed", title="Second paper",
                   abstract="", journal="J2", parse_status="done")
        db.add(p2)
        await db.commit()
        await db.refresh(p2)
        db.add(PaperUser(paper_id=p2.id, user_id=uid))
        db.add(PaperFavorite(paper_id=p2.id, user_id=uid))
        await db.commit()
        pid2 = p2.id
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage(pid1, pid2))
    )

    await _create_annotation(client, admin, pid1, "First paragraph about", "p1_b2", "老")
    await _create_annotation(client, admin, pid2, "Results paragraph with", "p2_b2", "新")

    resp = await client.get("/papers/annotations/recent?limit=20", headers=admin)
    assert resp.status_code == 200
    items = resp.json()
    assert [i["paper_id"] for i in items] == [pid2, pid1]  # 倒序
    assert items[0]["paper_title"] == "Second paper"
    assert items[0]["anchor_quote"] == "Results paragraph with"


# ── 旧全文笔记兼容 + /papers/parsed 统计 ─────────────────
async def test_legacy_note_upsert_and_partial_unique_constraint(client, monkeypatch):
    """旧 /note upsert 语义不变；legacy 行每篇至多一条（部分唯一索引）；批注可多条。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    pid = await _make_parsed_paper("admin")

    r1 = await client.post(f"/papers/{pid}/note", json={"content": "全文笔记 v1"}, headers=admin)
    assert r1.status_code == 200
    r2 = await client.post(f"/papers/{pid}/note", json={"content": "全文笔记 v2"}, headers=admin)
    assert r2.status_code == 200  # upsert 覆盖，不炸

    # 批注多条 + 全文笔记一条共存同篇
    await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2", "批1")
    await _create_annotation(client, admin, pid, "Second paragraph spans", "p1_b4", "批2")
    async with SessionLocal() as db:
        notes = (
            await db.execute(select(PaperNote).where(PaperNote.paper_id == pid))
        ).scalars().all()
        kinds = sorted(n.note_kind for n in notes)
        assert kinds == ["annotation", "annotation", "note"]
        legacy = [n for n in notes if n.note_kind == "note"]
        assert len(legacy) == 1 and legacy[0].content == "全文笔记 v2"

        # 直接再插一条 legacy note → 撞部分唯一索引（批注多行不受影响）
        uid = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        db.add(PaperNote(paper_id=pid, user_id=uid, content="重复", note_kind="note"))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    # 详情仍回读笔记正文（旧行为）
    detail = (await client.get(f"/papers/{pid}", headers=admin)).json()
    assert detail["note"] == "全文笔记 v2"


async def test_parsed_list_carries_annotation_stats(client, monkeypatch):
    """「我的笔记」列表条目带 annotations_count / last_annotation_at。"""
    monkeypatch.setattr(
        paper_content, "get_storage", lambda db: _async(_content_storage())
    )
    admin = await login(client)
    pid = await _make_parsed_paper("admin")
    assert (await client.get("/papers/parsed", headers=admin)).json()[0]["annotations_count"] == 0

    await _create_annotation(client, admin, pid, "First paragraph about", "p1_b2", "x")
    await _create_annotation(client, admin, pid, "Second paragraph spans", "p1_b4", "y")
    # 全文笔记不计入批注统计
    await client.post(f"/papers/{pid}/note", json={"content": "legacy"}, headers=admin)

    items = (await client.get("/papers/parsed", headers=admin)).json()
    assert len(items) == 1
    assert items[0]["annotations_count"] == 2
    assert items[0]["last_annotation_at"] is not None
