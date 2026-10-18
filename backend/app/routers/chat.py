"""通用对话接口（PRD §4.6，架构设计 §4.6/§5.2/Q14/Q15）。

- POST /chat：SSE 事件流（delta → [DONE]；中途失败 {error} → [DONE]，半截回复不落库）；
  校验（应用/权限/会话/模型）全部在返回 StreamingResponse 之前完成；
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
    HistoryResponse,
)
from app.services import chat_service, llm_gateway, rbac_service

router = APIRouter(prefix="/chat", tags=["chat"])


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
    """SSE 生成器：流式转发 → 成功后落库（校验与预处理已在路由层完成）。"""
    collected: list[str] = []
    try:
        async for delta in llm_gateway.chat_stream(target.cfg, messages):
            collected.append(delta)
            yield _sse({"delta": delta})
    except llm_gateway.UpstreamError:
        # 流中途失败：已产生文字不落库（PRD §4.6）
        yield _sse({"error": "刚刚卡了一下，没听清，要不再说一次？"})
        yield "data: [DONE]\n\n"
        return

    # 流正常结束：完整助手消息落库后发送 [DONE]
    async with SessionLocal() as db:
        await chat_service.persist_exchange(
            db,
            user_id=user.id,
            app_id=body.app_id,
            conversation_id=target.conversation.id,
            user_message=body.message,
            assistant_message="".join(collected),
            set_title=target.is_new_conversation,
        )
    yield "data: [DONE]\n\n"


@router.post("")
async def chat(body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _check_app_permission(db, user, body.app_id)
    # 校验/会话/模型解析全部在返回 SSE 之前完成：此处抛错可正常返回 4xx/503
    target = await chat_service.prepare_chat(
        db, user.id, body.app_id, body.conversation_id, body.model_id
    )
    messages = await chat_service.build_messages(
        db, user.id, body.app_id, target.conversation.id, body.message
    )
    return StreamingResponse(
        _chat_stream(user, body, target, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
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
