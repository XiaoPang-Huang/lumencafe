"""ORM 模型汇总：Alembic autogenerate 的 metadata 来源。

分模块对应架构设计 §3：
user（§3.1 五表）/ llm（§3.2 三表）/ apps（§3.3 三表）/
chat（§3.4 两表）/ user_settings（§3.5 一表）/ money（§3.6 两表）。
"""
from app.models.apps import AppRegistry, AppVisibility, Category
from app.models.chat import ChatConversation, ChatMessage
from app.models.llm import GatewayToken, LLMModel, Provider
from app.models.money import MoneyCategory, MoneyTransaction
from app.models.user import Permission, Role, RolePermission, User, UserRole
from app.models.user_settings import UserSetting

__all__ = [
    "AppRegistry",
    "AppVisibility",
    "Category",
    "ChatConversation",
    "ChatMessage",
    "GatewayToken",
    "LLMModel",
    "MoneyCategory",
    "MoneyTransaction",
    "Permission",
    "Provider",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "UserSetting",
]
