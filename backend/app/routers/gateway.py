"""模型网关对外端点（架构设计 §4.9/§5.6/Q13/Q17）。

- OpenAI 兼容：POST /gw/v1/chat/completions，Bearer 网关令牌鉴权（查 gateway_tokens 表）；
- 零 Key 原则：真实 provider Key 由网关查库注入转发，任何响应不回显 Key；
- 纯转发：不落库、不计费、不审计对话内容；不走用户 JWT/RBAC；
- model 反查 llm_models.name（同名多 provider 取 enabled 且 id 最小者）；
  别名 default（不区分大小写）→ 网关默认路由；stream=true 返回 OpenAI 兼容 SSE。
"""
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.llm import GatewayToken, LLMModel, Provider
from app.services import llm_gateway, route_service

router = APIRouter(prefix="/gw/v1", tags=["gateway"])
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    # extra="allow"：网关是透传层，消息上的 tool_calls/tool_call_id/name 等
    # 扩展字段必须原样保留（pi-runner 步 1 排障：pydantic 默认丢弃 extra 字段，
    # 导致 follow-up 请求缺 tool_call_id，上游 422）
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = ""


class ChatCompletionsRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    # pi-runner 步 1 增补：工具透传（OpenAI 兼容协议；此前缺失导致客户端工具调用
    # 被静默丢弃，模型退化为纯文本输出伪工具标记）
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    # 其余调用参数原样透传（此前被 pydantic 静默丢弃；实测丢参数会改变上游
    # 响应行为并触发客户端跟进请求异常，pi-runner 步 1 排障增补）
    max_completion_tokens: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    store: bool | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _authenticate_gateway(db: AsyncSession, authorization: str | None) -> GatewayToken:
    """查 gateway_tokens 表（Q17）：哈希比对 + active 检查；全表无活跃令牌 → 503。"""
    active_count = (
        await db.execute(select(GatewayToken.id).where(GatewayToken.active.is_(True)).limit(1))
    ).first()
    if active_count is None:
        raise HTTPException(status_code=503, detail="模型网关未启用")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="网关令牌无效")
    token_hash = _token_hash(authorization.removeprefix("Bearer ").strip())
    row = (
        await db.execute(
            select(GatewayToken).where(
                GatewayToken.token_hash == token_hash, GatewayToken.active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="网关令牌无效")
    return row


async def _resolve_model(
    db: AsyncSession, model_name: str
) -> tuple[LLMModel, Provider]:
    """模型解析（Q13）：default 别名走默认路由；否则反查 llm_models.name。"""
    if model_name.lower() == "default":
        route = await route_service.resolve_default(db)
        if route is None:
            raise HTTPException(status_code=503, detail="默认模型未配置")
        model = (
            await db.execute(select(LLMModel).where(LLMModel.id == route.model_id))
        ).scalar_one()
        provider = (
            await db.execute(select(Provider).where(Provider.id == route.provider_id))
        ).scalar_one()
        return model, provider

    # 同名多 provider：取 enabled=true 中 providers.id 最小者
    rows = (
        await db.execute(
            select(LLMModel, Provider)
            .join(Provider, Provider.id == LLMModel.provider_id)
            .where(LLMModel.name == model_name)
            .order_by(Provider.id)
        )
    ).all()
    for model, provider in rows:
        if provider.enabled:
            return model, provider
    raise HTTPException(status_code=404, detail="模型不存在或未启用")


def _check_scope(token: GatewayToken, model_name: str) -> None:
    """model_scope 白名单校验（NULL = 全部模型）。"""
    if token.model_scope and model_name not in token.model_scope:
        raise HTTPException(status_code=403, detail="该模型不在令牌可用范围内")


def _chunk(
    model: str,
    delta: str,
    *,
    finish_reason: str | None = None,
    tool_calls: list[Any] | None = None,
) -> str:
    if tool_calls is not None:
        delta_payload: dict[str, Any] = {"tool_calls": tool_calls}
    elif delta:
        delta_payload = {"content": delta}
    else:
        delta_payload = {}
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta_payload,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_reply(
    cfg: llm_gateway.ClientCfg,
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    extra: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    finish_sent = False
    try:
        # 原样透传上游帧（chat_stream_passthrough）：不重序列化，避免协议漂移
        # （pi-runner 步 1 实测：重组 tool_calls 流会导致 Pi 丢失工具状态）
        async for frame in llm_gateway.chat_stream_passthrough(
            cfg, messages, tools=tools, tool_choice=tool_choice, extra=extra
        ):
            yield frame["raw"]
            if frame["finish"]:
                finish_sent = True
        if not finish_sent:
            # 兜底补 finish_reason：个别上游不发 finish 帧时，保证流以
            # 带 finish_reason 的 chunk 收尾（OpenAI 协议要求；Pi 客户端依赖）
            yield _chunk(model_name, "", finish_reason="stop")
    except llm_gateway.UpstreamError as exc:
        # 落日志留排障线索（上游错误体已由 chat_stream 拼进异常消息）
        logger.warning("网关流式调用上游失败：%s", exc)
        yield f"data: {json.dumps({'error': '上游模型调用失败'}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(
    request: ChatCompletionsRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    token = await _authenticate_gateway(db, http_request.headers.get("Authorization"))
    model, provider = await _resolve_model(db, request.model)
    _check_scope(token, model.name)
    cfg = llm_gateway.ClientCfg(
        base_url=provider.base_url, api_key=provider.api_key, model=model.name
    )
    messages = [m.model_dump() for m in request.messages]

    # 其余调用参数原样透传上游（None 值不入 payload）
    extra = {
        k: v
        for k, v in {
            "max_completion_tokens": request.max_completion_tokens,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "store": request.store,
            "parallel_tool_calls": request.parallel_tool_calls,
            "response_format": request.response_format,
        }.items()
        if v is not None
    }

    if request.stream:
        return StreamingResponse(
            _stream_reply(
                cfg, model.name, messages, request.tools, request.tool_choice, extra
            ),
            media_type="text/event-stream",
        )

    message_out: dict[str, Any] = {}
    try:
        content = await llm_gateway.chat_once(
            cfg,
            messages,
            tools=request.tools,
            tool_choice=request.tool_choice,
            message_out=message_out,
        )
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail="上游模型调用失败") from exc
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model.name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, **message_out},
                "finish_reason": "stop",
            }
        ],
    }
