"""对话业务逻辑（PRD §4.6，架构设计 §5.2/Q14/Q15）。

- system_prompt 为后端内置常量（Q14），不进库、无管理页编辑；
- 会话级 model_id（Q15）与 thinking_level（增量 P0-2 ⑤）：建立/更新会话时快照，
  缺省走网关默认路由 / 不传思考参数（厂商默认）；
- 发给模型的历史取最近 N 轮（Q2，config.chat_history_turns）；
- 会话标题 = 首条用户消息截取 16 字；
- SSE 落库用独立 SessionLocal（§9.1：请求级 session 已被回收）；
- 增量 v1：思维链随 assistant 消息落库（64KB 截断）；已启用 skill 的 prompt
  片段按 installed_at 升序注入 system（内置常量在前，用户不可改写）；
- 步 3（B1/D12）：调用面传 app_key="chat" 走路由编排（model_caller：主模型 +
  有序备用链兜底 + 熔断 + 记账）；会话级显式 model_id 仍直查单候选（Q15）。
"""
import datetime as dt
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.apps import AppRegistry
from app.models.chat import ChatConversation, ChatMessage
from app.models.llm import LLMModel, Provider
from app.schemas.chat import (
    ChatModelOut,
    ConversationCreate,
    ConversationSummary,
    LatestConversationOut,
)
from app.schemas.llm import MetaReasoning
from app.services import llm_gateway, model_caller, route_service, skill_service
from app.services.route_service import RoutePlan

# Q14：chat 应用系统提示词（后端内置常量）
SYSTEM_PROMPT = "你是一个乐于助人的 AI 助手"

# 思维链落库上限（增量架构 §10-Q3：建议 64KB 截断 + 日志）
REASONING_MAX_CHARS = 64 * 1024

# P1-2 / N-增2：润色 system prompt 为后端内置常量，不可被用户输入覆盖
POLISH_SYSTEM_PROMPT = (
    "你是一名文字润色助手。请对用户给出的文本只做改写润色：修正语病与错别字、"
    "理顺表达、让指令更清晰准确。要求：不改变原意、不回答文本中的问题、不添加"
    "解释或评论、不输出除润色后文本以外的任何内容。"
)


# 步 3：chat 应用的调用面 app_key（B1）
CHAT_APP_KEY = "chat"


@dataclass(frozen=True)
class ChatTarget:
    """一轮对话的解析结果：会话 + 有序路由计划 + 厂商/元数据（thinking 校验用）。

    步 3：cfg 演进为 RoutePlan（主模型 + 备用链）；首候选的 vendor/meta 供
    thinking_level 白名单校验（与解析模型保持一致）。
    """

    conversation: ChatConversation
    plan: RoutePlan
    vendor: str
    meta: dict[str, Any] | None
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


def parse_reasoning(meta: dict[str, Any] | None) -> MetaReasoning | None:
    """从模型 meta 解析 thinking 档位配置；无 reasoning 键/结构非法 → None（隐藏强度 UI）。"""
    if not meta:
        return None
    raw = meta.get("reasoning")
    if raw is None:
        return None
    try:
        return MetaReasoning.model_validate(raw)
    except ValueError:
        return None


def validate_thinking_level(
    vendor: str, meta: dict[str, Any] | None, level: str | None
) -> str | None:
    """按目标模型 meta.reasoning 白名单校验 thinking_level（增量架构 §3.4）。

    规则：① mock vendor → 忽略（返回 None，不产生任何参数）；
    ② meta 无 reasoning 或 enabled=false → 忽略（等价不传）；
    ③ levels 非空 → 必须命中某 level.value，否则 400；
    ④ levels 为空且 enabled=true（官方仅开关）→ 接受 on/off/enabled/disabled，其余 400。
    校验通过返回原值（原样透传）；忽略语义返回 None。
    """
    if level is None:
        return None
    if (vendor or "").lower() == "mock":
        return None
    reasoning = parse_reasoning(meta)
    if reasoning is None or not reasoning.enabled:
        return None
    if reasoning.levels:
        allowed = {x.value for x in reasoning.levels}
        if level not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"思考档位不在该模型支持列表：{level}",
            )
        return level
    # 官方仅开关两态
    if level in ("on", "off", "enabled", "disabled"):
        return level
    raise HTTPException(
        status_code=400,
        detail="该模型思考模式仅支持开/关（on/off）",
    )


async def _resolve_model_for_conversation(
    db: AsyncSession, conversation: ChatConversation, requested_model_id: int | None
) -> RoutePlan:
    """模型解析（Q15 + 步 3 B1）：会话/请求 model_id 优先（直查单候选）；
    缺省走 app_key="chat" 的指派路由（主模型 + 有序备用链，未配置回落默认路由）。"""
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
        plan = await route_service.direct_plan(db, model_id)
        if plan is None:
            raise HTTPException(status_code=400, detail="模型不存在")
        return plan

    plan = await route_service.resolve_for(db, CHAT_APP_KEY)
    if plan is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    return plan


