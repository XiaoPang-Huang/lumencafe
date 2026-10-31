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
    # ── 收藏并解析全链路（P16/P20）──
    parse_status: str = "none"  # none|pending|running|done|failed
    parsed_at: dt.datetime | None = None  # 解析完成时间（未完成 null）
    # 轮②（P26）：解析五段阶段 download|upload|queue|parsing（完成/未启动 null）
    parse_phase: str | None = None
    # 轮③（P27）：段落级中英对照翻译状态 none|running|done|failed（未启动/存量 none）
    translate_status: str = "none"
    translate_error: str | None = None  # 翻译失败原因（failed 时有值，可重试）
    # ── 全文与解析解耦（P30）：全文文件就绪度，独立于解析状态机 ──
    fulltext_status: str = "none"  # none（无文件）| oa（获取成功）| uploaded（用户上传/替换）
    fulltext_error: str | None = None  # 获取全文失败原因（可见可重试；成功/上传即清）
    # ── 批注式笔记（P8）：「我的笔记」列表条目统计 ──
    annotations_count: int = 0  # 本人批注条数（不含旧全文笔记）
    last_annotation_at: dt.datetime | None = None  # 最近批注时间（无批注 null）


class PaperDetailOut(PaperOut):
    note: str = ""  # 本人笔记（无则空串；详情面板只读展示）
    explanation: str | None = None  # 全局 AI 解读缓存（无则 null）
    explanation_model: str = ""
    parse_error: str | None = None  # 解析失败原因（P16：错误区 + 手动下载指引）


class SaveResponse(BaseModel):
    saved: bool


# ── 轮①：我的文献工作台（P22/P24，用户世界隔离 P23）─────────
class LibraryItemOut(PaperOut):
    """我的文献列表条目：题录元数据 + 解析状态 + 本人批注统计 + 加入信息。"""

    added_via: str = "crawl"  # crawl | import（轮②导入）
    added_at: dt.datetime | None = None  # 加入我的文献时间
    parse_error: str | None = None  # 轮②：失败原因随列表可见（解析中 tab 展示）
    # P30：替换文件且此前已解析/解析中 → true（后端显式标志，前端「⟳ 重新解析」高亮）
    needs_reparse: bool = False


class LibraryActionOut(BaseModel):
    in_library: bool  # 操作后是否在库（POST 恒 True；幂等重复加入也 True）


# ── 轮②：文献导入（P25：PDF 上传 / arXiv ID / DOI 粘贴）──────
class LibraryImportRequest(BaseModel):
    """导入请求：kind=pdf 走文件上传；kind=identifier 走 arXiv ID / DOI 粘贴。"""

    kind: str = Field(pattern="^(pdf|identifier)$")
    filename: str | None = Field(default=None, max_length=255)  # kind=pdf：原始文件名
    pdf_base64: str | None = Field(default=None, max_length=80_000_000)  # kind=pdf：文件内容 base64
    identifier: str | None = Field(default=None, max_length=512)  # kind=identifier：arXiv ID / DOI


class LibraryImportOut(BaseModel):
    """导入响应：条目恒落库（origin=import，P25/P30 口径见 routers/library_import）。

    P30 解耦：fulltext_error 非空且 parse_status=none = 「已添加但自动下载全文
    失败」（前端引导 [获取全文] 重试或 [上传] 本地文件，绝不误报解析失败）；
    parse_status=failed = 元数据拉取失败（P25，条目落 failed 态 + parse_error）。
    """

    paper_id: int
    title: str
    parse_status: str  # none|pending|running|done|failed（导入成功即触发解析状态机）
    parse_phase: str | None = None  # 阶段条（失败时停在出错段）
    parse_error: str | None = None  # 失败原因（成功 null；元数据失败有值）
    fulltext_status: str | None = None  # none|oa|uploaded（P30：全文就绪态）
    fulltext_error: str | None = None  # 自动下载全文失败原因（P30 解耦展示）


class NoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


# ── P30：全文与解析解耦（获取全文 / 上传全文两个独立动作）──────
class FulltextUploadRequest(BaseModel):
    """上传/替换全文请求：body base64 PDF（≤30MB，后端解码 + 魔数校验）。"""

    pdf_base64: str = Field(min_length=1, max_length=80_000_000)


class FulltextFetchOut(BaseModel):
    """POST /papers/{id}/fetch-fulltext 回执（失败也 200，reason 可见可重试）。

    获取成功即自动触发解析（与导入路对齐）：parse_status 为触发后的即时状态
    （pending = Hatchet 事件已推；done/failed = 进程内同步执行的终态）。
    """

    ok: bool  # true = 全文已在 COS（本次下载成功 / 本就已存在）
    already: bool = False  # true = 幂等直返（此前已有文件，未重新下载）
    source: str | None = None  # 本次下载来源 direct|unpaywall（already 时 null）
    reason: str | None = None  # 失败原因（ok=false 时有值，同 fulltext_error）
    fulltext_status: str = "none"  # 动作后全文状态
    fulltext_error: str | None = None
    parse_status: str = "none"  # 自动解析触发后状态（pending/done/failed/none）
    parse_error: str | None = None  # 解析失败原因（parse_status=failed 时有值）


