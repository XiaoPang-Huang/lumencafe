"""请求/响应模型：平台管理-成员与 RBAC（PRD §4.2）。"""
from datetime import datetime

from pydantic import BaseModel, Field


# ── 权限点 ──────────────────────────────────────────────
class PermissionOut(BaseModel):
    code: str
    name: str
    description: str

    model_config = {"from_attributes": True}


# ── 角色 ────────────────────────────────────────────────
class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=128)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    description: str | None = Field(default=None, max_length=128)


class SetPermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)  # 权限点 code 整体重设


class RoleOut(BaseModel):
    id: int
    name: str
    description: str
    built_in: bool
    permissions: list[PermissionOut] = Field(default_factory=list)


# ── 用户 ────────────────────────────────────────────────
class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=32)
    role_ids: list[int] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None


class SetRolesRequest(BaseModel):
    role_ids: list[int] = Field(default_factory=list)  # 整体重设


class RoleBrief(BaseModel):
    id: int
    name: str


class AdminUserOut(BaseModel):
    id: int
    username: str
    nickname: str
    is_active: bool
    is_deleted: bool
    roles: list[RoleBrief] = Field(default_factory=list)
    created_at: datetime


class AdminUserDetailOut(AdminUserOut):
    permissions: list[str] = Field(default_factory=list)


class ResetPasswordOut(BaseModel):
    new_password: str


class UserPage(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    page_size: int
