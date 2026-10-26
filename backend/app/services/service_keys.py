"""服务 Key 消费侧（架构设计-增量 v2.9）：后端异构服务按服务名取钥匙直连厂商。

用法（本期先落函数不接线，供后续 MinerU 解析 / FunASR 语音等服务消费）：

    row = await get_key(db, "mineru")
    if row is not None:
        headers = {"Authorization": f"Bearer {row.api_key}"}
        base_url = row.base_url
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_key import ServiceKey


async def get_key(db: AsyncSession, service_key: str) -> ServiceKey | None:
    """按服务名取启用行的钥匙（api_key / base_url）；停用或不存在返回 None。"""
    return (
        await db.execute(
            select(ServiceKey).where(
                ServiceKey.service_key == service_key, ServiceKey.enabled.is_(True)
            )
        )
    ).scalar_one_or_none()
