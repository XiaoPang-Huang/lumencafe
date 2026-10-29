"""存储抽象层测试（论文域步 D，拍板 P9/P11）。

覆盖：
- P11 前缀硬约束：app 白名单 [a-z0-9_]+；key 禁止 / 开头、..、空段（papers/x 合法，
  ../x / /x / PAPERS / a//b / a/../b 全部 ValueError）；
- parse_cos_endpoint：标准/内网/尾斜线/无 scheme 解析，畸形 endpoint 抛错；
- LocalStorage 全操作（tmp_path 落盘）：put/get/exists/delete 闭环 + 不存在语义；
- CosStorage：凭证缺失/未启用抛 StorageConfigError（不静默降级）；四操作经
  fake client 验证键名恒为 {app}/{key}，404 → StorageNotFoundError/exists False；
- 工厂 get_storage：双行未配置 → Local；只配置一行 → 抛错；两行齐备 → CosStorage。
"""

import io
from pathlib import Path

import pytest
from qcloud_cos.cos_exception import CosServiceError

import app.services.storage as storage_module
from app.db import SessionLocal
from app.models.service_key import ServiceKey
from app.services.storage import (
    CosStorage,
    LocalStorage,
    StorageConfigError,
    StorageNotFoundError,
    build_object_key,
    get_storage,
    parse_cos_endpoint,
)

ENDPOINT = "https://lumencafe-papers-1234567890.cos.ap-guangzhou.myqcloud.com"


# ---------- P11 前缀校验 ----------

@pytest.mark.parametrize(
    ("app", "key"),
    [
        ("papers", "2026/abc.pdf"),
        ("papers", "x"),
        ("chat", "a/b/c.txt"),
        ("a", "k"),
        ("app_2", "k"),
    ],
)
def test_object_key_legal(app, key):
    assert build_object_key(app, key) == f"{app}/{key}"


@pytest.mark.parametrize(
    ("app", "key"),
    [
        ("PAPERS", "x"),  # 大写拒绝（白名单 [a-z0-9_]+）
        ("Papers", "x"),
        ("papers", "../x"),  # 路径逃逸拒绝
        ("papers", "a/../b"),
        ("papers", ".."),
        ("papers", "/x"),  # 绝对路径拒绝
        ("papers", ""),  # 空 key 拒绝
        ("..", "x"),  # app 本身逃逸拒绝
        ("papers", "a//b"),  # 空段拒绝
        ("papers", "a/"),  # 尾空段拒绝
        ("", "x"),  # 空 app 拒绝
    ],
)
def test_object_key_illegal(app, key):
    with pytest.raises(ValueError):
        build_object_key(app, key)


# ---------- parse_cos_endpoint ----------

@pytest.mark.parametrize(
    "raw",
    [
        "https://b.cos.ap-guangzhou.myqcloud.com",
        "http://b.cos.ap-guangzhou.myqcloud.com/",
        "b.cos.ap-nanjing.myqcloud.com",
        "https://b.cos-internal.ap-guangzhou.tencentcos.cn",
    ],
)
def test_parse_endpoint_ok(raw):
    bucket, region = parse_cos_endpoint(raw)
    assert bucket == "b"
    assert region.startswith("ap-")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://cos.ap-guangzhou.myqcloud.com",  # 缺 bucket 段
        "https://b.cos.myqcloud.com",  # 缺 region
        "https://example.com",  # 非 COS 域
        "not-a-url",
    ],
)
def test_parse_endpoint_bad(raw):
    with pytest.raises(StorageConfigError):
        parse_cos_endpoint(raw)


# ---------- LocalStorage 全操作 ----------

async def test_local_storage_roundtrip(tmp_path: Path):
    store = LocalStorage(root_dir=tmp_path)
    assert await store.exists("papers", "2026/a.txt") is False

    await store.put("papers", "2026/a.txt", b"hello")
    assert await store.exists("papers", "2026/a.txt") is True
    assert (tmp_path / "papers" / "2026" / "a.txt").read_bytes() == b"hello"
    assert await store.get("papers", "2026/a.txt") == b"hello"

    await store.delete("papers", "2026/a.txt")
    assert await store.exists("papers", "2026/a.txt") is False


