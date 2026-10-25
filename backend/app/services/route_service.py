"""网关路由解析（架构设计 §3.2 / Q10 / Q13；增量 v2 B1/D2：按消费者路由）。

默认路由 = providers.is_default 选定默认 Provider + 其下 llm_models.is_default
选定默认模型，两标记联动，PUT /admin/models/default-route 负责切换。
解析严格只认标记（Q13：未配置或 provider 停用 → 视为无默认路由）。

步 3（D12）：resolve_for(app_key) 演进为按消费者路由——查 model_assignments
解析主模型 + 有序备用链；未配置指派的 app_key 回落默认路由（兼容期不报错）。
候选过滤：模型/渠道停用、熔断 open 未到探测点的模型一律跳过。
"""
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LLMModel, ModelAssignment, Provider
from app.services import circuit_service
from app.services.llm_gateway import ClientCfg

# 指派来源（RoutePlan.source）
SOURCE_ASSIGNMENT = "assignment"  # model_assignments 解析（主模型 + 备用链）
SOURCE_DEFAULT = "default"  # 未配置指派/指派失效，回落默认路由（兼容期）
SOURCE_DIRECT = "direct"  # 会话级显式 model_id（Q15），单候选不走熔断


@dataclass(frozen=True)
class ResolvedRoute:
    provider_id: int
    provider_name: str
    vendor: str
    model_id: int
    model_name: str
    cfg: ClientCfg
    meta: dict[str, Any] | None = None  # 增量 v1：模型 meta（thinking 白名单/单价用）


@dataclass(frozen=True)
class RoutePlan:
    """一次调用的有序路由计划：candidates[0] = 主模型，其后按序兜底。"""

    candidates: tuple[ResolvedRoute, ...]
    source: str = SOURCE_ASSIGNMENT
    is_fallback: bool = field(default=False)  # 备用链非空 = 存在兜底路径


def _dedup(ids: list[int]) -> list[int]:
    """保序去重（主模型若在备用链中重复出现只留首位）。"""
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def _load_candidates(db: AsyncSession, model_ids: list[int]) -> list[ResolvedRoute]:
    """按序把模型 id 解析为可用候选；停用（模型/渠道）与熔断摘出的一律跳过。"""
    routes: list[ResolvedRoute] = []
    for mid in _dedup(model_ids):
        row = (
            await db.execute(
                select(LLMModel, Provider)
                .join(Provider, Provider.id == LLMModel.provider_id)
                .where(LLMModel.id == mid)
            )
        ).first()
        if row is None:
            continue
        model, provider = row
        if not model.enabled or not provider.enabled:
            continue
        if not await circuit_service.is_available(db, model.id):
            continue  # 熔断摘出中且未到探测点
        routes.append(
            ResolvedRoute(
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
        )
    return routes


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


async def resolve_for(db: AsyncSession, app_key: str) -> RoutePlan | None:
    """按消费者解析路由（B1/D12）：主模型 + 有序备用链。

    - 无指派或指派停用 → 回落默认路由（兼容期不报错，source=default）；
    - 指派存在但候选全不可用 → 同样回落默认路由兜底；
    - 默认路由也未配置 → None（调用方转 503）。
    """
    assignment = (
        await db.execute(
            select(ModelAssignment).where(
                ModelAssignment.app_key == app_key, ModelAssignment.enabled.is_(True)
            )
        )
    ).scalar_one_or_none()
    if assignment is not None:
        chain = [assignment.primary_model_id, *(assignment.fallback_chain or [])]
        candidates = await _load_candidates(db, chain)
        if candidates:
            return RoutePlan(
                candidates=tuple(candidates),
                source=SOURCE_ASSIGNMENT,
                is_fallback=len(candidates) > 1,
            )
    default = await resolve_default(db)
    if default is None:
        return None
    return RoutePlan(candidates=(default,), source=SOURCE_DEFAULT)


async def direct_plan(db: AsyncSession, model_id: int) -> RoutePlan | None:
    """会话级显式 model_id（Q15）：单候选直查，不走指派/熔断（调用方已做启用校验）。"""
    row = (
        await db.execute(
            select(LLMModel, Provider)
            .join(Provider, Provider.id == LLMModel.provider_id)
            .where(LLMModel.id == model_id)
        )
    ).first()
    if row is None:
        return None
    model, provider = row
    return RoutePlan(
        candidates=(
            ResolvedRoute(
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
            ),
        ),
        source=SOURCE_DIRECT,
    )
