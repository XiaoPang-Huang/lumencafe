"""存储抽象层（论文域步 D，拍板 P9/P11）：按应用目录硬隔离的对象存储。

P11 硬性规定（用户定，最高优先级）：bucket/本地目录顶层按应用分文件夹
（``papers/``、``chat/``……），应用间**绝对隔离**。本模块是全后端唯一的
对象存储入口：

- 所有公开方法强制 ``(app, key)`` 双参数，最终对象键恒为 ``f"{app}/{key}"``；
- ``app`` 名白名单校验（``[a-z0-9_]+``）；``key`` 禁止以 ``/`` 开头、禁止
  ``..``、禁止空段——违规一律 ``ValueError``，在边界直接拒绝（跨应用路径
  没有任何机会落到存储介质）；
- 两个实现：``CosStorage``（腾讯云 COS，凭证从 service_keys 表读
  ``tencent_cos_id`` / ``tencent_cos_key``，endpoint 拆自 ``tencent_cos_key``
  行的网址字段）+ ``LocalStorage``（``data/storage/<app>/<key>`` 落盘，开发兜底）；
- 凭证纪律：COS 已配置后**绝不静默降级**——显式构造 ``CosStorage`` 时
  凭证缺失/行未启用抛 ``StorageConfigError``；工厂 ``get_storage(db)`` 的选择
  策略见函数 docstring（只在 COS 完全未配置时回落 Local；配置了一半即报错）。

用法::

    storage = await get_storage(db)
    await storage.put("papers", "2026/abc.pdf", pdf_bytes)
    data = await storage.get("papers", "2026/abc.pdf")
"""
import re
from abc import ABC, abstractmethod
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosServiceError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.service_keys import get_key

# ---- P11 前缀硬约束常量 ----
_APP_PATTERN = re.compile(r"[a-z0-9_]+")  # app 名白名单（全匹配使用）
_ENDPOINT_PATTERN = re.compile(
    r"^(?P<bucket>[a-z0-9][a-z0-9-]{0,60})"
    r"\.cos(?:-internal)?\.(?P<region>[a-z0-9-]+)"
    r"\.(?:myqcloud\.com|tencentcos\.cn)$"
)

# service_keys 表里的 COS 凭证行（拍板 P9：SecretId/SecretKey 两行，
# SecretKey 行的网址字段存 bucket endpoint）
COS_SECRET_ID_KEY = "tencent_cos_id"
COS_SECRET_KEY_KEY = "tencent_cos_key"

DEFAULT_LOCAL_ROOT = Path("data/storage")


class StorageConfigError(RuntimeError):
    """COS 存储配置错误（凭证缺失/未启用/endpoint 无法解析）。

    显式故障，绝不静默降级——调用方应修复 service_keys 配置，
    而不是假装存储成功。
    """


class StorageNotFoundError(FileNotFoundError):
    """对象不存在（get/delete 语义统一，两个实现一致抛出）。"""


def _validate_app(app: str) -> None:
    """P11 白名单校验：app 名必须全匹配 [a-z0-9_]+。"""
    if not isinstance(app, str) or not app or _APP_PATTERN.fullmatch(app) is None:
        raise ValueError(f"app 名非法: {app!r}（P11 硬隔离：仅允许小写字母/数字/下划线）")


def _validate_key(key: str) -> None:
    """P11 路径校验：key 不得空、不得以 / 开头、不得含 .. 或空段。"""
    if not isinstance(key, str) or not key:
        raise ValueError("key 不能为空")
    if key.startswith("/"):
        raise ValueError(f"key 不允许以 / 开头（会逃逸应用目录前缀）: {key!r}")
    if ".." in key:
        raise ValueError(f"key 不允许包含 ..（路径逃逸风险）: {key!r}")
    if any(segment == "" for segment in key.split("/")):
        raise ValueError(f"key 不允许含空路径段: {key!r}")


def build_object_key(app: str, key: str) -> str:
    """校验并拼出最终对象键 f"{app}/{key}"（P11：唯一合法形态）。"""
    _validate_app(app)
    _validate_key(key)
    return f"{app}/{key}"


def parse_cos_endpoint(base_url: str) -> tuple[str, str]:
    """从 service_keys 的网址字段拆出 (bucket, region)。

    支持形态（去 scheme/尾斜线/端口后匹配）：
      https://<bucket>.cos.<region>.myqcloud.com      （公网/内网同域，内网走解析器）
      https://<bucket>.cos-internal.<region>.tencentcos.cn

    解析失败抛 StorageConfigError（配置错误要响亮，不静默）。
    """
    host = (base_url or "").strip().lower()
    host = re.sub(r"^https?://", "", host)
    host = host.split("/")[0].split(":")[0].rstrip(".")
    match = _ENDPOINT_PATTERN.fullmatch(host)
    if match is None:
        raise StorageConfigError(
            f"无法从 COS endpoint 解析 bucket/region: {base_url!r}"
            "（期望形如 https://<bucket>.cos.<region>.myqcloud.com）"
        )
    return match.group("bucket"), match.group("region")


class Storage(ABC):
    """存储抽象基类：四操作契约（字节进字节出）。"""

    @abstractmethod
    async def put(self, app: str, key: str, data: bytes) -> None:
        """上传对象；app/key 违规抛 ValueError（P11）。"""

    @abstractmethod
    async def get(self, app: str, key: str) -> bytes:
        """下载对象；不存在抛 StorageNotFoundError。"""

    @abstractmethod
    async def delete(self, app: str, key: str) -> None:
        """删除对象；不存在抛 StorageNotFoundError（幂等调用方先 exists）。"""

    @abstractmethod
    async def exists(self, app: str, key: str) -> bool:
        """对象是否存在；app/key 违规抛 ValueError（P11）。"""