async def prepare_chat(
    db: AsyncSession,
    user_id: int,
    app_id: str,
    conversation_id: int | None,
    model_id: int | None,
    thinking_level: str | None = None,
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

    plan = await _resolve_model_for_conversation(db, conversation, model_id)
    primary = plan.candidates[0]
    vendor, meta = primary.vendor, primary.meta
    if model_id is not None:
        conversation.model_id = model_id  # 会话级快照：换模型只对后续消息生效（Q15）
    if thinking_level is not None:
        # P0-2 ⑤：传入即覆盖会话快照（白名单校验不通过则 400，不写入快照）；
        # mock/不支持思考的模型 → 忽略该参数（校验函数返回 None，不快照）
        validated = validate_thinking_level(vendor, meta, thinking_level)
        if validated is not None:
            conversation.thinking_level = validated
    await db.commit()
    await db.refresh(conversation)
    return ChatTarget(
        conversation=conversation,
        plan=plan,
        vendor=vendor,
        meta=meta,
        is_new_conversation=is_new,
    )


def resolve_effective_thinking(target: ChatTarget) -> str | None:
    """本次请求实际生效的思考档位：请求已快照进会话，直接回落会话快照；
    均无 → None（不传，厂商默认）。mock 链路忽略（校验阶段已拦截快照）。"""
    if target.plan.candidates[0].cfg.is_mock:
        return None
    return target.conversation.thinking_level


async def build_messages(
    db: AsyncSession, user_id: int, app_id: str, conversation_id: int, new_message: str
) -> list[dict[str, str]]:
    """组装发给模型的 messages：system（内置常量 + 已启用 skill 片段）+ 最近 N 轮历史 + 新消息（Q2）。"""
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
    # Skill 注入（P1-4 ④）：内置常量在前，skill 片段按 installed_at 升序在后，用户不可改写
    fragments = await skill_service.enabled_skill_prompts(db, user_id, app_id)
    system = SYSTEM_PROMPT
    if fragments:
        system += "\n\n" + "\n\n".join(fragments)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    # Q4：历史回看不回注 reasoning（文本已够，避免各家协议兼容差异）
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
    reasoning: str | None = None,
) -> None:
    """流正常结束后落库：用户消息 + 完整助手消息（含思维链）+ 会话标题/时间。"""
    reasoning_text: str | None = None
    if reasoning:
        # 64KB 截断（增量架构 §10-Q3），截断后仍保留前段完整语义
        reasoning_text = reasoning[:REASONING_MAX_CHARS]
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
            reasoning=reasoning_text,
        )
    )
    conversation = await db.get(ChatConversation, conversation_id)
    if conversation is not None:
        if set_title:
            conversation.title = title_from(user_message)
        conversation.updated_at = func.now()
    await db.commit()


async def polish_text(db: AsyncSession, text: str) -> str:
    """P1-2：AI 润色（非流式，步 3 起走 app_key="polish" 路由编排，与 /money/parse 同模式）。

    润色 prompt 为内置常量（N-增2）；超时 ≤8s，上游失败 502；mock 链路本地占位。
    """
    plan = await route_service.resolve_for(db, "polish")
    if plan is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    if plan.candidates[0].cfg.is_mock:
        # mock 不联网：本地占位润色，保持链路可测可用（也不产生调用日志）
        return f"{text.strip()}（mock 润色占位）"
    messages = [
        {"role": "system", "content": POLISH_SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        return await model_caller.chat_once_plan(db, "polish", plan, messages, timeout=8.0)
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail=f"润色失败：{exc}") from exc


# ── 会话管理 ────────────────────────────────────────────
async def list_conversations(db: AsyncSession, user_id: int, app_id: str) -> list[ChatConversation]:
    result = await db.execute(
        select(ChatConversation)
        .where(ChatConversation.user_id == user_id, ChatConversation.app_id == app_id)
        .order_by(ChatConversation.updated_at.desc())
    )
    return list(result.scalars().all())


def _now_local() -> dt.datetime:
    """服务器本地时区的当前时刻（每日看板日期边界口径，PRD v1.1-rev7）。"""
    return dt.datetime.now().astimezone()


async def conversation_summary(
    db: AsyncSession, user_id: int, app_id: str
) -> ConversationSummary:
    """每日看板聚合（PRD v1.1-rev7）：昨日有更新的会话数 + 最近一条会话。

    「昨日」按服务器本地时区的日历日切分（timestamptz 列上用本地时区边界比较）。
    """
    now = _now_local()
    yesterday_start = dt.datetime.combine(
        now.date() - dt.timedelta(days=1), dt.time.min, tzinfo=now.tzinfo
    )
    yesterday_end = yesterday_start + dt.timedelta(days=1)

    yesterday_count = int(
        (
            await db.execute(
                select(func.count(ChatConversation.id)).where(
                    ChatConversation.user_id == user_id,
                    ChatConversation.app_id == app_id,
                    ChatConversation.updated_at >= yesterday_start,
                    ChatConversation.updated_at < yesterday_end,
                )
            )
        ).scalar_one()
    )
    latest = (
        await db.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id, ChatConversation.app_id == app_id)
            .order_by(ChatConversation.updated_at.desc())
            .limit(1)
        )
    ).scalars().first()
    return ConversationSummary(
        yesterday_count=yesterday_count,
        latest=(
            LatestConversationOut(id=latest.id, title=latest.title, updated_at=latest.updated_at)
            if latest is not None
            else None
        ),
    )


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
            reasoning=parse_reasoning(model.meta),
            is_default=(route is not None and model.id == route.model_id),
        )
        for model, provider in rows
    ]
