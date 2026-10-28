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
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.papers import (
    Paper,
    PaperCrawlRun,
    PaperExplanation,
    PaperFavorite,
    PaperNote,
    PaperUser,
)
from app.models.user import User
from app.models.user_settings import UserSetting
from app.schemas.papers import (
    CrawlNowResponse,
    DigestItemOut,
    DigestOut,
    ExplainResponse,
    NoteRequest,
    PaperDetailOut,
    PaperOut,
    SaveResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    SourceOut,
    SuggestKeywordsRequest,
    SuggestKeywordsResponse,
)
from app.services import llm_gateway, papers_crawl, route_service
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


@router.get("/{pid}", response_model=PaperDetailOut)
async def paper_detail(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    paper = await _get_mine(db, user.id, pid)
    note = (
        await db.execute(
            select(PaperNote).where(PaperNote.user_id == user.id, PaperNote.paper_id == pid)
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
    """笔记 upsert：每人每篇一条，覆盖更新。"""
    await _get_mine(db, user.id, pid)
    stmt = (
        pg_insert(PaperNote)
        .values(paper_id=pid, user_id=user.id, content=body.content)
        .on_conflict_do_update(
            index_elements=["paper_id", "user_id"],
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
