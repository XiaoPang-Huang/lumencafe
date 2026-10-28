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

    # Skill 文件夹库（Agent Skills 开放标准：skills/<slug>/SKILL.md 为真相源）。
    # 解析优先级：环境变量 SKILL_LIBRARY_DIR > 本项 > 默认 <项目根>/skills；
    # docker-compose 给 api 注入 /app/skills 并挂载 ./skills 卷。
    skill_library_dir: str = ""

    # 文献抓取（NCBI E-utilities；中译走网关默认路由）
    ncbi_email: str = ""  # NCBI 建议带联系邮箱（可选）
    papers_default_keywords: str = ""  # 回落默认订阅关键词（逗号分隔；用户未配置时用）
    papers_retmax: int = 20  # 每关键词每轮最多抓取篇数
    papers_days_back: int = 3  # 只抓最近 N 天发表的文献

    # Hatchet 定时引擎（论文域步 B，组件选型 §三拍板）。只作接线开关与 cron 配置：
    # SDK 连接参数（HATCHET_CLIENT_TOKEN / HATCHET_CLIENT_TLS_STRATEGY）由 compose
    # 从 .env 原样注入容器、SDK 自行读取（不走 LUMEN_ 前缀）。
    # token 留空 = 后端不接线 Hatchet（定时抓取退化到 /internal/jobs 触发），不报错。
    hatchet_client_token: str = ""  # 镜像 settings.hatchet_client_token 仅作「是否接线」开关
    papers_crawl_cron: str = "30 7 * * *"  # 每日抓取 cron；引擎容器 TZ=Asia/Shanghai → 本地 7:30
    papers_cleanup_cron: str = "30 8 * * *"  # 每日 7 天滚动清理 cron（抓取后 1 小时，本地 8:30）
    papers_retention_days: int = 7  # P14：未收藏且无笔记的论文入库保留天数

    # 系统状态（底座步 5）：/api/status 返回值；发版时手动 bump
    app_version: str = "1.0.0"

    # 备份状态卷挂载点（backup 容器写 last_run.json 的共享卷）。
    # compose 中 api 挂载 backup_state → /var/lib/backup-state；留空 = 未挂载，
    # /api/status 的 backup 字段返回 null（未配置灰灯）
    backup_state_dir: str = ""

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
