"""请求/响应模型：用户设置与个人页（PRD §4.5）。"""
from typing import Any

from pydantic import BaseModel, Field


class SettingUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: dict[str, Any]


class MeResponse(BaseModel):
    id: int
    username: str
    nickname: str
    roles: list[str]
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
