"""请求/响应模型：通用对话（PRD §4.6，架构设计 Q14/Q15/Q16）。

增量 v1：ChatRequest.thinking_level（R1 白名单内唯一可开放调用参数）/
ChatMessageOut.reasoning（R2）/ConversationOut.thinking_level（P0-2 ⑤ 快照）/
ChatModelOut.reasoning（P0-2 ①）/Polish In-Out（P1-2）。
"""
import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.llm import MetaReasoning


class ChatRequest(BaseModel):
    app_id: str = "chat"
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=8000)
    model_id: int | None = None  # 会话级绑定（Q15）；缺省走网关默认路由
    # R1：可选思考档位（透传值原样来自 meta.reasoning.levels[].value）；不传 = 厂商默认
    thinking_level: str | None = Field(default=None, min_length=1, max_length=32)


class ConversationCreate(BaseModel):
    app_id: str = "chat"
    title: str = Field(default="新对话", max_length=64)


class ConversationOut(BaseModel):
    id: int
    app_id: str
    title: str
    model_id: int | None
    thinking_level: str | None = None  # P0-2 ⑤：会话级档位快照
    created_at: dt.datetime
    updated_at: dt.datetime


class ChatModelOut(BaseModel):
    """对话模型池条目：按 Provider 条目分组由前端按 provider 字段归类。"""

    id: int
    name: str
    provider: str  # Provider 条目名
    capabilities: dict[str, Any] = Field(default_factory=dict)  # Q16 meta 固定结构
    reasoning: MetaReasoning | None = None  # P0-2 ①：思考档位配置（无 = 不支持）
    is_default: bool  # 是否当前默认路由模型


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    reasoning: str | None = None  # R2：思维全文（仅 assistant 可能非空）
    created_at: dt.datetime


class HistoryResponse(BaseModel):
    conversation_title: str
    messages: list[ChatMessageOut]


# ── 润色（P1-2）─────────────────────────────────────────
class PolishIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PolishOut(BaseModel):
    polished: str
