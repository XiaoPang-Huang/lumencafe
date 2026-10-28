"""请求/响应模型：文献（PRD §4.8，批次 2）。"""
import datetime as dt

from pydantic import BaseModel, Field


class PaperOut(BaseModel):
    id: int
    pmid: str
    title: str
    abstract: str
    abstract_zh: str  # 空串 = 未译
    journal: str
    authors: list[str]
    pub_date: dt.date | None
    cited_count: int | None = None  # 被引次数（P15；源未提供为 null）
    if_approx: float | None = None  # 影响因子近似（OpenAlex 两年篇均引用，非 JCR 官方）
    tags: list[str]
    keywords: list[str]
    created_at: dt.datetime
    saved: bool = False  # 当前用户是否已收藏


class PaperDetailOut(PaperOut):
    note: str = ""  # 本人笔记（无则空串）
    explanation: str | None = None  # 全局 AI 解读缓存（无则 null）
    explanation_model: str = ""


class SaveResponse(BaseModel):
    saved: bool


class NoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class ExplainResponse(BaseModel):
    content: str
    model: str
    cached: bool  # true = 命中缓存


# ── 步 A：数据源清单 + AI 生成订阅关键词 ──────────────────
class SourceOut(BaseModel):
    """源目录市场条目（P17：全量编目展示；已接 5 源可勾选，未实现源只展示）。"""

    key: str  # 源 key（subscribe_sources 存储值；未实现源为预留 key，不可勾选）
    name: str  # 展示名
    category: str  # 分类：综合索引/生物医学/理工/社科人文/中文国内/商业收费/开放期刊
    cost: str  # free（免费直接用）/ free_key（免费需申请 key）/ paid（收费或订阅）
    key_service: str | None = None  # key 表服务名（cost=free 为 null）
    implemented: bool = False  # 是否已接入（注册表内可真实抓取）
    description: str = ""  # 一句话说明（市场展示）
    key_configured: bool = False  # key 源：当前是否已配置启用中的 key（引导「去 Key 管理配置」）


class SuggestKeywordsRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)  # 大白话研究方向描述


class SuggestKeywordsResponse(BaseModel):
    keywords: list[str]  # 8-12 个中英检索关键词（AI 生成，用户勾选确认后自行入库）


# ── P13 本期：自然语言检索（大白话 → AI 扩词 → 临时聚合抓取） ──
class SemanticSearchRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)  # 一句话检索意图


class SemanticSearchResponse(BaseModel):
    keywords: list[str]  # AI 语义扩词结果（不写订阅词，仅本轮检索使用）
    added: int  # 本轮新入库文献数（已按全局键去重，重复命中不计）
    runs_id: int | None = None  # papers_crawl_runs 行 id（trigger=semantic）


# ── 步 B：页内 digest + 立即检索 ──────────────────────────
class DigestItemOut(BaseModel):
    paper_id: int
    title: str
    source: str  # 数据源 key（pubmed/arxiv/...）
    year: int | None  # 发表年（pub_date 缺失时 null）
    url: str  # 落地页（doi 优先；否则按源构造；拿不到为空串）
    authors: list[str] = []  # 作者列表（P15）
    journal: str = ""  # 期刊/venue（P15）
    cited_count: int | None = None  # 被引次数（P15）
    if_approx: float | None = None  # 影响因子近似（P15）
    matched_keywords: list[str]  # 命中的本人订阅关键词（保序去重）
    score: int  # 命中关键词数
    is_high_relevance: bool  # score ≥ HIGH_RELEVANCE_MIN_KEYWORDS（步 B 阈值常量）
    saved: bool = False  # 当前用户是否已收藏（P19 双列表同步的状态源）


class DigestOut(BaseModel):
    last_run_at: dt.datetime | None  # 最近一次抓取轮次时间（无记录时 null）
    last_run_status: str  # success | failed | ""（尚无轮次）
    total_today: int  # 今日命中篇数
    high_relevance_count: int  # 今日高相关篇数
    items: list[DigestItemOut]


class CrawlNowResponse(BaseModel):
    added: int  # 本轮新入库文献数
    runs_id: int  # papers_crawl_runs 行 id
    per_source: dict[str, int]  # 各源本轮命中（provider 返回）篇数
