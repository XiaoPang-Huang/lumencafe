from typing import Any

from pydantic import BaseModel, Field


class WechatLoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class AuthOut(BaseModel):
    authorized: bool
    token: str | None = None
    user: dict[str, Any] | None = None


class SettingsPut(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: Any = Field(default=None)


class AppConfigPut(BaseModel):
    hidden: bool | None = None
    category_id: int | None = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class CategoryRename(BaseModel):
    name: str = Field(min_length=1, max_length=32)


class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)


class TodoPut(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    done: bool | None = None


class MoodIn(BaseModel):
    mood: str = Field(pattern="^(good|ok|anxious)$")


class TaskDoneIn(BaseModel):
    done: bool


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class DangerIn(BaseModel):
    action: str = Field(min_length=1, max_length=32)


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)
    login_code: str = Field(min_length=1, max_length=128)


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class ExplainOut(BaseModel):
    explanation: str
