"""服务 Key 表 schemas（架构设计-增量 v2.9）。

- service_key（服务标识）格式：小写字母 + 数字 + 下划线（新增/编辑均校验）；
- 输出一律掩码（前 4 + **** + 后 4），api_key 完整值只有 POST/PUT 写入时接收。
"""
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

SERVICE_KEY_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")


def _check_service_key(cls: type, value: str) -> str:
    if not SERVICE_KEY_PATTERN.fullmatch(value):
        raise ValueError("service_key 仅允许小写字母、数字、下划线（1-64 位）")
    return value


class ServiceKeyCreate(BaseModel):
    service_key: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)  # 选填
    note: str | None = Field(default=None, max_length=512)  # 选填
    enabled: bool = True

    _v_service_key = field_validator("service_key")(_check_service_key)


class ServiceKeyUpdate(BaseModel):
    """编辑：service_key 为服务标识，创建后不可改（前端弹窗只读，本 schema 不开放该字段）。"""

    vendor: str | None = Field(default=None, min_length=1, max_length=64)
    api_key: str | None = Field(default=None, max_length=512)  # 留空 = 不修改
    base_url: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None


class ServiceKeyOut(BaseModel):
    """脱敏输出：api_key 永不回显，仅返回掩码（前 4 + **** + 后 4）。"""

    id: int
    service_key: str
    vendor: str
    api_key_masked: str
    base_url: str | None
    note: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
