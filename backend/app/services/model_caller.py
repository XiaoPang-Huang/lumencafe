"""路由化调用编排（架构设计-增量 v2 B1/D2/D3，步 3 调用面收口）。

在 llm_gateway（纯调用引擎）之上串起四件事：
1. route_service 解析有序候选（主模型 → 备用链）；
2. 首 token 前失败按序兜底（流式开始输出后不换模型——所有同类产品同限制）；
3. circuit_service 记录成败（连挂摘出/探测恢复自动切回）；
4. meter_service 每次调用尝试写 llm_call_logs（含失败尝试；费用=单价快照×token）。

调用方（chat_service / money_service）只传 app_key，不再各自查路由。
"""
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import circuit_service, llm_gateway, meter_service, route_service
from app.services.llm_gateway import StreamChunk


class RouteUnavailable(Exception):
    """无任何可用路由（指派/默认路由均未配置或全部不可用）→ 调用方转 503。"""


class AllRoutesFailed(llm_gateway.UpstreamError):
    """主模型与备用链全部调用失败 → 调用方转 502。"""


async def _log(
    db: AsyncSession,
    *,
    app_key: str,
    route: route_service.ResolvedRoute,
    usage: meter_service.Usage,
    latency_ms: int,
    success: bool,
    error: str | None = None,
) -> None:
    await meter_service.write_call_log(
        db,
        app_key=app_key,
        model_id=route.model_id,
        model_name=route.model_name,
        model_meta=route.meta,
        usage=usage,
        latency_ms=latency_ms,
        success=success,
        error=error,
    )


async def chat_once(
    db: AsyncSession,
    app_key: str,
    messages: list[dict[str, str]],
    timeout: float = 30.0,
) -> str:
    """非流式调用（自带解析）：按序兜底，返回首个成功候选的完整文本。"""
    plan = await route_service.resolve_for(db, app_key)
    if plan is None:
        raise RouteUnavailable
    return await chat_once_plan(db, app_key, plan, messages, timeout)


async def chat_once_plan(
    db: AsyncSession,
    app_key: str,
    plan: route_service.RoutePlan,
    messages: list[dict[str, str]],
    timeout: float = 30.0,
) -> str:
    """非流式调用（plan 由调用方预解析，如 mock 短路等场景）：按序兜底。"""
    errors: list[str] = []
    for cand in plan.candidates:
        usage_out: dict[str, Any] = {}
        start = time.perf_counter()
        try:
            text = await llm_gateway.chat_once(cand.cfg, messages, timeout, usage_out)
        except llm_gateway.UpstreamError as exc:
            await circuit_service.on_failure(db, cand.model_id)
            await _log(
                db,
                app_key=app_key,
                route=cand,
                usage=meter_service.Usage(),
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error=str(exc),
            )
            errors.append(f"{cand.model_name}: {exc}")
            continue
        await circuit_service.on_success(db, cand.model_id)
        await _log(
            db,
            app_key=app_key,
            route=cand,
            usage=meter_service.Usage.from_mapping(usage_out),
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=True,
        )
        return text
    raise AllRoutesFailed("；".join(errors)[:300] or "全部模型调用失败")


async def chat_stream(
    db: AsyncSession,
    app_key: str,
    plan: route_service.RoutePlan,
    messages: list[dict[str, str]],
    thinking: str | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[StreamChunk]:
    """流式调用：首帧前失败按序换模型；首帧产出后该模型不可换（B1 兜底边界）。

    plan 由调用方在请求级 prepare 阶段解析（需要 request-scoped db）；
    本生成器内只做候选迭代与记账（db 为调用方提供的可写会话）。
    """
    errors: list[str] = []
    for cand in plan.candidates:
        usage_out: dict[str, Any] = {}
        start = time.perf_counter()
        iterator = llm_gateway.chat_stream(cand.cfg, messages, thinking, timeout, usage_out)
        try:
            first = await iterator.__anext__()
        except StopAsyncIteration:
            # 空流也算成功（无内容但无错误）
            await circuit_service.on_success(db, cand.model_id)
            await _log(
                db,
                app_key=app_key,
                route=cand,
                usage=meter_service.Usage.from_mapping(usage_out),
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=True,
            )
            return
        except llm_gateway.UpstreamError as exc:
            # 首 token 前失败：熔断计数 + 记失败日志，按序换下一个候选
            await circuit_service.on_failure(db, cand.model_id)
            await _log(
                db,
                app_key=app_key,
                route=cand,
                usage=meter_service.Usage(),
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error=str(exc),
            )
            errors.append(f"{cand.model_name}: {exc}")
            continue
        # 首帧已产出：本模型锁定，产出剩余帧；正常结束 → 成功 + 记账
        await circuit_service.on_success(db, cand.model_id)
        try:
            yield first
            async for chunk in iterator:
                yield chunk
        except llm_gateway.UpstreamError:
            # 流中途失败：不换模型（B1），记失败账后上抛（路由层转 SSE 错误事件）
            await circuit_service.on_failure(db, cand.model_id)
            await _log(
                db,
                app_key=app_key,
                route=cand,
                usage=meter_service.Usage(),
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=False,
                error="stream interrupted",
            )
            raise
        await _log(
            db,
            app_key=app_key,
            route=cand,
            usage=meter_service.Usage.from_mapping(usage_out),
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=True,
        )
        return
    raise AllRoutesFailed("；".join(errors)[:300] or "全部模型调用失败")