class LocalStorage(Storage):
    """本地磁盘兜底实现：root/<app>/<key> 落盘（开发环境用）。

    生产容器不应依赖本实现（无卷持久化），它只是 COS 未配置时的显式兜底，
    让开发链路（如后续 MinerU 解析产物落盘）可以先跑通。
    """

    def __init__(self, root_dir: Path | str = DEFAULT_LOCAL_ROOT) -> None:
        self._root = Path(root_dir)

    def _path(self, app: str, key: str) -> Path:
        """校验后的落盘路径（校验即 P11 闸门，拼接天然受限于应用目录内）。"""
        return self._root / build_object_key(app, key)

    async def put(self, app: str, key: str, data: bytes) -> None:
        path = self._path(app, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))

    async def get(self, app: str, key: str) -> bytes:
        path = self._path(app, key)
        if not path.is_file():
            raise StorageNotFoundError(f"对象不存在: {build_object_key(app, key)}")
        return path.read_bytes()

    async def delete(self, app: str, key: str) -> None:
        path = self._path(app, key)
        if not path.is_file():
            raise StorageNotFoundError(f"对象不存在: {build_object_key(app, key)}")
        path.unlink()

    async def exists(self, app: str, key: str) -> bool:
        return self._path(app, key).is_file()


class CosStorage(Storage):
    """腾讯云 COS 实现（cos-python-sdk-v5，同步 SDK 薄封装）。

    构造即校验：四个参数缺一不可。凭证请走 :meth:`from_db` 从
    service_keys 表读取——凭证缺失/行未启用抛 StorageConfigError，
    **绝不静默降级**（一旦选定 COS，运行期凭证消失是故障，不叫兜底）。
    """

    def __init__(self, secret_id: str, secret_key: str, bucket: str, region: str) -> None:
        if not secret_id or not secret_key:
            raise StorageConfigError("COS SecretId/SecretKey 不能为空")
        if not bucket or not region:
            raise StorageConfigError("COS bucket/region 不能为空")
        self._bucket = bucket
        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Scheme="https")
        self._client = CosS3Client(config)

    @classmethod
    async def from_db(cls, db: AsyncSession) -> "CosStorage":
        """从 service_keys 读凭证构造；任一缺失/未启用/endpoint 不可解析即抛错。"""
        id_row = await get_key(db, COS_SECRET_ID_KEY)
        key_row = await get_key(db, COS_SECRET_KEY_KEY)
        missing = []
        if id_row is None or not id_row.api_key:
            missing.append(COS_SECRET_ID_KEY)
        if key_row is None or not key_row.api_key:
            missing.append(COS_SECRET_KEY_KEY)
        if missing:
            raise StorageConfigError(
                "COS 凭证未配置或未启用（service_keys 表）: "
                + ", ".join(missing)
                + "；请先在管理页填写并启用后重试"
            )
        bucket, region = parse_cos_endpoint(key_row.base_url or "")
        return cls(
            secret_id=id_row.api_key,
            secret_key=key_row.api_key,
            bucket=bucket,
            region=region,
        )

    async def put(self, app: str, key: str, data: bytes) -> None:
        object_key = build_object_key(app, key)
        self._client.put_object(Bucket=self._bucket, Key=object_key, Body=bytes(data))

    async def get(self, app: str, key: str) -> bytes:
        object_key = build_object_key(app, key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except CosServiceError as exc:
            if exc.get_status_code() == 404:
                raise StorageNotFoundError(f"对象不存在: {object_key}") from exc
            raise
        return response["Body"].get_raw_stream().read()

    async def delete(self, app: str, key: str) -> None:
        object_key = build_object_key(app, key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except CosServiceError as exc:
            if exc.get_status_code() == 404:
                raise StorageNotFoundError(f"对象不存在: {object_key}") from exc
            raise

    async def exists(self, app: str, key: str) -> bool:
        object_key = build_object_key(app, key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except CosServiceError as exc:
            if exc.get_status_code() == 404:
                return False
            raise


async def get_storage(db: AsyncSession) -> Storage:
    """存储工厂：COS 可用则 COS，否则 Local（选择策略，显式非静默）。

    - 两行凭证（``tencent_cos_id`` / ``tencent_cos_key``）都未配置/未启用
      → 视为 COS 从未接入，回落 ``LocalStorage``（开发兜底）；
    - 只配置了一行（或行在但 api_key 为空）→ 抛 ``StorageConfigError``
      （配置了一半是故障，不允许悄悄退回本地造成数据分叉）；
    - 两行齐备但 endpoint 无法解析 bucket/region → 抛 ``StorageConfigError``；
    - 两行齐备且可解析 → ``CosStorage``。
    """
    id_row = await get_key(db, COS_SECRET_ID_KEY)
    key_row = await get_key(db, COS_SECRET_KEY_KEY)
    id_ready = id_row is not None and bool(id_row.api_key)
    key_ready = key_row is not None and bool(key_row.api_key)

    if not id_ready and not key_ready:
        return LocalStorage()
    if not id_ready or not key_ready:
        missing = COS_SECRET_ID_KEY if not id_ready else COS_SECRET_KEY_KEY
        raise StorageConfigError(
            f"COS 凭证不完整：{missing} 未配置/未启用（service_keys 表），"
            "不允许静默降级到本地存储；补齐或停用另一行后重试"
        )
    # 两行齐备：endpoint 解析失败会响亮抛错（非静默）
    return await CosStorage.from_db(db)


__all__ = [
    "COS_SECRET_ID_KEY",
    "COS_SECRET_KEY_KEY",
    "CosStorage",
    "LocalStorage",
    "Storage",
    "StorageConfigError",
    "StorageNotFoundError",
    "build_object_key",
    "get_storage",
    "parse_cos_endpoint",
]
