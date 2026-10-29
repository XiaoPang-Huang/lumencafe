"""文献接口（PRD §4.8，权限点 app:papers，批次 2；步 A 多源扩展；步 B digest+立即检索）。

- /papers/daily：仅本人订阅抓到的文献（paper_users 归属隔离），tag JSONB `@>` 筛选；
- 收藏为幂等 toggle；笔记每人每篇一条 upsert；
- AI 解读全局缓存（paper_explanations 一篇一条，成功才入库，命中直返）；
- 步 A：/papers/sources 已注册源清单（订阅设置勾选框）；
  /papers/suggest-keywords 大白话 → AI 生成订阅关键词（不写库，保存走 /me/settings）；
- 步 B：/papers/digest 今日命中 + 高相关（按本人订阅关键词重算命中）+ 最近抓取轮次；
  /papers/crawl-now 立即检索（进程内锁防并发，force 跳过同日幂等）。
- 论文域增强（P15/P18）：digest 与 /papers/daily 支持 sort(time|if|score)、
  if_min（影响因子下限，null 值被过滤）、limit；未显式传的参数回落用户 papers_prefs
  （user_settings JSONB：{display_limit, sort, if_min}），响应条目带齐元数据字段。
- 论文域修复轮：sort 三字段 SQL 显式 NULLS LAST（PG DESC 默认 NULLS FIRST，
  没 IF/被引的沉底）；digest 窗口改为「最近一轮成功检索（runs.status=success）
  的 run_at 之后入库」，无 runs 记录回落本地今日零点。
- 论文域增强③（P16/P20）：POST /papers/{id}/collect-parse 收藏并解析（自动收藏幂等
  → 触发 papers-parse workflow，引擎未接线回落进程内同步执行；done 直返/pending·
  running 409/failed·none 可重跑）；GET /papers/{id}/parse-status 轮询；GET
  /papers/parsed = 我的笔记列表；digest/daily 条目与详情带 parse_status（详情另带
  parse_error 供失败指引区）。
- 轮①（P22/P23/P24 用户世界隔离 + 我的文献工作台，Alembic 0011）：papers 行级
  归属 user_id（抓取去重/upsert 限同 user 内，同一篇两人抓各存一份）；新表
  paper_library（我的文献，阅读/批注/翻译唯一入口）；POST /papers/{id}/library
  幂等加入；DELETE /papers/{id}/library 级联删（本人 papers 行 + 本人批注 +
  COS 产物四件 + 收藏/归属/库关联；非行主只解除本人归属）；GET /papers/library
  本人列表（元数据 + parse_status + annotations_count）；/library 注册在
  /{pid} 之前（单段路径匹配顺序）。
- 论文域后批①（P8 批注式笔记 + 知识网，Alembic 0010 改造 paper_notes 双形态）：
  GET /papers/{id}/content 阅读器正文（content_list → 稳定 block_id `p{页}_b{序}`，
  无产物 404）；POST/GET /papers/{id}/annotations 建批注（body 可空=纯划线）/
  本篇列表；PUT/DELETE /papers/annotations/{aid} 改正文/换出链/删除（自链与越权
  目标 422，删除级联摘链）；GET /papers/annotations/recent 互链选择器（最近 N 条，
  跨论文）；GET /papers/annotations/{aid}/backlinks 反向链接（查询派生，边单写）；
  /papers/parsed 条目带 annotations_count/last_annotation_at；旧 /note upsert 保留
  （note_kind='note' 每篇至多一条的部分唯一索引约束不变）。
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.papers import (
    Paper,
    PaperCrawlRun,
    PaperExplanation,
    PaperFavorite,
    PaperLibrary,
    PaperNote,
    PaperUser,
)
from app.models.user import User
from app.models.user_settings import UserSetting
from app.schemas.papers import (
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    ContentBlockOut,
    CrawlNowResponse,
    CrawlStatusOut,
    DigestItemOut,
    DigestOut,
    ExplainResponse,
    LibraryActionOut,
    LibraryImportOut,
    LibraryImportRequest,
    LibraryItemOut,
    NoteRequest,
    PaperContentOut,
    PaperDetailOut,
    PaperOut,
    ParseStatusOut,
    RecentAnnotationOut,
    SaveResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SourceOut,
    SuggestKeywordsRequest,
    SuggestKeywordsResponse,
)
from app.services import (
    llm_gateway,
    paper_content,
    paper_import,
    paper_library,
    paper_parse,
    papers_crawl,
    pipeline,
    route_service,
)
from app.services.sources import SOURCE_CATALOG, SourceCatalogEntry, list_providers
from app.services.sources.keys import fetch_service_api_key

router = APIRouter(prefix="/papers", tags=["papers"])

logger = logging.getLogger("lumencafe.papers")

EXPLAIN_PROMPT = (
    "你是神经退行性疾病领域的文献解读助手。基于给出的论文标题与摘要输出中文解读，"
    "固定四段式（用①②③④标出）：①研究背景与问题 ②方法概要 ③主要发现 ④局限与意义。"
    "只依据摘要内容，不要臆测；摘要信息不足时明确说明。直接输出解读正文。"
    "\n\n标题：{title}\n\n摘要：{abstract}"
)

# 步 A：AI 生成订阅关键词的系统提示词（内置常量；app_key=papers_config 解析路由）
SUGGEST_KEYWORDS_APP_KEY = "papers_config"
SUGGEST_KEYWORDS_SYSTEM = (
    "你是学术文献订阅关键词提炼助手。用户用一句大白话描述研究方向，"
    "你要提炼成 8-12 个适合在文献数据库（PubMed/arXiv/OpenAlex 等）检索的关键词。"
    "要求：中英文都给出（英文关键词用于国际库检索，中文用于说明可附）；"
    "每个关键词 1-4 个词，覆盖核心概念、关键方法、应用场景等同义表达；"
    "不要输出任何解释、编号或多余文字，严格返回 JSON 字符串数组，"
    '形如 ["关键词1", "keyword 2", ...]。'
)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

# P18：展示设置缺省（用户未存 papers_prefs 时的口径）
# P21 扩展：同一份 papers_prefs 兼存抓取期过滤参数（year_from/year_to/authors），
# 解析口径与抓取管线共用 papers_crawl.parse_papers_prefs（单一事实源）。
DEFAULT_PAPERS_PREFS: dict = dict(papers_crawl.PAPERS_PREFS_DEFAULTS)
SORT_MODES: tuple[str, ...] = papers_crawl.SORT_MODES  # 时间 / 影响因子 / 相关度


async def _reader(user: User = Depends(require_permission("app:papers"))) -> User:
    return user


async def _papers_prefs(db: AsyncSession, user_id: int) -> dict:
    """读取用户展示偏好（user_settings.papers_prefs），缺省回落 DEFAULT_PAPERS_PREFS。

    value 形如 {display_limit: 50, sort: "time", if_min: null, year_from: null,
    year_to: null, authors: []}；非法/越界字段逐项回落缺省，不整单丢弃
    （偏好是体验项，容错优先）。解析逻辑与抓取管线共用 parse_papers_prefs。
    """
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id, UserSetting.key == "papers_prefs"
            )
        )
    ).scalar_one_or_none()
    return papers_crawl.parse_papers_prefs(row.value if row is not None else None)


def _out(p: Paper, saved: bool = False) -> PaperOut:
    return PaperOut(
        id=p.id,
        pmid=p.pmid,
        title=p.title,
        abstract=p.abstract,
        abstract_zh=p.abstract_zh,
        journal=p.journal,
        authors=list(p.authors or []),
        pub_date=p.pub_date,
        cited_count=p.cited_count,
        if_approx=float(p.if_approx) if p.if_approx is not None else None,
        tags=list(p.tags or []),
        keywords=list(p.keywords or []),
        created_at=p.created_at,
        saved=saved,
        parse_status=p.parse_status or "none",
        parsed_at=p.parsed_at,
        parse_phase=p.parse_phase,
    )


async def _last_successful_run_at(db: AsyncSession) -> datetime | None:
    """最近一轮成功抓取（runs.status=success）的 run_at；无成功轮次返回 None。

    digest 的「本轮新命中」窗口锚点：失败轮次不算数（那轮没带来新数据），
    窗口应锚在最近一次真正检索成功的时间上。
    """
    return (
        await db.execute(
            select(func.max(PaperCrawlRun.run_at)).where(PaperCrawlRun.status == "success")
        )
    ).scalar_one_or_none()


async def _saved_ids(db: AsyncSession, user_id: int, paper_ids: list[int]) -> set[int]:
    if not paper_ids:
        return set()
    rows = (
        await db.execute(
            select(PaperFavorite.paper_id).where(
                PaperFavorite.user_id == user_id, PaperFavorite.paper_id.in_(paper_ids)
            )
        )
    ).scalars().all()
    return set(rows)


async def _get_mine(db: AsyncSession, user_id: int, pid: int) -> Paper:
    """归属隔离：仅 paper_users 中属于我的文献可见（不泄露存在性，统一 404）。"""
    owned = (
        await db.execute(
            select(PaperUser.id).where(PaperUser.user_id == user_id, PaperUser.paper_id == pid)
        )
    ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    return paper


@router.get("/sources", response_model=list[SourceOut])
async def list_paper_sources(user: User = Depends(_reader), db: AsyncSession = Depends(get_db)):
    """源目录市场清单（P17）：编目（含未实现源）× 注册表合并，订阅设置弹窗数据源。

    - implemented=True 的源可勾选（注册表内真实可抓取）；未实现源只展示、不可勾选
      （前端徽标「待接入」）；
    - cost=free_key / paid 且带 key_service 的源，key_configured 反映当前是否存在
      启用中的 key：未配置时前端引导「去 Key 管理配置」（不泄露 key 本体，
      仅存在性，与 admin 掩码口径一致的安全水位）。
    """
    implemented_keys = {p.name for p in list_providers()}
    entries = list(SOURCE_CATALOG)
    # 注册表内但不在编目里的实现（防御：未来加源忘编目）按注册表信息补位
    known = {e.key for e in entries}
    for p in list_providers():
        if p.name not in known:
            entries.append(
                SourceCatalogEntry(
                    key=p.name, name=p.display_name, category="综合索引",
                    cost="free", key_service=getattr(p, "key_service", None),
                    description="已接入数据源",
                )
            )
    out: list[SourceOut] = []
    for e in entries:
        key_configured = False
        if e.key_service:
            key_configured = await fetch_service_api_key(db, e.key_service) is not None
        out.append(
            SourceOut(
                key=e.key,
                name=e.name,
                category=e.category,
                cost=e.cost,
                key_service=e.key_service,
                implemented=e.key in implemented_keys,
                description=e.description,
                key_configured=key_configured,
            )
        )
    return out


def _parse_keyword_array(content: str) -> list[str]:
    """解析 LLM 返回为关键词数组：剥 code fence → json.loads → 校验字符串数组。

    返回保序去重、去空白后的关键词；解析失败/结构不符抛 ValueError（路由层转 502）。
    """
    cleaned = _CODE_FENCE_RE.sub("", content or "").strip()
    data = json.loads(cleaned)
    if not isinstance(data, list) or not all(isinstance(k, str) for k in data):
        raise ValueError("AI 返回不是 JSON 字符串数组")
    out: list[str] = []
    for kw in data:
        kw = kw.strip()
        if kw and kw not in out:
            out.append(kw)
    if not out:
        raise ValueError("AI 返回的关键词数组为空")
    return out


async def _suggest_keywords(db: AsyncSession, description: str) -> list[str]:
    """大白话 → AI 生成检索关键词（步 A 拍板 P4 核心逻辑，路由与 P13 语义检索共用）。

    走网关按消费者路由（app_key=papers_config，未配置指派回落默认路由）；
    不写库。解析失败/上游失败抛 HTTPException（路由层直接外透语义）。
    """
    plan = await route_service.resolve_for(db, SUGGEST_KEYWORDS_APP_KEY)
    if plan is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    try:
        content = await llm_gateway.chat_once(
            plan.candidates[0].cfg,
            [
                {"role": "system", "content": SUGGEST_KEYWORDS_SYSTEM},
                {"role": "user", "content": description.strip()},
            ],
            timeout=60.0,
        )
    except llm_gateway.UpstreamError as exc:
        logger.warning("生成订阅关键词失败：%s", exc)
        raise HTTPException(status_code=502, detail="AI 生成失败，请稍后再试") from exc
    try:
        return _parse_keyword_array(content)
    except (ValueError, TypeError) as exc:
        logger.warning("订阅关键词解析失败：%s（原文：%.200s）", exc, content)
        raise HTTPException(
            status_code=502, detail="AI 返回内容无法解析为关键词数组，请重试"
        ) from exc


@router.post("/suggest-keywords", response_model=SuggestKeywordsResponse)
async def suggest_keywords(
    body: SuggestKeywordsRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """大白话 → AI 生成 8-12 个中英检索关键词（步 A 拍板 P4）。

    不写库——用户勾选确认后由前端调 /me/settings 保存 subscribe_keywords。
    """
    return SuggestKeywordsResponse(keywords=await _suggest_keywords(db, body.description))


@router.post("/semantic-search", response_model=SemanticSearchResponse)
async def semantic_search(
    body: SemanticSearchRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """P13 本期·自然语言检索：一句话 → AI 语义扩词 → 临时聚合抓取一轮。

    - 扩词走与 /papers/suggest-keywords 同一通道（不写订阅词，仅本轮使用）；
    - 抓取复用按用户聚合管线（勾选源 + P21 参数同口径），结果照常全局去重入库；
    - 写 runs(trigger=semantic)：digest「最近一轮成功检索」窗口刷新，页内立即可见；
    - 与每日/手动轮共用抓取锁：409 = 已有轮次进行中（前端防抖 + loading 防重）。
    """
    keywords = await _suggest_keywords(db, body.description)
    try:
        result = await papers_crawl.run_semantic_search(db, user.id, keywords)
    except papers_crawl.CrawlAlreadyRunning as exc:
        raise HTTPException(
            status_code=409, detail="已有检索正在进行，请稍后再试"
        ) from exc
    return SemanticSearchResponse(keywords=keywords, **result)


# ── 步 B：页内 digest + 立即检索 ──────────────────────────
def _paper_url(p: Paper) -> str:
    """文献落地页：doi 优先；否则按源从全局去重键（pmid 列）构造；拿不到为空串。"""
    if p.doi:
        return f"https://doi.org/{p.doi}"
    key = p.pmid or ""
    if p.source == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{key}/"
    prefix, _, rest = key.partition(":")
    if prefix == "arxiv" and rest:
        return f"https://arxiv.org/abs/{rest}"
    if prefix == "openalex" and rest:
        return f"https://openalex.org/{rest}"
    if prefix == "semantic_scholar" and rest:
        return f"https://www.semanticscholar.org/paper/{rest}"
    return ""


@router.get("/digest", response_model=DigestOut)
async def digest(
    sort: str | None = Query(default=None, pattern="^(time|if|score)$"),
    if_min: float | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """页内 digest（拍板 P1）：本轮新命中且命中本人订阅关键词的文献 + 高相关标记。

    窗口口径（修复轮）：papers.created_at ≥ 最近一轮成功检索（runs.status=success）
    的 run_at——过了午夜昨天的命中仍属于「本轮」，与页头 last_run_at 对齐；
    无任何成功轮次时回落本地今日零点（入库日=今日，本地时区）。
    再 ∩ paper_users 本人归属；命中 = 用与抓取打标同一套 match_keywords 按本人
    当前订阅关键词（resolve_user_keywords，与抓取回落口径一致）重算；高相关 =
    命中数 ≥ HIGH_RELEVANCE_MIN_KEYWORDS（步 B 常量，先简单后精细）。

    排序过滤（P18）：sort=time|if|score（默认 time=入库时间倒序；if=影响因子近似
    倒序 NULLS LAST；score=命中词数倒序）——三个字段 SQL 全部显式 NULLS LAST，
    没 IF/没打分的沉底（PG 默认 DESC NULLS FIRST，不显式会被顶到最前）；
    if_min=影响因子下限（设置了则近似值为 null 的条目被过滤）；limit 截断展示条数。
    未显式传的参数回落 papers_prefs。在已抓数据上筛排，不触发重检索；
    total_today/high_relevance_count 为过滤后、截断前的口径（页头数字与筛选项所见一致）。
    """
    prefs = await _papers_prefs(db, user.id)
    sort = sort or prefs["sort"]
    if_min = if_min if if_min is not None else prefs["if_min"]
    limit = limit or prefs["display_limit"]

    keywords = await papers_crawl.resolve_user_keywords(db, user.id)
    last_ok = await _last_successful_run_at(db)
    if last_ok is not None:
        window_start = last_ok
    else:
        window_start = datetime.now().astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    stmt = select(Paper).join(PaperUser, PaperUser.paper_id == Paper.id).where(
        PaperUser.user_id == user.id, Paper.created_at >= window_start
    )
    if sort == "if":
        stmt = stmt.order_by(
            Paper.if_approx.desc().nullslast(),
            Paper.created_at.desc().nullslast(),
            Paper.id.desc(),
        )
    else:
        # time 与 score 的兜底顺序：入库时间倒序（score 的命中词数在 Python 侧重算后
        # 稳定排序，行序即并列时的次序）；created_at 显式 NULLS LAST 保持一致口径
        stmt = stmt.order_by(Paper.created_at.desc().nullslast(), Paper.id.desc())
    if if_min is not None:
        stmt = stmt.where(Paper.if_approx >= if_min)  # null 近似值被下限过滤
    rows = (await db.execute(stmt)).scalars().all()
    saved_ids = await _saved_ids(db, user.id, [p.id for p in rows])

    items: list[DigestItemOut] = []
    for p in rows:
        matched = papers_crawl.match_keywords(p.title, p.abstract, keywords)
        if not matched:
            continue  # 今日入库但已不命中当前订阅关键词（改订阅后常见），digest 不推
        score = len(matched)
        items.append(
            DigestItemOut(
                paper_id=p.id,
                title=p.title,
                source=p.source,
                year=p.pub_date.year if p.pub_date else None,
                url=_paper_url(p),
                authors=list(p.authors or []),
                journal=p.journal,
                cited_count=p.cited_count,
                if_approx=float(p.if_approx) if p.if_approx is not None else None,
                matched_keywords=matched,
                score=score,
                is_high_relevance=score >= papers_crawl.HIGH_RELEVANCE_MIN_KEYWORDS,
                saved=p.id in saved_ids,
                parse_status=p.parse_status or "none",
            )
        )

    # 稳定排序：if/time 已按 SQL NULLS LAST 定序；score（命中词数，Python 侧重算）
    # 在行序（created_at 倒序）基础上稳定排序，同分并列保持时间倒序
    if sort == "score":
        items.sort(key=lambda i: -i.score)

    total = len(items)
    high = sum(1 for i in items if i.is_high_relevance)
    items = items[:limit]

    last_run = (
        await db.execute(
            select(PaperCrawlRun).order_by(PaperCrawlRun.run_at.desc(), PaperCrawlRun.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return DigestOut(
        last_run_at=last_run.run_at if last_run else None,
        last_run_status=last_run.status if last_run else "",
        total_today=total,
        high_relevance_count=high,
        items=items,
    )


@router.post("/crawl-now", response_model=CrawlNowResponse)
async def crawl_now(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """立即检索（拍板 P6）：同步跑一轮按用户聚合抓取，写 runs(trigger=manual)。

    进程内 asyncio 锁防并发：已有轮次进行中返回 409（不重排队，避免叠加压力）。
    force 跳过 Q11 同日幂等——用户显式点「立即检索」就是要跑一轮；入库仍幂等
    （papers upsert / paper_users ON CONFLICT DO NOTHING），重复跑不重复建行。
    """
    try:
        return await papers_crawl.run_manual_crawl(db)
    except papers_crawl.CrawlAlreadyRunning as exc:
        raise HTTPException(
            status_code=409, detail="已有抓取正在进行，请稍后再试"
        ) from exc


@router.get("/crawl-now/status", response_model=CrawlStatusOut)
async def crawl_now_status(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """立即检索进度轮询（轮② P26）：返回最新一轮 runs 的状态 + 实时进度。

    - 无 runs 记录 → state=idle；
    - 最新行 status=running → state=running + progress（阶段/当前关键词/各源计数，
      轮内逐源更新同一 runs 行，1.5s 轮询粒度足够平滑）；
    - 终态 → state=done|failed + 该轮汇总（added/per_source/error）。
    前端用 run_at 与点击时刻比对，防止把上一轮终态误当本轮完成。
    """
    run = (
        await db.execute(
            select(PaperCrawlRun).order_by(
                PaperCrawlRun.run_at.desc(), PaperCrawlRun.id.desc()
            ).limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return CrawlStatusOut(state="idle")
    state = "running" if run.status == "running" else (
        "done" if run.status == "success" else "failed"
    )
    stats = run.stats or {}
    per_source = {
        source: counts.get("fetched", 0)
        for source, counts in (stats.get("per_source") or {}).items()
        if isinstance(counts, dict)
    }
    return CrawlStatusOut(
        state=state,
        runs_id=run.id,
        run_at=run.run_at,
        added=stats.get("added"),
        per_source=per_source,
        progress=run.progress,
        error=run.error,
    )


@router.get("/daily", response_model=list[PaperOut])
async def daily_papers(
    tag: str | None = None,
    sort: str | None = Query(default=None, pattern="^(time|if|score)$"),
    if_min: float | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """每日推送：本人订阅抓到的文献；tag 为 JSONB 包含筛选。

    排序过滤（P18）同 /papers/digest：sort=time|if|score（score=抓取打标命中词数），
    三个字段 SQL 全部显式 NULLS LAST（没 IF/没打分的沉底）；
    if_min 影响因子下限（null 被过滤），limit 截断；未显式传的参数回落 papers_prefs。
    在已抓数据上筛排，不触发重检索。
    """
    prefs = await _papers_prefs(db, user.id)
    sort = sort or prefs["sort"]
    if_min = if_min if if_min is not None else prefs["if_min"]
    limit = limit or prefs["display_limit"]

    stmt = select(Paper).join(PaperUser, PaperUser.paper_id == Paper.id).where(
        PaperUser.user_id == user.id
    )
    if tag:
        stmt = stmt.where(Paper.tags.contains([tag]))
    if if_min is not None:
        stmt = stmt.where(Paper.if_approx >= if_min)  # null 近似值被下限过滤
    if sort == "if":
        stmt = stmt.order_by(
            Paper.if_approx.desc().nullslast(),
            Paper.created_at.desc().nullslast(),
            Paper.id.desc(),
        )
    elif sort == "score":
        # 相关度=抓取打标命中词数（keywords JSONB 长度），数据库内排序
        stmt = stmt.order_by(
            func.jsonb_array_length(Paper.keywords).desc().nullslast(),
            Paper.created_at.desc().nullslast(),
            Paper.id.desc(),
        )
    else:
        stmt = stmt.order_by(Paper.created_at.desc().nullslast(), Paper.id.desc())
    stmt = stmt.limit(limit)
    papers = list((await db.execute(stmt)).scalars().all())
    saved = await _saved_ids(db, user.id, [p.id for p in papers])
    return [_out(p, p.id in saved) for p in papers]


@router.get("/favorites", response_model=list[PaperOut])
async def favorite_papers(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(Paper)
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == user.id)
            .order_by(PaperFavorite.created_at.desc())
        )
    ).scalars().all()
    return [_out(p, True) for p in rows]


# ── 收藏并解析全链路（P16/P20）────────────────────────────
async def _parse_status_out(db: AsyncSession, user_id: int, pid: int) -> ParseStatusOut:
    """按当前库内状态组轮询响应（saved 反映「收藏并解析」自动收藏后的回执）。"""
    paper = (
        await db.execute(select(Paper).where(Paper.id == pid))
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    saved = await _saved_ids(db, user_id, [pid])
    return ParseStatusOut(
        parse_status=paper.parse_status or "none",
        parse_error=paper.parse_error,
        parsed_at=paper.parsed_at,
        saved=pid in saved,
        parse_phase=paper.parse_phase,
    )


@router.get("/parsed", response_model=list[PaperOut])
async def parsed_papers(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """我的笔记列表（P16）：已收藏且解析完成（parse_status=done）的文献。

    按 parsed_at 倒序；P8 起条目带 annotations_count / last_annotation_at
    （本人批注统计，供列表展示「N 条批注 · 最后批注时间」）。
    """
    rows = (
        await db.execute(
            select(Paper)
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == user.id, Paper.parse_status == "done")
            .order_by(Paper.parsed_at.desc().nullslast(), Paper.id.desc())
        )
    ).scalars().all()
    out = [_out(p, True) for p in rows]
    if out:
        stats = (
            await db.execute(
                select(
                    PaperNote.paper_id,
                    func.count(PaperNote.id),
                    func.max(PaperNote.updated_at),
                )
                .where(
                    PaperNote.user_id == user.id,
                    PaperNote.note_kind == "annotation",
                    PaperNote.paper_id.in_([p.id for p in rows]),
                )
                .group_by(PaperNote.paper_id)
            )
        ).all()
        stat_map = {pid: (cnt, latest) for pid, cnt, latest in stats}
        for item in out:
            cnt, latest = stat_map.get(item.id, (0, None))
            item.annotations_count = cnt
            item.last_annotation_at = latest
    return out


# ── 轮①：我的文献工作台（P22 一级页；加入幂等 / 删除级联 P24；隔离 P23）──
# 注意：/library 为单段路径，必须注册在 /{pid} 之前（FastAPI 按注册顺序匹配）。
@router.get("/library", response_model=list[LibraryItemOut])
async def list_library(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """我的文献列表：题录元数据 + parse_status + 本人批注数（annotations_count）。

    只含本人库内行（paper_library.user_id 过滤，P23 行级隔离）；
    批注统计与 /papers/parsed 同口径（仅 annotation 形态，不含旧全文笔记）。
    """
    rows = await paper_library.list_library(db, user.id)
    papers_list = [p for _, p in rows]
    out = []
    stat_map: dict[int, tuple[int, object]] = {}
    if papers_list:
        stats = (
            await db.execute(
                select(
                    PaperNote.paper_id,
                    func.count(PaperNote.id),
                )
                .where(
                    PaperNote.user_id == user.id,
                    PaperNote.note_kind == "annotation",
                    PaperNote.paper_id.in_([p.id for p in papers_list]),
                )
                .group_by(PaperNote.paper_id)
            )
        ).all()
        stat_map = {pid: (cnt, None) for pid, cnt in stats}
    for lib, p in rows:
        cnt, _ = stat_map.get(p.id, (0, None))
        item = LibraryItemOut(
            **_out(p, True).model_dump(),
            added_via=lib.added_via,
            added_at=lib.created_at,
        )
        item.annotations_count = cnt
        item.parse_error = p.parse_error  # 失败原因随列表可见（解析中 tab 展示）
        out.append(item)
    return out


@router.get("/library/parsing", response_model=list[LibraryItemOut])
async def list_library_parsing(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """「解析中」tab 数据源（轮② P26/P28）：库内全部未完成的解析任务。

    口径 = 本人 library ∩ parse_status ∈ {pending, running, failed}（done 完成、
    none 从未发起不算任务）；每条带 parse_phase 五段阶段 + parse_error 失败原因，
    前端 2s 轮询刷新阶段条。
    """
    rows = await paper_library.list_library(db, user.id)
    out: list[LibraryItemOut] = []
    for lib, p in rows:
        status = p.parse_status or "none"
        if status not in ("pending", "running", "failed"):
            continue
        item = LibraryItemOut(
            **_out(p, True).model_dump(),
            added_via=lib.added_via,
            added_at=lib.created_at,
        )
        item.parse_error = p.parse_error
        out.append(item)
    return out


@router.post("/library/import", response_model=LibraryImportOut)
async def library_import(
    body: LibraryImportRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """导入文献（拍板 P25）：① PDF 上传 ② arXiv ID / DOI 粘贴。

    - 条目恒落库：papers.origin=import + owner=本人 + 自动进 library（added_via=
      import）+ 触发解析状态机（pdf_bytes 通道，阶段条从「上传」起）；
    - 请求本身不合法（格式/大小/非 PDF）→ 422，不落条目；
    - 元数据/全文下载失败 → 条目落 failed 态 + parse_error 记原因（保留可重试，
      P25），响应 200 携 parse_status=failed 与原因——前端 toast「导入失败：<原因>」。
    """
    paper: Paper | None = None
    if body.kind == "pdf":
        if not body.pdf_base64:
            raise HTTPException(status_code=422, detail="请选择一个 PDF 文件")
        try:
            data = paper_import.decode_pdf_base64(body.pdf_base64)
            paper = await paper_import.import_pdf(db, user.id, body.filename or "", data)
        except paper_import.ImportInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        if not body.identifier or not body.identifier.strip():
            raise HTTPException(status_code=422, detail="请输入 arXiv ID 或 DOI")
        try:
            paper = await paper_import.import_identifier(db, user.id, body.identifier)
        except paper_import.ImportInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except paper_import.ImportFailedError as exc:
            # 条目已落 failed 态：回读行组响应（明确失败信息随 200 返回）
            paper = (
                await db.execute(
                    select(Paper).where(
                        Paper.user_id == user.id, Paper.pmid == _import_key(body.identifier)
                    )
                )
            ).scalar_one_or_none()
            if paper is None:  # 防御：理论上条目必在
                raise HTTPException(status_code=502, detail=str(exc)) from exc

    assert paper is not None
    return LibraryImportOut(
        paper_id=paper.id,
        title=paper.title,
        parse_status=paper.parse_status or "none",
        parse_phase=paper.parse_phase,
        parse_error=paper.parse_error,
    )


def _import_key(raw: str) -> str:
    """与 paper_import 同口径的去重键（失败回读用）：arxiv:{id} / doi:{doi}。"""
    try:
        kind, ident = paper_import.classify_identifier(raw)
    except paper_import.ImportInputError:
        return ""
    return f"{kind}:{ident}"


@router.post("/{pid}/library", response_model=LibraryActionOut)
async def add_to_library(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """加入我的文献（幂等）：归属校验（paper_users 本人）后 ON CONFLICT DO NOTHING。

    已加入再调一次无副作用（不刷新加入时间/途径），返回 in_library=True。
    """
    await _get_mine(db, user.id, pid)
    await paper_library.add_to_library(db, pid, user.id, added_via="crawl")
    return LibraryActionOut(in_library=True)


@router.delete("/{pid}/library")
async def remove_from_library(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """从我的文献删除（拍板 P24 级联）：本人 papers 行 + 本人批注/笔记 +
    COS 产物四件（parsed/{id} 三件 + pdfs 分层 PDF）+ 收藏/归属/库关联全清。

    非行主的历史共享行只解除本人归属（P23：删自己的不影响对方）。
    """
    await _get_mine(db, user.id, pid)
    result = await paper_library.delete_from_library(db, pid, user.id)
    return {"ok": True, **result}


@router.get("/{pid}/parse-status", response_model=ParseStatusOut)
async def parse_status(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """解析状态轮询（P16：详情面板 2s 轮询到 done/failed 停）；归属隔离同详情。"""
    await _get_mine(db, user.id, pid)
    return await _parse_status_out(db, user.id, pid)


@router.post("/{pid}/collect-parse", response_model=ParseStatusOut)
async def collect_parse(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """解析入口收紧（拍板 P28）：仅「我的文献」库内可发起解析。

    - 归属校验（_get_mine，404）后加库内校验：不在本人 library → 403
      （前端详情面板主按钮已改「＋ 我的文献」，解析只在 #/library 内发起）；
    - 幂等：done 直返不再跑；pending/running 返回 409（前端「解析中…」禁用按钮）；
      failed/none 允许重跑（重试 = 再次点按钮）；
    - 触发：Hatchet 事件推送成功 → 异步执行（先置 pending 占坑防并发双跑）；
      引擎未接线/推送失败 → 进程内同步执行（与 crawl-now 同一哲学，即时出结果）。
    """
    paper = await _get_mine(db, user.id, pid)
    # P28：目标论文须在本人 library（否 403）；同时自动入库存工作台语义
    in_library = (
        await db.execute(
            select(PaperLibrary.id).where(
                PaperLibrary.user_id == user.id, PaperLibrary.paper_id == pid
            )
        )
    ).scalar_one_or_none()
    if in_library is None:
        raise HTTPException(
            status_code=403, detail="该文献不在你的「我的文献」中，请先加入后再发起解析"
        )
    # 自动收藏（幂等；收藏本身持久化，受 P14 清空规则保护）
    await db.execute(
        pg_insert(PaperFavorite)
        .values(paper_id=pid, user_id=user.id)
        .on_conflict_do_nothing(index_elements=["paper_id", "user_id"])
    )
    await db.commit()

    paper = (
        await db.execute(select(Paper).where(Paper.id == pid))
    ).scalar_one_or_none()
    status = paper.parse_status or "none"
    if status == "done":
        return await _parse_status_out(db, user.id, pid)
    if status in ("pending", "running"):
        raise HTTPException(status_code=409, detail="该文献正在解析中，请稍后再试")

    # 置 pending 占坑（第二个并发请求到此即 409，workflow/进程内执行各自置 running）
    paper.parse_status = "pending"
    paper.parse_error = None
    await db.commit()

    if not pipeline.push_parse_event(pid, user.id):
        # 引擎未接线：进程内同步执行（下载 → COS → MinerU → 状态机），即时返回终态
        await paper_parse.run_parse_pipeline(db, pid, user.id)
    return await _parse_status_out(db, user.id, pid)


@router.get("/{pid}", response_model=PaperDetailOut)
async def paper_detail(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    paper = await _get_mine(db, user.id, pid)
    # P8：note 字段 = 旧全文笔记行（note_kind='note'，每篇至多一条）；批注走 /annotations
    note = (
        await db.execute(
            select(PaperNote).where(
                PaperNote.user_id == user.id,
                PaperNote.paper_id == pid,
                PaperNote.note_kind == "note",
            )
        )
    ).scalar_one_or_none()
    explanation = (
        await db.execute(select(PaperExplanation).where(PaperExplanation.paper_id == pid))
    ).scalar_one_or_none()
    saved = await _saved_ids(db, user.id, [pid])
    return PaperDetailOut(
        **_out(paper, pid in saved).model_dump(),
        note=note.content if note else "",
        explanation=explanation.content if explanation else None,
        explanation_model=explanation.model if explanation else "",
        parse_error=paper.parse_error,
    )


@router.post("/{pid}/save", response_model=SaveResponse)
async def toggle_save(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """幂等切换收藏：已收藏 → 取消；未收藏 → 收藏。"""
    await _get_mine(db, user.id, pid)
    stmt = pg_insert(PaperFavorite).values(paper_id=pid, user_id=user.id).on_conflict_do_nothing(
        index_elements=["paper_id", "user_id"]
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 1:
        return SaveResponse(saved=True)
    # 已存在 → 取消收藏
    existing = (
        await db.execute(
            select(PaperFavorite).where(
                PaperFavorite.user_id == user.id, PaperFavorite.paper_id == pid
            )
        )
    ).scalar_one_or_none()
    if existing is None:  # 并发下恰好被他人删（不可能，同 user_id），兜底
        return SaveResponse(saved=False)
    await db.delete(existing)
    await db.commit()
    return SaveResponse(saved=False)


@router.post("/{pid}/note")
async def upsert_note(
    pid: int,
    body: NoteRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """笔记 upsert：每人每篇一条全文笔记（note_kind='note'），覆盖更新。

    P8 后唯一性落在部分唯一索引（仅 note_kind='note'）上，ON CONFLICT 需带
    同款 index_where 才能命中索引推断。
    """
    await _get_mine(db, user.id, pid)
    stmt = (
        pg_insert(PaperNote)
        .values(paper_id=pid, user_id=user.id, content=body.content, note_kind="note")
        .on_conflict_do_update(
            index_elements=["paper_id", "user_id"],
            index_where=text("note_kind = 'note'"),
            set_={"content": body.content},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


@router.post("/{pid}/explain", response_model=ExplainResponse)
async def explain_paper(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """AI 解读：命中缓存直返；未命中调网关默认路由生成并写全局缓存（成功才入库）。"""
    paper = await _get_mine(db, user.id, pid)
    cached = (
        await db.execute(select(PaperExplanation).where(PaperExplanation.paper_id == pid))
    ).scalar_one_or_none()
    if cached is not None:
        return ExplainResponse(content=cached.content, model=cached.model, cached=True)

    route = await route_service.resolve_default(db)
    if route is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    try:
        content = await llm_gateway.chat_once(
            route.cfg,
            [
                {"role": "system", "content": "你是文献解读助手，直接输出解读正文。"},
                {
                    "role": "user",
                    "content": EXPLAIN_PROMPT.format(
                        title=paper.title, abstract=paper.abstract[:6000]
                    ),
                },
            ],
            timeout=60.0,
        )
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试") from exc
    if not content or not content.strip():
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试")

    stmt = (
        pg_insert(PaperExplanation)
        .values(paper_id=pid, content=content.strip(), model=route.model_name)
        .on_conflict_do_nothing(index_elements=["paper_id"])  # 并发兜底：先成者入库
    )
    await db.execute(stmt)
    await db.commit()
    return ExplainResponse(content=content.strip(), model=route.model_name, cached=False)


# ── P8：批注式笔记 + 知识网（锚定解析段落，Alembic 0010）────
def _annotation_out(
    note: PaperNote, backlink_counts: dict[int, int] | None = None
) -> AnnotationOut:
    """PaperNote 行 → 批注响应（backlink_count 由调用方传入的统计表派生）。"""
    return AnnotationOut(
        id=note.id,
        paper_id=note.paper_id,
        note_kind=note.note_kind,
        anchor_quote=note.anchor_quote or "",
        anchor_block_id=note.anchor_block_id or "",
        body=note.content or "",
        links=list(note.links or []),
        backlink_count=(backlink_counts or {}).get(note.id, 0),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def _backlink_counts(
    db: AsyncSession, user_id: int, ids: list[int]
) -> dict[int, int]:
    """被链次数表：扫描本人全部批注的出链，统计指向 ids 各元素的边数。

    双向链接的派生半侧（另一半 = 存于 note.links 的出链）：边只写一次，
    反向永远由查询得出——单写无同步泄漏风险（Obsidian backlinks 同构）。
    """
    counts = {i: 0 for i in ids}
    if not ids:
        return counts
    rows = (
        await db.execute(
            select(PaperNote.id, PaperNote.links).where(
                PaperNote.user_id == user_id, PaperNote.note_kind == "annotation"
            )
        )
    ).all()
    for _row_id, links in rows:
        for target in links or []:
            if target in counts:
                counts[target] += 1
    return counts


async def _get_annotation(db: AsyncSession, user_id: int, aid: int) -> PaperNote:
    """批注行级隔离：只认本人 annotation 行（不泄露存在性，统一 404）。"""
    note = (
        await db.execute(
            select(PaperNote).where(
                PaperNote.id == aid,
                PaperNote.user_id == user_id,
                PaperNote.note_kind == "annotation",
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="批注不存在")
    return note


async def _validate_links(
    db: AsyncSession, user_id: int, self_id: int, links: list[int]
) -> list[int]:
    """出链校验：保序去重、拒自链、目标必须存在且是本人的批注（否则 422）。"""
    cleaned: list[int] = []
    for raw in links:
        target = int(raw)
        if target == self_id:
            raise HTTPException(status_code=422, detail="批注不能链接到自己")
        if target not in cleaned:
            cleaned.append(target)
    if not cleaned:
        return []
    rows = (
        await db.execute(
            select(PaperNote.id).where(
                PaperNote.user_id == user_id,
                PaperNote.note_kind == "annotation",
                PaperNote.id.in_(cleaned),
            )
        )
    ).scalars().all()
    if set(rows) != set(cleaned):
        raise HTTPException(status_code=422, detail="出链目标不存在或不属于你的批注")
    return cleaned


@router.get("/{pid}/content", response_model=PaperContentOut)
async def paper_content_view(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """阅读器正文（P8）：解析产物 content_list.json → 结构化段落数组。

    block_id = `p{页}_b{页内序}`（规则见 services/paper_content.py）；无解析产物
    （未解析/对象缺失/JSON 损坏）一律 404「还没有解析产物」——拍板 P8 明确语义。
    鉴权：app:papers 登录 + paper_users 归属（收藏者可见，与详情同口径）。
    """
    paper = await _get_mine(db, user.id, pid)
    blocks = await paper_content.load_parsed_content(db, pid)
    if blocks is None:
        raise HTTPException(
            status_code=404, detail="该文献还没有解析产物，请先「收藏并解析」"
        )
    return PaperContentOut(
        paper_id=pid,
        title=paper.title,
        blocks=[ContentBlockOut(**b) for b in blocks],
    )


@router.post(
    "/{pid}/annotations", response_model=AnnotationOut, status_code=201
)
async def create_annotation(
    pid: int,
    body: AnnotationCreate,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """建批注：anchor_quote（被选中原文）+ anchor_block_id（锚定段落）。

    body 可空串 = 纯划线（Zotero/hypothes.is 式）。anchor_block_id 必须在当前
    解析产物的块集合内（422 = 段落不存在，通常是解析产物更新后前端旧锚点）。
    """
    await _get_mine(db, user.id, pid)
    blocks = await paper_content.load_parsed_content(db, pid)
    if blocks is None:
        raise HTTPException(
            status_code=404, detail="该文献还没有解析产物，请先「收藏并解析」"
        )
    valid_ids = {b["block_id"] for b in blocks}
    if body.anchor_block_id not in valid_ids:
        raise HTTPException(status_code=422, detail="锚定段落不存在（解析产物已更新？）")
    note = PaperNote(
        paper_id=pid,
        user_id=user.id,
        content=body.body,
        anchor_quote=body.anchor_quote,
        anchor_block_id=body.anchor_block_id,
        note_kind="annotation",
        links=[],
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _annotation_out(note)


@router.get("/{pid}/annotations", response_model=list[AnnotationOut])
async def list_annotations(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """本篇我的批注列表（含出链 links 与被链数 backlink_count），id 升序。"""
    await _get_mine(db, user.id, pid)
    notes = (
        await db.execute(
            select(PaperNote)
            .where(
                PaperNote.paper_id == pid,
                PaperNote.user_id == user.id,
                PaperNote.note_kind == "annotation",
            )
            .order_by(PaperNote.id)
        )
    ).scalars().all()
    counts = await _backlink_counts(db, user.id, [n.id for n in notes])
    return [_annotation_out(n, counts) for n in notes]


@router.get("/annotations/recent", response_model=list[RecentAnnotationOut])
async def recent_annotations(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """互链选择器数据源：我的最近 N 条批注（跨论文，updated_at 倒序）。

    拍板 P8「链到…」弹该论文（或跨论文）我的批注选择器（最近 20 条）——
    前端按当前篇优先排序展示。
    """
    rows = (
        await db.execute(
            select(PaperNote, Paper.title)
            .join(Paper, Paper.id == PaperNote.paper_id)
            .where(PaperNote.user_id == user.id, PaperNote.note_kind == "annotation")
            .order_by(PaperNote.updated_at.desc(), PaperNote.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        RecentAnnotationOut(
            id=note.id,
            paper_id=note.paper_id,
            paper_title=title,
            anchor_quote=note.anchor_quote or "",
            body=note.content or "",
            updated_at=note.updated_at,
        )
        for note, title in rows
    ]


@router.put("/annotations/{aid}", response_model=AnnotationOut)
async def update_annotation(
    aid: int,
    body: AnnotationUpdate,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """改批注：body（None=不改）/ links（None=不改；传数组=整体替换出链）。

    双向链接语义：links 是出链，A 链 B 后 B 的 backlink_count 立即 +1
    （派生查询，无需写 B）；自链与越权目标 422。
    """
    note = await _get_annotation(db, user.id, aid)
    if body.body is not None:
        note.content = body.body
    if body.links is not None:
        note.links = await _validate_links(db, user.id, aid, body.links)
    await db.commit()
    await db.refresh(note)
    counts = await _backlink_counts(db, user.id, [note.id])
    return _annotation_out(note, counts)


@router.delete("/annotations/{aid}")
async def delete_annotation(
    aid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """删批注（本人）；同时摘除本人其他批注指向它的出链（边随节点删）。"""
    note = await _get_annotation(db, user.id, aid)
    await db.delete(note)
    refs = (
        await db.execute(
            select(PaperNote).where(
                PaperNote.user_id == user.id,
                PaperNote.id != aid,
                PaperNote.links.contains([aid]),
            )
        )
    ).scalars().all()
    for other in refs:
        other.links = [x for x in (other.links or []) if x != aid]
    await db.commit()
    return {"ok": True}


@router.get("/annotations/{aid}/backlinks", response_model=list[AnnotationOut])
async def annotation_backlinks(
    aid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """反向链接（知识网半侧）：哪些我的批注链向了 aid（Obsidian backlinks 面板）。"""
    note = await _get_annotation(db, user.id, aid)
    rows = (
        await db.execute(
            select(PaperNote)
            .where(
                PaperNote.user_id == user.id,
                PaperNote.note_kind == "annotation",
                PaperNote.links.contains([aid]),
            )
            .order_by(PaperNote.id)
        )
    ).scalars().all()
    counts = await _backlink_counts(db, user.id, [n.id for n in rows] + [note.id])
    return [_annotation_out(n, counts) for n in rows]
