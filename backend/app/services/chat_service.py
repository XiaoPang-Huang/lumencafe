"""对话业务逻辑（PRD §4.6，架构设计 §5.2/Q14/Q15）。

- system_prompt 为后端内置常量（Q14），不进库、无管理页编辑；
- 会话级 model_id（Q15）：建立/更新会话时快照，缺省走网关默认路由；
- 发给模型的历史取最近 N 轮（Q2，config.chat_history_turns）；
- 会话标题 = 首条用户消息截取 16 字；
- SSE 落库用独立 SessionLocal（§9.1：请求级 session 已被回收）。
"""
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.apps import AppRegistry
from app.models.chat import ChatConversation, ChatMessage
from app.models.llm import LLMModel, Provider
from app.schemas.chat import ChatModelOut, ConversationCreate
from app.services import route_service
from app.services.llm_gateway import ClientCfg

# Q14：chat 应用系统提示词（后端内置常量）
SYSTEM_PROMPT = "你是一个乐于助人的 AI 助手"


@dataclass(frozen=True)
class ChatTarget:
    """一轮对话的解析结果：会话 + 客户端配置。"""

    conversation: ChatConversation
    cfg: ClientCfg
    model_name: str
    is_new_conversation: bool


async def get_app(db: AsyncSession, app_id: str) -> AppRegistry:
    app = (
        await db.execute(select(AppRegistry).where(AppRegistry.id == app_id))
    ).scalar_one_or_none()
    if app is None:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


def title_from(message: str) -> str:
    """会话标题：首条用户消息截取 16 字。"""
    return message[:16]


async def _resolve_model_for_conversation(
    db: AsyncSession, conversation: ChatConversation, requested_model_id: int | None
) -> tuple[ClientCfg, str]:
    """模型解析（Q15）：会话/请求 model_id 优先，缺省走网关默认路由。"""
    model_id = requested_model_id or conversation.model_id
    if model_id is not None:
        row = (
            await db.execute(select(LLMModel, Provider).join(Provider, Provider.id == LLMModel.provider_id).where(LLMModel.id == model_id))
        ).first()
        if row is None:
            raise HTTPException(status_code=400, detail="模型不存在")
        model, provider = row
        if not model.enabled:
            raise HTTPException(status_code=400, detail="模型已停用")
        if not provider.enabled:
            raise HTTPException(status_code=503, detail="模型所属渠道已停用")
        return (
            ClientCfg(base_url=provider.base_url, api_key=provider.api_key, model=model.name),
            model.name,
        )

    route = await route_service.resolve_default(db)
    if route is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    return route.cfg, route.model_name


async def prepare_chat(
    db: AsyncSession, user_id: int, app_id: str, conversation_id: int | None, model_id: int | None
) -> ChatTarget:
    """请求级预处理（StreamingResponse 返回前完成所有校验与落库）。"""
    await get_app(db, app_id)

    is_new = False
    if conversation_id is not None:
        conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.user_id == user_id,
                    ChatConversation.app_id == app_id,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        conversation = (
            await db.execute(
                select(ChatConversation)
                .where(
                    ChatConversation.user_id == user_id,
                    ChatConversation.app_id == app_id,
                )
                .order_by(ChatConversation.updated_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if conversation is None:
            conversation = ChatConversation(user_id=user_id, app_id=app_id)
            db.add(conversation)
            is_new = True

    cfg, model_name = await _resolve_model_for_conversation(db, conversation, model_id)
    if model_id is not None:
        conversation.model_id = model_id  # 会话级快照：换模型只对后续消息生效（Q15）
    await db.commit()
    await db.refresh(conversation)
    return ChatTarget(
        conversation=conversation, cfg=cfg, model_name=model_name, is_new_conversation=is_new
    )


async def build_messages(
    db: AsyncSession, user_id: int, app_id: str, conversation_id: int, new_message: str
) -> list[dict[str, str]]:
    """组装发给模型的 messages：system + 最近 N 轮历史 + 新消息（Q2）。"""
    limit = settings.chat_history_turns * 2
    history = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.user_id == user_id,
                ChatMessage.app_id == app_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in reversed(history):
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": new_message})
    return messages


async def persist_exchange(
    db: AsyncSession,
    *,
    user_id: int,
    app_id: str,
    conversation_id: int,
    user_message: str,
    assistant_message: str,
    set_title: bool,
) -> None:
    """流正常结束后落库：用户消息 + 完整助手消息 + 会话标题/时间。"""
    db.add(
        ChatMessage(
            conversation_id=conversation_id,
            user_id=user_id,
            app_id=app_id,
            role="user",
            content=user_message,
        )
    )
    db.add(
        ChatMessage(
            conversation_id=conversation_id,
            user_id=user_id,
            app_id=app_id,
            role="assistant",
            content=assistant_message,
        )
    )
    conversation = await db.get(ChatConversation, conversation_id)
    if conversation is not None:
        if set_title:
            conversation.title = title_from(user_message)
        conversation.updated_at = func.now()
    await db.commit()


# ── 会话管理 ────────────────────────────────────────────
async def list_conversations(db: AsyncSession, user_id: int, app_id: str) -> list[ChatConversation]:
    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id, ChatConversation.app_id == app_id)
        .order_by(ChatConversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def create_conversation(
    db: AsyncSession, user_id: int, body: ConversationCreate
) -> ChatConversation:
    await get_app(db, body.app_id)
    conversation = ChatConversation(user_id=user_id, app_id=body.app_id, title=body.title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def delete_conversation(db: AsyncSession, user_id: int, app_id: str, cid: int) -> None:
    conversation = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == cid,
                ChatConversation.user_id == user_id,
                ChatConversation.app_id == app_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(conversation)  # 消息 ON DELETE CASCADE
    await db.commit()


async def get_history(
    db: AsyncSession, user_id: int, app_id: str, cid: int
) -> tuple[str, list[ChatMessage]]:
    conversation = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == cid,
                ChatConversation.user_id == user_id,
                ChatConversation.app_id == app_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == cid)
            .order_by(ChatMessage.id)
            .limit(200)
        )
    ).scalars().all()
    return conversation.title, list(messages)


async def clear_history(db: AsyncSession, user_id: int, app_id: str, cid: int) -> None:
    conversation = (
        await db.execute(
            select(ChatConversation).where(
                ChatConversation.id == cid,
                ChatConversation.user_id == user_id,
                ChatConversation.app_id == app_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == cid))
    await db.commit()


async def list_chat_models(db: AsyncSession) -> list[ChatModelOut]:
    """对话模型池：启用 Provider 的启用模型；默认路由模型标 is_default。"""
    route = await route_service.resolve_default(db)
    rows = (
        await db.execute(
            select(LLMModel, Provider)
            .join(Provider, Provider.id == LLMModel.provider_id)
            .where(Provider.enabled.is_(True), LLMModel.enabled.is_(True))
            .order_by(Provider.id, LLMModel.sort, LLMModel.id)
        )
    ).all()
    return [
        ChatModelOut(
            id=model.id,
            name=model.name,
            provider=provider.name,
            capabilities=dict(model.meta or {}),
            is_default=(route is not None and model.id == route.model_id),
        )
        for model, provider in rows
    ]
