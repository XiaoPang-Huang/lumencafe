"""请求/响应模型：模型管理与网关令牌（PRD §4.3，架构设计 Q10/Q16/Q17）。

增量 v1（R4/R5）：ModelMeta 增 reasoning（思考档位结构）/tools/custom_protocol
预留位；meta 列为 schemaless JSON，新增键无 DDL（架构设计-增量 §3.1）。
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

VENDOR_WHITELIST = ("deepseek", "kimi", "openai", "custom", "mock")

# Q16：meta 固定结构 {"context": "128K", "vision": false, "files": true}
DEFAULT_MODEL_META: dict[str, Any] = {"context": "", "vision": False, "files": False}


# ── meta.reasoning 思考档位结构（R5：档位跟模型官方走）─────────
class ReasoningLevel(BaseModel):
    """单个思考档位：value 为协议透传值（官方原样），label 仅展示用。"""

    value: str = Field(min_length=1, max_length=32)  # off/high/max/32768…
    label: str = Field(min_length=1, max_length=32)  # 高/超高、think-high…（官方命名不翻译）


class MetaReasoning(BaseModel):
    """llm_models.meta.reasoning 固定结构（P1-1 ①）。

    - levels 为空 = 官方仅开关：前端显示「思考 开/关」二态（R5 边界①）；
    - default_level 必须是 levels 中的一项（levels 非空时校验）。
    """

    enabled: bool = False
    levels: list[ReasoningLevel] = Field(default_factory=list)
    default_level: str | None = Field(default=None, max_length=32)

    @field_validator("default_level", mode="after")
    @classmethod
    def _in_levels(cls, v: str | None, info) -> str | None:
        if v and info.data.get("levels") and v not in {x.value for x in info.data["levels"]}:
            raise ValueError("default_level 必须是 levels 中的一项")
        return v


class ModelMeta(BaseModel):
    """llm_models.meta 固定结构（Q16 + R4/R5）：管理端读写统一校验入口。"""

    context: str | None = None
    vision: bool = False
    files: bool = False
    reasoning: MetaReasoning | None = None  # 无该键 = 不支持思考（enabled=false 等效）
    tools: bool = False  # R4 预留位：本期只落数据不落功能
    custom_protocol: bool = False  # R4 预留位：同上


# ── Provider ────────────────────────────────────────────
class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    vendor: str = Field(min_length=1, max_length=32)
    base_url: str = Field(default="", max_length=256)
    api_key: str = Field(default="", max_length=256)
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    vendor: str | None = Field(default=None, min_length=1, max_length=32)
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=256)  # 留空 = 不修改
    enabled: bool | None = None


class ProviderOut(BaseModel):
    """脱敏输出：api_key 永不回显（§9.1）。"""

    id: int
    name: str
    vendor: str
    base_url: str
    enabled: bool
    is_default: bool
    has_key: bool
    api_key_masked: str


class ProviderDetailOut(ProviderOut):
    models: list["ModelOut"] = Field(default_factory=list)


# ── 模型 ────────────────────────────────────────────────
class ModelOut(BaseModel):
    id: int
    name: str
    is_default: bool
    custom: bool
    enabled: bool
    meta: dict[str, Any] = Field(default_factory=dict)
    sort: int


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    meta: dict[str, Any] = Field(default_factory=lambda: dict(DEFAULT_MODEL_META))


class ModelUpdate(BaseModel):
    """模型级修正：能力元数据（Q16 固定结构）与启用开关。"""

    enabled: bool | None = None
    meta: dict[str, Any] | None = None


class FetchedModel(BaseModel):
    name: str
    meta: dict[str, Any] = Field(default_factory=dict)


class TestResult(BaseModel):
    ok: bool
    latency_ms: int
    model: str = ""
    error: str = ""


# ── 默认路由（Q10）──────────────────────────────────────
class RouteRef(BaseModel):
    id: int
    name: str


class DefaultRouteOut(BaseModel):
    provider: RouteRef | None
    model: RouteRef | None


class DefaultRouteSet(BaseModel):
    provider_id: int
    model_id: int


# ── 网关令牌（Q17）──────────────────────────────────────
class GatewayTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    model_scope: list[str] | None = None  # NULL = 全部模型


class GatewayTokenOut(BaseModel):
    id: int
    name: str
    token_mask: str
    model_scope: list[str] | None
    active: bool
    created_at: datetime


class GatewayTokenCreated(BaseModel):
    """完整令牌仅创建时返回一次。"""

    token: str
    item: GatewayTokenOut
