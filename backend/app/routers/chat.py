"""通用对话接口（PRD §4.6，架构设计 §4.6/§5.2/Q14/Q15）。

- POST /chat：SSE 事件流（reasoning_delta → delta → [DONE]；中途失败 {error} → [DONE]，
  半截回复不落库）；校验（应用/权限/会话/模型/thinking_level 白名单）全部在返回
  StreamingResponse 之前完成；增量 v1：思维双流透传（R3）+ 档位快照（P0-2 ⑤）；
- POST /chat/polish：AI 润色（P1-2，非流式复用 chat_once，≤8s，失败 502，限流 N14）；
- 权限按注册表 perm_code 判定（require_permission 语义，查库取 code）；
- SSE 期间落库用独立 SessionLocal（§9.1）。
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.models.chat import ChatConversation
from app.models.user import User
from app.schemas.chat import (
    ChatModelOut,
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    ConversationSummary,
    HistoryResponse,
    PolishIn,
    PolishOut,
)
from app.services import chat_service, llm_gateway, rate_limit, rbac_service

router = APIRouter(prefix="/chat", tags=["chat"])

# 润色限流（N14）：每用户每分钟 10 次（与 /money/parse 同模式）
_POLISH_LIMIT = 10


async def _check_app_permission(db: AsyncSession, user: User, app_id: str) -> None:
    """按注册表 perm_code 鉴权（对话/文献等应用各自独立权限点）。"""
    app = await chat_service.get_app(db, app_id)
    perms = await rbac_service.permission_codes(db, user.id)
    if app.perm_code not in perms:
        raise HTTPException(status_code=403, detail="权限不足")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _chat_stream(
    user: User, body: ChatRequest, target: chat_service.ChatTarget, messages: list[dict[str, str]]
) -> AsyncIterator[str]:
    """SSE 生成器：双流转发 → 成功后落库（校验与预处理已在路由层完成）。"""
    collected: list[str] = []
    collected_reasoning: list[str] = []
    thinking = chat_service.resolve_effective_thinking(target)
    try:
        async for chunk in llm_gateway.chat_stream(target.cfg, messages, thinking=thinking):
            if chunk.reasoning_delta:
                collected_reasoning.append(chunk.reasoning_delta)
                yield _sse({"reasoning_delta": chunk.reasoning_delta})
            elif chunk.delta:
                collected.append(chunk.delta)
                yield _sse({"delta": chunk.delta})
    except llm_gateway.UpstreamError:
        # 流中途失败：已产生文字（含思维）不落库（PRD §4.6）
        yield _sse({"error": "刚刚卡了一下，没听清，要不再说一次？"})
        yield "data: [DONE]\n\n"
        return

    # 流正常结束：完整助手消息（含思维链，64KB 截断在 service 层）落库后发送 [DONE]
    async with SessionLocal() as db:
        await chat_service.persist_exchange(
            db,
            user_id=user.id,
            app_id=body.app_id,
            conversation_id=target.conversation.id,
            user_message=body.message,
            assistant_message="".join(collected),
            reasoning="".join(collected_reasoning) or None,
            set_title=target.is_new_conversation,
        )
    yield "data: [DONE]\n\n"


@router.post("")
async def chat(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _check_app_permission(db, user, body.app_id)
    # 校验/会话/模型/档位白名单全部在返回 SSE 之前完成：此处抛错可正常返回 4xx/503
    target = await chat_service.prepare_chat(
        db, user.id, body.app_id, body.conversation_id, body.model_id, body.thinking_level
    )
    messages = await chat_service.build_messages(
        db, user.id, body.app_id, target.conversation.id, body.message
    )
    return StreamingResponse(
        _chat_stream(user, body, target, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 润色（P1-2：composer 魔棒按钮）────────────────────────
@router.post("/polish", response_model=PolishOut)
async def polish(
    body: PolishIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI 润色输入文本：内置润色 prompt（N-增2），走默认路由，≤8s，失败 502。"""
    await _check_app_permission(db, user, "chat")
    if not rate_limit.hit(f"chat-polish:{user.id}", limit=_POLISH_LIMIT):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    polished = await chat_service.polish_text(db, body.text)
    return PolishOut(polished=polished)


# ── 模型池（Q16 驱动选择器）──────────────────────────────
@router.get("/models", response_model=list[ChatModelOut])
async def list_models(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await chat_service.list_chat_models(db)


# ── 会话管理 ────────────────────────────────────────────
def _conversation_out(c: ChatConversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        app_id=c.app_id,
        title=c.title,
        model_id=c.model_id,
        thinking_level=c.thinking_level,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    app_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _check_app_permission(db, user, app_id)
    rows = await chat_service.list_conversations(db, user.id, app_id)
    return [_conversation_out(c) for c in rows]


@router.get("/conversations/summary", response_model=ConversationSummary)
async def conversation_summary(
    app_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """每日看板聚合（PRD v1.1-rev7）：昨日有更新的会话数 + 最近一条会话。"""
    await _check_app_permission(db, user, app_id)
    return await chat_service.conversation_summary(db, user.id, app_id)


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_app_permission(db, user, body.app_id)
    conversation = await chat_service.create_conversation(db, user.id, body)
    return _conversation_out(conversation)


@router.delete("/conversations/{cid}")
async def delete_conversation(
    cid: int,
    app_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_app_permission(db, user, app_id)
    await chat_service.delete_conversation(db, user.id, app_id, cid)
    return {"ok": True}


# ── 历史 ────────────────────────────────────────────────
@router.get("/history", response_model=HistoryResponse)
async def get_history(
    app_id: str,
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_app_permission(db, user, app_id)
    title, messages = await chat_service.get_history(db, user.id, app_id, conversation_id)
    return HistoryResponse(
        conversation_title=title,
        messages=[
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "reasoning": m.reasoning,
                "created_at": m.created_at,
            }
            for m in messages
        ],
    )


@router.delete("/history")
async def clear_history(
    app_id: str,
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _check_app_permission(db, user, app_id)
    await chat_service.clear_history(db, user.id, app_id, conversation_id)
    return {"ok": True}
