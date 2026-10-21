"""请求/响应模型：SkillHub 目录与已安装技能（架构设计-增量 v1 §3.6）。

- catalog 经后端代理（避免前端跨域/暴露平台细节），每条目含 installed 标记；
- UserSkillOut 不回写 prompt：注入片段服务端存储、用户不可改写（N-增5）。
"""
import datetime as dt

from pydantic import BaseModel, Field


class CatalogQuery(BaseModel):
    """GET /skills/catalog 查询参数（q/page/page_size）。"""

    q: str = Field(default="", max_length=64)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class SkillItemOut(BaseModel):
    skillhub_id: str
    name: str
    icon: str = ""
    description: str = ""
    installed: bool = False  # 本人是否已安装（安装位置固定 app_id=chat）


class CatalogOut(BaseModel):
    items: list[SkillItemOut]
    total: int
    page: int
    page_size: int


class SkillInstallIn(BaseModel):
    skillhub_id: str = Field(min_length=1, max_length=64)


class SkillEnabledIn(BaseModel):
    enabled: bool


class UserSkillOut(BaseModel):
    """本人已安装技能条目（prompt 不回显，任何接口不回写编辑）。"""

    id: int
    skillhub_id: str
    name: str
    icon: str = ""
    description: str = ""
    enabled: bool
    installed_at: dt.datetime
