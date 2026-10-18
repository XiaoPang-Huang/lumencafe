"""请求/响应模型：应用注册表（PRD §4.4）。

用户级覆盖以 DDL §3.3 为准：hidden + 自定义分类（pinned/sort 已在定稿中移除）。
"""
from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    sort: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    sort: int | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    sort: int


class AppOut(BaseModel):
    """注册表条目 + 当前用户可见性覆盖合并结果。"""

    id: str
    name: str
    desc: str
    color: str
    icon: str
    sort: int
    mode: str
    perm_code: str
    category_id: int | None = None  # 用户覆盖优先，无覆盖回退注册表分类
    hidden: bool = False


class AppsResponse(BaseModel):
    apps: list[AppOut]
    categories: list[CategoryOut]


class VisibilityConfig(BaseModel):
    """用户级覆盖 upsert；category_id 显式 null = 清除覆盖。"""

    hidden: bool | None = None
    category_id: int | None = None