async def test_local_storage_not_found(tmp_path: Path):
    store = LocalStorage(root_dir=tmp_path)
    with pytest.raises(StorageNotFoundError):
        await store.get("papers", "missing.txt")
    with pytest.raises(StorageNotFoundError):
        await store.delete("papers", "missing.txt")


async def test_local_storage_isolation(tmp_path: Path):
    """P11：不同 app 落盘目录互不可见。"""
    store = LocalStorage(root_dir=tmp_path)
    await store.put("papers", "same.txt", b"papers")
    await store.put("chat", "same.txt", b"chat")
    assert await store.get("papers", "same.txt") == b"papers"
    assert await store.get("chat", "same.txt") == b"chat"


# ---------- CosStorage 凭证缺失（不静默降级） ----------

async def _seed_key(db, service_key: str, api_key: str, base_url: str | None = None,
                    enabled: bool = True) -> None:
    db.add(
        ServiceKey(
            service_key=service_key,
            vendor="腾讯云 COS",
            api_key=api_key,
            base_url=base_url,
            enabled=enabled,
        )
    )
    await db.commit()


async def test_cos_from_db_missing_both_rows(client):
    with pytest.raises(StorageConfigError):
        async with SessionLocal() as db:
            await CosStorage.from_db(db)


async def test_cos_from_db_missing_one_row(client):
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKID-only-id")
        with pytest.raises(StorageConfigError):
            await CosStorage.from_db(db)


async def test_cos_from_db_disabled_row(client):
    """行存在但 enabled=False → get_key 视为缺失 → 抛错。"""
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKIDxxx", enabled=False)
        await _seed_key(db, "tencent_cos_key", "secretxxx", ENDPOINT, enabled=False)
        with pytest.raises(StorageConfigError):
            await CosStorage.from_db(db)


async def test_cos_from_db_bad_endpoint(client):
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKIDxxx")
        await _seed_key(db, "tencent_cos_key", "secretxxx", "https://example.com")
        with pytest.raises(StorageConfigError):
            await CosStorage.from_db(db)


async def test_cos_from_db_ok(client):
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKIDxxx")
        await _seed_key(db, "tencent_cos_key", "secretxxx", ENDPOINT)
        store = await CosStorage.from_db(db)
    assert isinstance(store, CosStorage)


# ---------- CosStorage 四操作（fake client，不真连 COS） ----------

class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._buf = io.BytesIO(data)

    def get_raw_stream(self) -> io.BytesIO:
        return self._buf


