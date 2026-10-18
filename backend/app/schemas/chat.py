"""请求/响应模型：通用对话（PRD §4.6，架构设计 Q14/Q15/Q16）。"""
import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    app_id: str = "chat"
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=8000)
    model_id: int | None = None  # 会话级绑定（Q15）；缺省走网关默认路由


class ConversationCreate(BaseModel):
    app_id: str = "chat"
    title: str = Field(default="新对话", max_length=64)


class ConversationOut(BaseModel):
    id: int
    app_id: str
    title: str
    model_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ChatModelOut(BaseModel):
    """对话模型池条目：按 Provider 条目分组由前端按 provider 字段归类。"""

    id: int
    name: str
    provider: str  # Provider 条目名
    capabilities: dict[str, Any] = Field(default_factory=dict)  # Q16 meta 固定结构
    is_default: bool  # 是否当前默认路由模型


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: dt.datetime


class HistoryResponse(BaseModel):
    conversation_title: str
    messages: list[ChatMessageOut]
