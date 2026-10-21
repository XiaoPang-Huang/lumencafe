"""模型网关对外端点（架构设计 §4.9/§5.6/Q13/Q17）。

- OpenAI 兼容：POST /gw/v1/chat/completions，Bearer 网关令牌鉴权（查 gateway_tokens 表）；
- 零 Key 原则：真实 provider Key 由网关查库注入转发，任何响应不回显 Key；
- 纯转发：不落库、不计费、不审计对话内容；不走用户 JWT/RBAC；
- model 反查 llm_models.name（同名多 provider 取 enabled 且 id 最小者）；
  别名 default（不区分大小写）→ 网关默认路由；stream=true 返回 OpenAI 兼容 SSE。
"""
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.llm import GatewayToken, LLMModel, Provider
from app.services import llm_gateway, route_service

router = APIRouter(prefix="/gw/v1", tags=["gateway"])


class ChatMessage(BaseModel):
    role: str
    content: Any = ""


class ChatCompletionsRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False


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


def _chunk(model: str, delta: str, *, finish: bool = False) -> str:
    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {} if finish else {"content": delta},
                "finish_reason": "stop" if finish else None,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_reply(
    cfg: llm_gateway.ClientCfg, model_name: str, messages: list[dict[str, Any]]
) -> AsyncIterator[str]:
    try:
        async for chunk in llm_gateway.chat_stream(cfg, messages):
            # 对外 /gw/v1 协议不变（N-增1）：reasoning 双流帧不透出，仅转发正文
            if chunk.delta:
                yield _chunk(model_name, chunk.delta)
    except llm_gateway.UpstreamError:
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

    if request.stream:
        return StreamingResponse(
            _stream_reply(cfg, model.name, messages),
            media_type="text/event-stream",
        )

    try:
        content = await llm_gateway.chat_once(cfg, messages)
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
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