class FulltextUploadOut(BaseModel):
    """POST /papers/{id}/fulltext 回执：最新全文 + 解析状态（替换触发「需重新解析」）。"""

    ok: bool
    needs_reparse: bool = False  # true = 已四清解析产物并置「需重新解析」标志
    fulltext_status: str = "uploaded"
    fulltext_error: str | None = None
    parse_status: str = "none"  # 动作后解析状态（done 态被替换 → none）
    parse_phase: str | None = None
    parse_error: str | None = None


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
    parse_status: str = "none"  # 解析状态（P16；digest 条目带，前端可按态出徽标）


class ParseStatusOut(BaseModel):
    """解析状态轮询响应（P16：详情面板 2s 轮询到 done/failed 停）。"""

    parse_status: str  # none|pending|running|done|failed
    parse_error: str | None = None  # 失败原因（failed 时有值）
    parsed_at: dt.datetime | None = None  # 完成时间（done 时有值）
    saved: bool = False  # 收藏并解析自动收藏后的回执
    parse_phase: str | None = None  # 轮②（P26）：五段阶段 download|upload|queue|parsing


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


# ── 轮②：立即检索进度条（P26：阶段式进度，轮询本接口）────────
class CrawlStatusOut(BaseModel):
    """GET /papers/crawl-now/status：最新一轮抓取的状态 + 实时进度。"""

    state: str  # idle（无轮次记录）| running | done | failed
    runs_id: int | None = None  # 最新 runs 行 id（idle 时 null）
    run_at: dt.datetime | None = None  # 该轮发起时刻（前端比对防止读到旧轮次）
    added: int | None = None  # 该轮新入库篇数（完成后有值）
    per_source: dict[str, int] = {}  # 各源命中（fetched）篇数
    progress: dict | None = None  # runs.progress（phase/current_keyword/done_keywords/total_keywords/per_source）
    error: str | None = None  # 失败原因（failed 时有值）


# ── P8：批注式笔记 + 知识网（锚定解析段落）────────────────
class ContentBlockOut(BaseModel):
    """结构化段落块（content_list.json 派生；block_id 规则见 services/paper_content.py）。"""

    block_id: str  # p{页}_b{页内序}（页 1 起、页内序 1 起，含非文本块计数）
    type: str  # text|table|image|equation|...
    text: str  # 展示文本（table 为去标签纯文本；image 为 caption 拼接）
    page_idx: int  # 0 起页码
    text_level: int | None = None  # 标题层级 1-4（正文 null）


class PaperContentOut(BaseModel):
    """阅读器正文：GET /papers/{id}/content 响应。"""

    paper_id: int
    title: str
    blocks: list[ContentBlockOut]


class AnnotationCreate(BaseModel):
    anchor_quote: str = Field(min_length=1, max_length=2000)  # 被选中原文
    anchor_block_id: str = Field(min_length=1, max_length=64)  # p{页}_b{序}
    body: str = Field(default="", max_length=5000)  # 空串 = 纯划线


class AnnotationUpdate(BaseModel):
    body: str | None = Field(default=None, max_length=5000)  # None = 不改
    links: list[int] | None = None  # None = 不改；传数组 = 整体替换出链


class AnnotationOut(BaseModel):
    id: int
    paper_id: int
    note_kind: str  # annotation
    anchor_quote: str
    anchor_block_id: str
    body: str  # 空串 = 纯划线
    links: list[int]  # 出链批注 id（保序去重）
    backlink_count: int = 0  # 被链次数（查询派生，双向链接的另一半）
    created_at: dt.datetime
    updated_at: dt.datetime


class RecentAnnotationOut(BaseModel):
    """互链选择器条目：跨论文「最近 N 条我的批注」。"""

    id: int
    paper_id: int
    paper_title: str
    anchor_quote: str
    body: str
    updated_at: dt.datetime


# ── 轮③：段落级中英对照翻译（P27：按钮触发 + translation.json 缓存 + 自动开关）──
class TranslateRequest(BaseModel):
    """翻译触发请求：force=true = 「重新翻译」（清空缓存全量重译，done 态也重跑）。"""

    force: bool = False


class TranslateStatusOut(BaseModel):
    """翻译状态响应（POST /translate 触发回执与 GET /translate-status 轮询共用）。"""

    paper_id: int
    translate_status: str  # none|running|done|failed
    translate_error: str | None = None  # 失败原因（failed 时有值）
    translated_blocks: int = 0  # 已译段落数（translation.json 现有条目）
    total_blocks: int = 0  # 正文 text 块总数


class TranslationOut(BaseModel):
    """阅读器对照译文：GET /papers/{id}/translation（block_id → 中文译文）。"""

    paper_id: int
    translate_status: str  # none|running|done|failed
    translate_error: str | None = None
    translations: dict[str, str]  # block_id（p{页}_b{序}）→ 中文译文
