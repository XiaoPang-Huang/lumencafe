"""LumenCafe 配置。所有配置项均可通过环境变量覆盖，前缀 LUMEN_。

约定：业务代码统一 ``from app.config import settings``，
禁止在业务代码里直接读 os.environ。
"""
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，环境变量前缀 LUMEN_，可读 .env 文件。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LUMEN_", extra="ignore")

    # 例：postgresql+asyncpg://lumencafe:lumencafe@localhost:5432/lumencafe
    database_url: str = "postgresql+asyncpg://lumencafe:lumencafe@localhost:5432/lumencafe"

    # JWT（后续批次认证使用；生产必须换成长随机串）
    jwt_secret: str = "change-me-in-production"
    jwt_expire_days: int = 30

    # 注册开关（默认关；实例部署者自行开启）
    registration_open: bool = False

    # 首次启动引导管理员（仅 users 表为空时生效）
    admin_username: str = "admin"
    admin_password: str = "change-me-too"

    # 内部令牌（/internal/jobs/* 与 /gw/* 共用；留空 = 均关闭 503）
    internal_token: str = ""

    # 初始 LLM 渠道种子（providers 表为空时导入；mock = 本地开发占位，不联网）
    llm_provider: str = ""  # mock / deepseek / kimi / 留空不种子
    deepseek_key: str = ""
    kimi_key: str = ""

    # 登录/注册限流（PRD N14）：同 IP 每分钟次数；测试环境可关
    rate_limit_enabled: bool = True
    auth_rate_limit_per_minute: int = 10

    # 连接池（2核4G 小池；与 PG max_connections=20 匹配）
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # 对话
    chat_history_turns: int = 20  # 发给模型的最近轮数（PRD Q2，一轮 = 问答两条）

    # CORS（本地开发；生产由 Caddy 同域反代，可留空）
    # NoDecode：环境变量按原始字符串交给下面的拆分校验器，不做 JSON 解析
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """环境变量 LUMEN_CORS_ORIGINS 为逗号分隔字符串，拆成列表。"""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()
