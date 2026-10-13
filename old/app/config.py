"""小岛 API 配置。所有配置项均可通过环境变量覆盖，前缀 ISLAND_。"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ISLAND_", extra="ignore")

    # 例：postgresql+asyncpg://island:island@postgres:5432/island
    database_url: str = "postgresql+asyncpg://island:island@localhost:5432/island"

    jwt_secret: str = "change-me-in-production"
    jwt_expire_hours: int = 72

    # 微信小程序 AppID / AppSecret（服务端调用 code2session 用，严禁泄露到前端）
    wechat_appid: str = ""
    wechat_secret: str = ""

    # 开发模式：login code 以 "dev:" 开头时直接视为对应 openid，不请求微信服务器。
    # 生产环境务必设为 false。
    dev_login: bool = True

    # ===== 文献推送（PubMed 抓取） =====
    # NCBI 建议带上联系邮箱，可选
    ncbi_email: str = ""
    # 订阅关键词（逗号分隔），默认覆盖神经内科退行性疾病方向
    subscribe_keywords: list[str] = [
        "Alzheimer",
        "Parkinson",
        "ALS",
        "biomarker",
        "neurodegenerative",
    ]
    # 抓取窗口：只抓最近 N 天发表的文献
    days_back: int = 3
    # 每日推送时间（本地时间 HH:MM）
    push_time: str = "08:00"

    # ===== LLM（文献 AI 解读 + 小岛树洞） =====
    # 供应商：deepseek / kimi / mock（本地开发占位），留空则未开通（前端友好提示）
    llm_provider: str = ""
    deepseek_key: str = ""
    kimi_key: str = ""

    # 小岛chat：每人每日对话轮数上限；0 = 不限制（2026-10-11 用户要求取消限制）
    chat_daily_limit: int = 0

    @field_validator("subscribe_keywords", mode="before")
    @classmethod
    def _split_keywords(cls, v: object) -> object:
        """环境变量 ISLAND_SUBSCRIBE_KEYWORDS 为逗号分隔字符串，拆成列表。"""
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v


settings = Settings()
