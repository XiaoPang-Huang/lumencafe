"""LumenCafe 配置。所有配置项均可通过环境变量覆盖，前缀 LUMEN_。

约定：业务代码统一 ``from app.config import settings``，
禁止在业务代码里直接读 os.environ。
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，环境变量前缀 LUMEN_，可读 .env 文件。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="LUMEN_", extra="ignore")

    # 例：postgresql+asyncpg://lumencafe:lumencafe@localhost:5432/lumencafe
    database_url: str = "postgresql+asyncpg://lumencafe:lumencafe@localhost:5432/lumencafe"

    # JWT（后续批次认证使用；生产必须换成长随机串）
    jwt_secret: str = "change-me-in-production"
    jwt_expire_days: int = 30

    # 连接池（2核4G 小池；与 PG max_connections=20 匹配）
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # CORS（本地开发；生产由 Caddy 同域反代，可留空）
    cors_origins: list[str] = ["http://localhost:5173"]

    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """环境变量 LUMEN_CORS_ORIGINS 为逗号分隔字符串，拆成列表。"""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


settings = Settings()
