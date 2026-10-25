"""调用记账（架构设计-增量 v2 B1/D3，费用模型抄 Langfuse）。

- chat_once / chat_stream 每次调用尝试（含失败的兜底尝试）写一条 llm_call_logs；
- 费用 = 调用时单价快照 × token：单价挂 llm_models.meta.pricing
  {"input_per_million": x, "output_per_million": y}（元/百万 token，可空），
  写日志时固化为 input_price/output_price/cost 三列，事后改价不动历史账；
- mock 模式 usage 记 0、cost 记 0（B1：mock 记 0 或跳过，取记 0 便于对账）。
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import LLMCallLog

ERROR_MAX_CHARS = 512


@dataclass(frozen=True)
class Usage:
    """一次调用的 token 计量（流式 usage 从末帧取，mock 为 0）。"""

    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "Usage":
        raw = data or {}
        return cls(
            input_tokens=int(raw.get("input_tokens") or 0),
            output_tokens=int(raw.get("output_tokens") or 0),
        )


def pricing_of(meta: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """从模型 meta.pricing 取单价（元/百万 token）；缺键/非法 → (None, None)。"""
    raw = (meta or {}).get("pricing")
    if not isinstance(raw, dict):
        return None, None
    try:
        in_p = raw.get("input_per_million")
        out_p = raw.get("output_per_million")
        return (
            float(in_p) if in_p is not None else None,
            float(out_p) if out_p is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def compute_cost(
    usage: Usage, input_price: float | None, output_price: float | None
) -> float | None:
    """费用（元）= 进/出 token × 对应单价 / 1e6；单价缺失时费用记 NULL。"""
    if input_price is None or output_price is None:
        return None
    return round(
        (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000,
        6,
    )


async def write_call_log(
    db: AsyncSession,
    *,
    app_key: str,
    model_id: int | None,
    model_name: str,
    model_meta: dict[str, Any] | None,
    usage: Usage,
    latency_ms: int,
    success: bool,
    error: str | None = None,
) -> LLMCallLog:
    """写一条调用日志并提交（独立事务：记账不掺进业务事务，失败不影响主流程）。"""
    input_price, output_price = pricing_of(model_meta)
    cost = compute_cost(usage, input_price, output_price) if success else None
    row = LLMCallLog(
        app_key=app_key,
        model_id=model_id,
        model_name=model_name,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=max(0, int(latency_ms)),
        success=success,
        error=(error or None)[:ERROR_MAX_CHARS] if error else None,
        input_price=input_price,
        output_price=output_price,
        cost=cost,
    )
    db.add(row)
    await db.commit()
    return row
