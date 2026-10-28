"""文献源 API Key 取匙（论文域 key 认证升级）。

- service_keys 表按服务名（service_key）托管钥匙（架构设计-增量 v2.9）；
- provider 本身不持有 DB 会话（契约冻结：search 只认关键词与日期），由抓取管线
  （papers_crawl）在轮次内按 provider.key_service 调本模块取匙，以 api_key 参数注入；
- 取不到行 / 行被禁用 / key 为空 → 返回 None → provider 保持匿名态（匿名池+重试），
  与升级前行为完全一致（向后兼容，不配 key 的用户无感知）。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_key import ServiceKey

logger = logging.getLogger("lumencafe.papers")


async def fetch_service_api_key(db: AsyncSession, service_key: str) -> str | None:
    """按服务名取启用中的完整 api_key；无行/禁用/空 key 返回 None（调用方走匿名态）。"""
    row = (
        await db.execute(
            select(ServiceKey).where(
                ServiceKey.service_key == service_key, ServiceKey.enabled.is_(True)
            )
        )
    ).scalar_one_or_none()
    if row is None or not (row.api_key or "").strip():
        logger.info("服务 %s 未配置可用 key，该源按匿名态抓取", service_key)
        return None
    return row.api_key.strip()
