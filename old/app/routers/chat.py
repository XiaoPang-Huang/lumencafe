"""小岛chat：SSE 流式对话 + 多会话管理 + 每日限流。

会话模型：每用户多个对话（chat_conversations），消息挂在会话下；
首条用户消息自动生成会话标题；每日轮数限额按用户全局计。
"""
import json
import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import get_current_user
from ..llm.base import CHAT_SYSTEM_PROMPT, LLMNotConfiguredError
from ..llm.providers import get_llm
from ..models import ChatConversation, ChatMessage, WhitelistUser
from ..schemas import ChatIn

logger = logging.getLogger("island.chat")
router = APIRouter(tags=["chat"])

# 发给模型的最近轮数（一轮 = 用户 + 助手各一条）
MAX_HISTORY_TURNS = 20
# 历史接口最多返回的条数
MAX_HISTORY_RETURN = 200
# 自动生成标题截断长度
TITLE_LEN = 16


def _today_range() -> tuple[datetime, datetime]:
    start = datetime.combine(date.today(), time.min)
    return start, start + timedelta(days=1)


async def used_today(db: AsyncSession, openid: str) -> int:
    start, end = _today_range()
    return (
        await db.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.user_id == openid,
                ChatMessage.role == "user",
                ChatMessage.created_at >= start,
                ChatMessage.created_at < end,
            )
        )
    ).scalar_one()


async def get_conversation_or_404(
    db: AsyncSession, openid: str, cid: int
) -> ChatConversation:
    conv = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == cid, ChatConversation.user_id == openid
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conv


async def latest_conversation(db: AsyncSession, openid: str) -> ChatConversation | None:
    return (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == openid)
            .order_by(ChatConversation.updated_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def resolve_conversation(
    db: AsyncSession, openid: str, cid: int | None
) -> ChatConversation:
    """确定消息归属的会话：传了 id 就校验归属；没传用最近会话，没有则新建。"""
    if cid is not None:
        return await get_conversation_or_404(db, openid, cid)
    conv = await latest_conversation(db, openid)
    if conv is None:
        conv = ChatConversation(user_id=openid, title="新对话")
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    return conv


async def load_context(
    db: AsyncSession, openid: str, conv_id: int
) -> list[dict[str, str]]:
    """取该会话最近 MAX_HISTORY_TURNS 轮，供模型使用。"""
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == openid,
                ChatMessage.conversation_id == conv_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(MAX_HISTORY_TURNS * 2)
        )
    ).scalars().all()
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


# ---------- 会话管理 ----------

class ConvIn(BaseModel):
    title: str | None = Field(default=None, max_length=64)


@router.get("/chat/conversations")
async def list_conversations(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user.openid)
            .order_by(ChatConversation.updated_at.desc())
        )
    ).scalars().all()
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "updated_at": c.updated_at.strftime("%m-%d %H:%M"),
            }
            for c in rows
        ]
    }


@router.post("/chat/conversations")
async def create_conversation(
    body: ConvIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = ChatConversation(user_id=user.openid, title=(body.title or "新对话").strip())
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {"id": conv.id, "title": conv.title}


@router.delete("/chat/conversations/{cid}")
async def delete_conversation(
    cid: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation_or_404(db, user.openid, cid)
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == cid))
    await db.delete(conv)
    await db.commit()
    return {"ok": True}


# ---------- 消息 ----------

@router.get("/chat/history")
async def chat_history(
    conversation_id: int | None = None,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """某会话的历史（默认最近一个会话）；附今日剩余轮数。"""
    conv = await resolve_conversation(db, user.openid, conversation_id)
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == user.openid,
                ChatMessage.conversation_id == conv.id,
            )
            .order_by(ChatMessage.id.asc())
            .limit(MAX_HISTORY_RETURN)
        )
    ).scalars().all()
    used = await used_today(db, user.openid)
    return {
        "conversation_id": conv.id,
        "conversation_title": conv.title,
        "messages": [{"role": r.role, "content": r.content} for r in rows],
        "remaining": max(0, settings.chat_daily_limit - used),
        "limit": settings.chat_daily_limit,
    }


@router.delete("/chat/history")
async def clear_history(
    conversation_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """清空指定会话的消息（会话保留）。"""
    conv = await get_conversation_or_404(db, user.openid, conversation_id)
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conv.id))
    await db.commit()
    return {"ok": True}


@router.post("/chat")
async def chat(
    body: ChatIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        llm = await get_llm("chat")
    except LLMNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="小岛chat 还没接通大模型。请在「我的 → 模型管理」添加并启用一个渠道，或在服务端 .env 配置 ISLAND_LLM_PROVIDER（deepseek/kimi）与 API Key；本地体验可设为 mock。",
        )

    used = await used_today(db, user.openid)
    if settings.chat_daily_limit > 0 and used >= settings.chat_daily_limit:
        raise HTTPException(
            status_code=429,
            detail=f"今天已经聊满 {settings.chat_daily_limit} 轮啦，这是每日上限。去休息一下，明天我还在。",
        )

    conv = await resolve_conversation(db, user.openid, body.conversation_id)
    # 首条消息自动生成标题
    is_first = conv.title in ("新对话", "") 
    if is_first:
        conv.title = body.message.strip()[:TITLE_LEN]
    conv.updated_at = datetime.utcnow()

    # 先存用户消息，再取上下文（包含这条）
    db.add(ChatMessage(
        user_id=user.openid, conversation_id=conv.id,
        role="user", content=body.message,
    ))
    await db.commit()
    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + await load_context(
        db, user.openid, conv.id
    )

    openid = user.openid
    conv_id = conv.id

    async def gen():
        full: list[str] = []
        try:
            async for delta in llm.chat_stream(messages):
                full.append(delta)
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception as e:  # 流中途失败：客户端收到 error 事件，已产生的文字不落库
            logger.warning("chat stream failed for %s: %s", openid, e)
            yield f"data: {json.dumps({'error': '刚刚卡了一下，没听清，要不再说一次？'}, ensure_ascii=False)}\n\n"
        finally:
            text = "".join(full).strip()
            if text:
                # 用独立会话保存，避免依赖请求级 session 的生命周期
                async with SessionLocal() as s:
                    s.add(ChatMessage(
                        user_id=openid, conversation_id=conv_id,
                        role="assistant", content=text,
                    ))
                    await s.commit()
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
