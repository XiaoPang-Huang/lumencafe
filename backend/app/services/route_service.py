"""网关默认路由解析（架构设计 §3.2 / Q10 / Q13）。

默认路由 = providers.is_default 选定默认 Provider + 其下 llm_models.is_default
选定默认模型，两标记联动，PUT /admin/models/default-route 负责切换。
解析严格只认标记（Q13：未配置或 provider 停用 → 视为无默认路由）。
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LLMModel, Provider
from app.services.llm_gateway import ClientCfg


@dataclass(frozen=True)
class ResolvedRoute:
    provider_id: int
    provider_name: str
    vendor: str
    model_id: int
    model_name: str
    cfg: ClientCfg
    meta: dict[str, Any] | None = None  # 增量 v1：模型 meta（thinking 白名单校验用）


async def resolve_default(db: AsyncSession) -> ResolvedRoute | None:
    """解析网关默认路由；未配置/停用返回 None（调用方转 503）。"""
    provider = (
        await db.execute(select(Provider).where(Provider.is_default.is_(True)))
    ).scalar_one_or_none()
    if provider is None or not provider.enabled:
        return None
    model = (
        await db.execute(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if model is None or not model.enabled:
        return None
    return ResolvedRoute(
        provider_id=provider.id,
        provider_name=provider.name,
        vendor=provider.vendor,
        model_id=model.id,
        model_name=model.name,
        cfg=ClientCfg(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=model.name,
            vendor=provider.vendor,
        ),
        meta=dict(model.meta) if model.meta else None,
    )