class FakeCosClient:
    """记录调用并模拟内存对象表；不存在键抛 404 CosServiceError。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list[tuple[str, str, str]] = []  # (method, bucket, key)

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.calls.append(("put", Bucket, Key))
        self.objects[Key] = bytes(Body)

    def get_object(self, Bucket: str, Key: str) -> dict:
        self.calls.append(("get", Bucket, Key))
        if Key not in self.objects:
            raise CosServiceError("GET", {"code": "NoSuchKey"}, 404)
        return {"Body": _FakeBody(self.objects[Key])}

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.calls.append(("delete", Bucket, Key))
        if Key not in self.objects:
            raise CosServiceError("DELETE", {"code": "NoSuchKey"}, 404)
        del self.objects[Key]

    def head_object(self, Bucket: str, Key: str) -> dict:
        self.calls.append(("head", Bucket, Key))
        if Key not in self.objects:
            raise CosServiceError("HEAD", {"code": "NoSuchKey"}, 404)
        return {}

    def list_objects(
        self, Bucket: str, Prefix: str, Marker: str = "", MaxKeys: int = 1000
    ) -> dict:
        self.calls.append(("list", Bucket, Prefix))
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        if Marker:
            keys = [k for k in keys if k > Marker]
        page = keys[:MaxKeys]
        return {
            "Contents": [{"Key": k} for k in page],
            "IsTruncated": "true" if len(keys) > MaxKeys else "false",
        }


def _make_cos(monkeypatch, fake: FakeCosClient) -> CosStorage:
    monkeypatch.setattr(storage_module, "CosS3Client", lambda config: fake)
    return CosStorage("AKIDxxx", "secretxxx", "b", "ap-guangzhou")


async def test_cos_roundtrip_fake_client(monkeypatch):
    fake = FakeCosClient()
    store = _make_cos(monkeypatch, fake)

    assert await store.exists("papers", "2026/a.pdf") is False
    await store.put("papers", "2026/a.pdf", b"%PDF-fake")
    assert await store.exists("papers", "2026/a.pdf") is True
    assert await store.get("papers", "2026/a.pdf") == b"%PDF-fake"

    # 键名恒为 {app}/{key}（P11），bucket 固定
    assert ("put", "b", "papers/2026/a.pdf") in fake.calls
    assert ("get", "b", "papers/2026/a.pdf") in fake.calls

    await store.delete("papers", "2026/a.pdf")
    assert await store.exists("papers", "2026/a.pdf") is False


async def test_cos_list_directory_prefix_and_app_isolation(monkeypatch):
    """list（轮①级联删新增）：目录型前缀（尾随 /）合法；只列本应用目录；
    返回 key 不含 app 前缀；P11 违规照旧拒绝。"""
    fake = FakeCosClient()
    store = _make_cos(monkeypatch, fake)
    await store.put("papers", "pdfs/2026/11/7.pdf", b"x")
    await store.put("papers", "pdfs/2026/10/8.pdf", b"x")
    await store.put("papers", "parsed/7/full.md", b"x")
    await store.put("chat", "pdfs/9.pdf", b"x")  # 他应用同前缀，不得串目录

    keys = await store.list("papers", "pdfs/")
    assert keys == ["pdfs/2026/10/8.pdf", "pdfs/2026/11/7.pdf"]
    assert ("list", "b", "papers/pdfs/") in fake.calls  # COS Prefix 带尾随 /

    all_keys = await store.list("papers", "")
    assert all_keys == ["parsed/7/full.md", "pdfs/2026/10/8.pdf", "pdfs/2026/11/7.pdf"]

    with pytest.raises(ValueError):  # P11：路径逃逸照旧拒绝
        await store.list("papers", "../x")


async def test_cos_not_found_semantics(monkeypatch):
    fake = FakeCosClient()
    store = _make_cos(monkeypatch, fake)
    with pytest.raises(StorageNotFoundError):
        await store.get("papers", "missing.pdf")
    with pytest.raises(StorageNotFoundError):
        await store.delete("papers", "missing.pdf")


async def test_cos_non_404_error_propagates(monkeypatch):
    fake = FakeCosClient()

    def _boom(**kwargs):
        raise CosServiceError("GET", {"code": "AccessDenied"}, 403)

    fake.get_object = _boom  # type: ignore[method-assign]
    store = _make_cos(monkeypatch, fake)
    with pytest.raises(CosServiceError):
        await store.get("papers", "x.pdf")


async def test_cos_prefix_validation_still_applies(monkeypatch):
    """P11：即使底层是 COS，非法 app/key 仍在边界被拒（未触及 client）。"""
    fake = FakeCosClient()
    store = _make_cos(monkeypatch, fake)
    with pytest.raises(ValueError):
        await store.put("PAPERS", "x", b"1")
    with pytest.raises(ValueError):
        await store.get("papers", "../x")
    assert fake.calls == []  # client 零调用


# ---------- 工厂选择策略 ----------

async def test_factory_falls_back_local_when_unconfigured(client):
    async with SessionLocal() as db:
        store = await get_storage(db)
    assert isinstance(store, LocalStorage)


async def test_factory_raises_when_half_configured(client):
    """只配置一行 = 故障：不允许静默降级到本地。"""
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKIDxxx")
        with pytest.raises(StorageConfigError):
            await get_storage(db)


async def test_factory_raises_when_half_configured_other_side(client):
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_key", "secretxxx", ENDPOINT)
        with pytest.raises(StorageConfigError):
            await get_storage(db)


async def test_factory_uses_cos_when_configured(client, monkeypatch):
    monkeypatch.setattr(storage_module, "CosS3Client", lambda config: FakeCosClient())
    async with SessionLocal() as db:
        await _seed_key(db, "tencent_cos_id", "AKIDxxx")
        await _seed_key(db, "tencent_cos_key", "secretxxx", ENDPOINT)
        store = await get_storage(db)
    assert isinstance(store, CosStorage)
