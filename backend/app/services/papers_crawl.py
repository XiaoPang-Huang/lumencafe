"""文献抓取执行体（论文域步 A 改造：多源 × 按用户订阅聚合；步 B：runs 记录 + 手动触发）。

流程（步 A 拍板）：对每个有文献权限（app:papers）的用户——
按其勾选的订阅源（user_settings.subscribe_sources，未配置回落默认三源）×
其订阅关键词（subscribe_keywords，未配置回落 env 默认）逐源抓取（SourceProvider
契约，sources/ 目录）→ 轮内按 doi/arxiv_id/external_id 去重 →
打标（tag_paper 不动，TAG_RULES 沿用）→ papers 幂等 upsert → paper_users 归属。

轮①（拍板 P23 用户世界隔离，Alembic 0011）：papers 行级归属 user_id，
去重键 = (user_id, pmid)（同用户内去重；同一篇两人抓各存一份，删除互不影响）；
doi 补查同样限同用户内。存量行回填口径 = 最早 paper_users 归属人，无归属归
admin（见迁移 0011 docstring）。

步 B 增量：
- 每轮结束写 papers_crawl_runs 一行（成功/失败都写；trigger=schedule|manual），
  stats 带 per_source 各源命中/新增数；
- run_manual_crawl 供「立即检索」：进程内 asyncio 锁防并发，force=True 跳过
  Q11 同日幂等（用户显式要求跑一轮），成功后不写当日标记（schedule 幂等照旧）；
- match_keywords 抽出为 tag_paper 与 digest 共用的命中口径（大小写不敏感子串）。

PubMed 的 esearch/efetch/XML 解析已收编至 app/services/sources/pubmed.py
（逻辑搬家不改语义）；中译回填沿用网关默认路由（单轮 ≤20 篇、篇间 ≥1s）。

网络层（步 2 工程三小件，D10）：外部调用走共享 httpx 总机（http_client.py，各
provider 内部取）；瞬时错误由各源 tenacity 重试收口（retry.py），4xx 不重试；
源间 polite sleep 是限速纪律（NCBI ≤3 req/s 等），不是重试。

同日去重双保险（Q11）：进程内日期标记 + papers 表当日已有记录。
"""
import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.papers import Paper, PaperCrawlRun, PaperFavorite, PaperNote, PaperUser
from app.models.user import Permission, RolePermission, User, UserRole
from app.models.user_settings import UserSetting
from app.services import llm_gateway, route_service
from app.services.sources import DEFAULT_SOURCES, PaperItem, get_provider
from app.services.sources.keys import fetch_service_api_key
from app.services.sources.pubmed import RATE_LIMIT_SLEEP  # NCBI polite 限速复用为源间隔

logger = logging.getLogger("lumencafe.papers")

TRANSLATE_MAX_PER_ROUND = 20  # 中译单轮 ≤20 篇（PRD 4.8）
TRANSLATE_INTERVAL = 1.0  # 中译篇间 ≥1s（PRD 4.8）
HIGH_RELEVANCE_MIN_KEYWORDS = 2  # digest 高相关阈值：命中订阅关键词数 ≥2（先简单后精细）

# ── papers_prefs 展示/抓取偏好缺省（P18 展示项 + P21 抓取期过滤参数） ──
PAPERS_PREFS_DEFAULTS: dict = {
    "display_limit": 50,
    "sort": "time",
    "if_min": None,  # 影响因子下限（null = 不限；展示过滤与抓取过滤共用）
    "year_from": None,  # P21：抓取起始年（null = 不限，回落 papers_days_back 窗口）
    "year_to": None,  # P21：抓取截止年（null = 不限）
    "authors": [],  # P21：作者限定（逗号分隔多值存数组；任一作者命中即过）
    "auto_translate": False,  # 轮③ P27：解析完成后自动触发中英对照翻译（默认关）
}
SORT_MODES: tuple[str, ...] = ("time", "if", "score")


def parse_papers_prefs(value: object) -> dict:
    """解析 user_settings.papers_prefs 的 value：逐项容错回落缺省，不整单丢弃。

    展示项（display_limit/sort）与 P21 抓取期过滤项（year_from/year_to/authors/if_min）
    同存一份 papers_prefs（拍板 P21：参数随订阅配置管理，存取走现有 prefs 通道）。
    """
    prefs = dict(PAPERS_PREFS_DEFAULTS)
    if not isinstance(value, dict):
        return prefs
    try:
        limit = int(value.get("display_limit") or prefs["display_limit"])
        prefs["display_limit"] = min(max(limit, 1), 500)
    except (TypeError, ValueError):
        pass
    if value.get("sort") in SORT_MODES:
        prefs["sort"] = value["sort"]
    try:
        if_min = value.get("if_min")
        prefs["if_min"] = float(if_min) if if_min is not None else None
    except (TypeError, ValueError):
        prefs["if_min"] = None
    for key in ("year_from", "year_to"):
        try:
            raw = value.get(key)
            prefs[key] = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            prefs[key] = None
    authors = value.get("authors")
    if isinstance(authors, (list, tuple)):
        prefs["authors"] = [str(a).strip() for a in authors if str(a).strip()]
    prefs["auto_translate"] = bool(value.get("auto_translate"))  # 轮③ P27：默认关
    return prefs

# 打标规则：标签 -> 命中词列表（大小写不敏感，可多命中；沿用旧版）
TAG_RULES: dict[str, list[str]] = {
    "AD": ["alzheimer", "dementia"],
    "PD": ["parkinson"],
    "ALS": ["als", "amyotrophic"],
    "scale": ["mmse", "moca", "updrs", "hoehn-yahr", "cdr", "mini-mental", "montreal cognitive"],
}

TRANSLATE_PROMPT = (
    "你是医学文献翻译助手。把下面的论文摘要翻译成通顺的中文，"
    "保留专业术语（可附英文原词），不要添加原文没有的内容，直接输出译文。"
    "\n\n标题：{title}\n\n摘要：{abstract}"
)

# 进程内当日执行标记（日期戳；重启不重复抓取，Q11 第一重）
_last_run_date: str | None = None


def _today_str() -> str:
    """业务「今天」= 本地时区（容器 TZ=Asia/Shanghai），全模块统一口径。"""
    return datetime.now().astimezone().date().isoformat()


def already_ran_today() -> bool:
    return _last_run_date == _today_str()


def mark_ran_today() -> None:
    global _last_run_date
    _last_run_date = _today_str()


def match_keywords(title: str, abstract: str, keywords: list[str]) -> list[str]:
    """按关键词列表在标题+摘要中做大小写不敏感子串匹配，返回命中的关键词（保序去重）。

    tag_paper（抓取打标）与 digest（页内命中）共用的命中口径，保证两处一致。
    """
    text = f"{title}\n{abstract}".lower()
    hits: list[str] = []
    for kw in keywords:
        needle = str(kw).strip().lower()
        if needle and needle in text and kw not in hits:
            hits.append(kw)
    return hits


def tag_paper(title: str, abstract: str) -> tuple[list[str], list[str]]:
    """按规则打标签：标题+摘要大小写不敏感匹配，可多命中；返回 (标签, 命中词)。"""
    tags: list[str] = []
    hit_words: list[str] = []
    for tag, words in TAG_RULES.items():
        matched = match_keywords(title, abstract, words)
        if matched:
            tags.append(tag)
            hit_words.extend(matched)
    return tags, hit_words


class CrawlAlreadyRunning(Exception):
    """「立即检索」并发护栏：已有抓取轮次进行中。"""


# ── 按用户订阅聚合 ────────────────────────────────────────
@dataclass(frozen=True)
class UserSubscription:
    """一个用户的抓取计划：勾选源 × 订阅关键词 × P21 抓取期过滤参数。"""

    user_id: int
    keywords: tuple[str, ...]
    sources: tuple[str, ...]
    year_from: int | None = None  # P21：起始年（None = 不限）
    year_to: int | None = None  # P21：截止年（None = 不限）
    authors: tuple[str, ...] = ()  # P21：作者限定（任一命中即过）
    if_min: float | None = None  # P21：影响因子下限（None = 不限）


async def _papers_permission_user_ids(db: AsyncSession) -> list[int]:
    """有文献权限（app:papers，经角色绑定）的启用用户（步 A：抓取按有权限用户聚合）。"""
    stmt = (
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            Permission.code == "app:papers",
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())


async def collect_subscriptions(db: AsyncSession) -> list[UserSubscription]:
    """每个有文献权限用户的 (关键词, 源, P21 过滤参数) 计划。

    关键词：user_settings.subscribe_keywords.value.keywords，未配置回落 env 默认
    （papers_default_keywords）；关键词为空的用户本轮跳过（与旧版语义一致）。
    源：user_settings.subscribe_sources.value.sources，未配置回落默认三源
    （sources.DEFAULT_SOURCES，见注册表 docstring）。
    P21 过滤参数：user_settings.papers_prefs（与展示偏好同一份，拍板 P21），
    逐项容错解析（parse_papers_prefs），未配置/非法 = 全不限。
    """
    user_ids = await _papers_permission_user_ids(db)
    if not user_ids:
        return []

    rows = (
        await db.execute(select(UserSetting).where(UserSetting.key.in_(
            ["subscribe_keywords", "subscribe_sources", "papers_prefs"]
        )))
    ).scalars().all()
    keywords_by_user: dict[int, list[str]] = {}
    sources_by_user: dict[int, list[str]] = {}
    prefs_by_user: dict[int, dict] = {}
    for row in rows:
        if row.key == "subscribe_keywords":
            kws = [str(k).strip() for k in (row.value or {}).get("keywords", []) if str(k).strip()]
            if kws:
                keywords_by_user[row.user_id] = kws
        elif row.key == "subscribe_sources":
            srcs = [str(s).strip() for s in (row.value or {}).get("sources", []) if str(s).strip()]
            if srcs:
                sources_by_user[row.user_id] = srcs
        elif row.key == "papers_prefs":
            prefs_by_user[row.user_id] = parse_papers_prefs(row.value)

    defaults = [k.strip() for k in (settings.papers_default_keywords or "").split(",") if k.strip()]

    subs: list[UserSubscription] = []
    for uid in user_ids:
        kws = keywords_by_user.get(uid) or defaults
        if not kws:
            continue  # 无有效关键词：本轮不为其抓取（不回落别人配置的源）
        srcs = sources_by_user.get(uid) or list(DEFAULT_SOURCES)
        prefs = prefs_by_user.get(uid) or PAPERS_PREFS_DEFAULTS
        subs.append(
            UserSubscription(
                user_id=uid,
                keywords=tuple(kws),
                sources=tuple(srcs),
                year_from=prefs["year_from"],
                year_to=prefs["year_to"],
                authors=tuple(prefs["authors"]),
                if_min=prefs["if_min"],
            )
        )
    return subs


async def resolve_user_keywords(db: AsyncSession, user_id: int) -> list[str]:
    """单个用户的订阅关键词：user_settings.subscribe_keywords 优先，回落 env 默认。

    与 collect_subscriptions 同一口径（digest 按用户当前关键词重算命中用）。
    """
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id, UserSetting.key == "subscribe_keywords"
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        kws = [str(k).strip() for k in (row.value or {}).get("keywords", []) if str(k).strip()]
        if kws:
            return kws
    return [k.strip() for k in (settings.papers_default_keywords or "").split(",") if k.strip()]


# ── 入库 ────────────────────────────────────────────────
def external_key(item: PaperItem) -> str:
    """papers.pmid 列承载的全局去重键：PubMed 纯数字 pmid，其余 "{source}:{external_id}"。"""
    return item.external_id if item.source == "pubmed" else f"{item.source}:{item.external_id}"


async def _find_existing_paper_id(
    db: AsyncSession, item: PaperItem, user_id: int
) -> int | None:
    """跨源去重查找（限同用户内，拍板 P23）：先按去重键（pmid 列），再按 doi。"""
    key = external_key(item)
    pid = (
        await db.execute(
            select(Paper.id).where(Paper.user_id == user_id, Paper.pmid == key)
        )
    ).scalar_one_or_none()
    if pid is not None:
        return pid
    if item.doi:
        pid = (
            await db.execute(
                select(Paper.id).where(
                    Paper.user_id == user_id, Paper.doi == item.doi.lower()
                )
            )
        ).scalar_one_or_none()
        if pid is not None:
            return pid
    return None


# 已存在行允许刷新的元数据列（P15：跨源重复命中时补全/更新题录元数据；
# title/abstract/abstract_zh/tags/keywords 不在其列——不覆盖既有正文与中译）
_METADATA_REFRESH_COLS = ("doi", "journal", "authors", "pub_date", "cited_count", "if_approx", "url")


def _metadata_values(item: PaperItem) -> dict:
    """PaperItem → 可刷新元数据列的值字典（pub_date 由 year 兜底）。"""
    return {
        "doi": item.doi.lower() if item.doi else None,
        "journal": item.journal,
        "authors": list(item.authors),
        "pub_date": item.pub_date or (date(item.year, 1, 1) if item.year else None),
        "cited_count": item.cited_count,
        "if_approx": item.if_approx,
        "url": item.url or "",  # P16：原文落地页/OA 直链（下载优先直链）
    }


async def _refresh_metadata(db: AsyncSession, paper_id: int, item: PaperItem) -> None:
    """对已存在行刷新元数据列（P15，空值不回填：源没有就不覆盖已有值）。"""
    values = {k: v for k, v in _metadata_values(item).items() if v not in (None, "", [])}
    if values:
        await db.execute(update(Paper).where(Paper.id == paper_id).values(**values))


async def _upsert_item(
    db: AsyncSession, item: PaperItem, tags: list[str], hits: list[str], user_id: int
) -> tuple[int, bool]:
    """单篇入库：同用户内跨源去重后 papers 幂等 upsert；返回 (paper_id, 是否新插入)。

    同一篇被多源命中时（doi/arxiv 相同），第二轮起只补归属不重复建行；命中已存在
    行时刷新元数据列（P15，空值不回填）。真正并发撞车由 (user_id, pmid) 唯一
    索引 + ON CONFLICT DO UPDATE（仅元数据列，语义同上）兜底。拍板 P23：去重与
    upsert 全部限同 user 内，他人世界里的同键行不参与。
    """
    key = external_key(item)
    existing = await _find_existing_paper_id(db, item, user_id)
    if existing is not None:
        await _refresh_metadata(db, existing, item)
        return existing, False
    stmt = (
        pg_insert(Paper)
        .values(
            pmid=key,
            user_id=user_id,
            origin="crawl",
            source=item.source or "unknown",
            title=item.title,
            abstract=item.abstract,
            tags=tags,
            keywords=hits,
            **_metadata_values(item),
        )
        .on_conflict_do_update(
            index_elements=["user_id", "pmid"],
            set_={col: getattr(pg_insert(Paper).excluded, col) for col in _METADATA_REFRESH_COLS},
        )
    )
    await db.execute(stmt)
    paper_id = (
        await db.execute(
            select(Paper.id).where(Paper.user_id == user_id, Paper.pmid == key)
        )
    ).scalar_one()
    return paper_id, True


async def _attribute_paper(db: AsyncSession, paper_id: int, user_ids: list[int]) -> None:
    """归属记录幂等写入（ON CONFLICT DO NOTHING）。"""
    for uid in set(user_ids):
        await db.execute(
            pg_insert(PaperUser)
            .values(paper_id=paper_id, user_id=uid)
            .on_conflict_do_nothing(index_elements=["paper_id", "user_id"])
        )


async def _papers_created_today(db: AsyncSession) -> bool:
    """Q11 第二重去重：papers 表当日已有抓取记录即视为已执行。

    日期口径 = 本地（容器 TZ=Asia/Shanghai，与 PG 会话时区一致；digest 今日口径
    同为本地零点）：created_at 经 func.date 按会话时区取日期，与本地今天比较。
    """
    count = (
        await db.execute(
            select(func.count(Paper.id)).where(
                func.date(Paper.created_at) == datetime.now().astimezone().date()
            )
        )
    ).scalar_one()
    return count > 0


async def _backfill_translations(db: AsyncSession) -> int:
    """LLM 中译回填：abstract_zh 为空的最多 20 篇，篇间 ≥1s；失败跳过不阻塞。"""
    route = await route_service.resolve_default(db)
    if route is None:
        logger.warning("未配置默认路由，跳过中译回填")
        return 0
    pending = (
        await db.execute(
            select(Paper).where(Paper.abstract_zh == "").limit(TRANSLATE_MAX_PER_ROUND)
        )
    ).scalars().all()
    done = 0
    for idx, paper in enumerate(pending):
        if idx > 0:
            await asyncio.sleep(TRANSLATE_INTERVAL)  # 中译篇间 ≥1s
        if not paper.abstract:
            continue
        try:
            zh = await llm_gateway.chat_once(
                route.cfg,
                [
                    {"role": "system", "content": "你是医学文献翻译助手，直接输出译文。"},
                    {
                        "role": "user",
                        "content": TRANSLATE_PROMPT.format(
                            title=paper.title, abstract=paper.abstract[:6000]
                        ),
                    },
                ],
                timeout=60.0,
            )
        except llm_gateway.UpstreamError as exc:
            logger.warning("文献 %s 中译失败，跳过：%s", paper.pmid, exc)
            continue
        if zh and zh.strip():
            paper.abstract_zh = zh.strip()
            done += 1
    if done:
        await db.commit()
    return done


# ── P21 抓取期过滤 ──────────────────────────────────────
def _sub_since_date(sub: UserSubscription, base_since: date) -> date:
    """起始口径：P21 year_from 与全局回溯窗口取更晚者（年份起点折算 1 月 1 日）。"""
    if sub.year_from is None:
        return base_since
    return max(base_since, date(sub.year_from, 1, 1))


def _sub_until_date(sub: UserSubscription) -> date | None:
    """截止口径：year_to 折算 12 月 31 日；未配置返回 None（源端不过滤，管线也不后过滤）。"""
    return date(sub.year_to, 12, 31) if sub.year_to is not None else None


def _apply_crawl_filters(items: list[PaperItem], sub: UserSubscription) -> list[PaperItem]:
    """P21 抓取期后过滤：作者限定 + IF 下限（年份区间由 since/until 与各源过滤兜住）。

    - authors：条目作者字段（大小写不敏感子串）命中任一限定作者即过；空 = 不过滤；
    - if_min：近似 IF 非空且 ≥ 下限才过；if_approx 为 null 的条目在下限有值时排除；
    - 日期条目缺失（pub_date/year 皆空）时年份后过滤保守保留（与源端过滤口径一致）。
    """
    out: list[PaperItem] = []
    needles = [a.lower() for a in sub.authors if a.strip()]
    for item in items:
        if needles:
            haystack = [a.lower() for a in item.authors]
            if not any(any(n in a for a in haystack) for n in needles):
                continue
        if sub.if_min is not None and (
            item.if_approx is None or item.if_approx < sub.if_min
        ):
            continue
        if sub.year_to is not None:
            item_year = item.pub_date.year if item.pub_date else item.year
            if item_year is not None and item_year > sub.year_to:
                continue
        out.append(item)
    return out


# ── 轮次执行与 runs 记录（步 B） ──────────────────────────
# 「立即检索」并发护栏：进程内 asyncio 锁，同一时刻只允许一轮抓取
# （每日轮 / 手动轮 / P13 语义检索共用同一把锁）。
_crawl_lock = asyncio.Lock()


async def _write_run(
    db: AsyncSession,
    trigger: str,
    stats: dict,
    status: str,
    error: str | None = None,
    run_at: datetime | None = None,
    progress: dict | None = None,
) -> PaperCrawlRun:
    """写一行抓取轮次记录并提交；返回 run 行（含 ORM 生成的自增 id）。

    run_at 显式传轮次发起时刻（_execute_round 捕获）：该轮入库的论文 created_at
    均 ≥ run_at，digest「自最近一轮检索以来」窗口才能把本轮命中算进来；
    不传则回落数据库 now()（兼容直接调用方）。progress（轮② P26）随写入持久化。
    """
    run = PaperCrawlRun(
        trigger=trigger, stats=stats, status=status, error=error, progress=progress
    )
    if run_at is not None:
        run.run_at = run_at
    db.add(run)
    await db.commit()
    return run


def _initial_progress(total_keywords: int) -> dict:
    """轮②（P26）检索进度条初始形态：阶段 fetching + 关键词计数 + 各源计数。"""
    return {
        "phase": "fetching",  # fetching | translating | done
        "current_keyword": "",  # 当前检索批次标签（源 · 关键词组）
        "done_keywords": 0,  # 已完成检索的关键词计数（源×关键词 维度累计）
        "total_keywords": total_keywords,  # 全轮关键词总量（源×关键词）
        "per_source": {},  # {源: {"fetched": n, "added": n}}，与 stats 同一份字典
    }


async def _update_run(
    db: AsyncSession,
    run: PaperCrawlRun,
    *,
    stats: dict | None = None,
    progress: dict | None = None,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """轮内更新同一 runs 行（P26：进度条轮询数据源）；独立短事务提交。

    expire_on_commit 下提交后 ORM 属性过期，下次访问自动 refresh——
    同一会话内反复 update 安全。
    """
    if stats is not None:
        run.stats = stats
    if progress is not None:
        run.progress = progress
    if status is not None:
        run.status = status
    if error is not None:
        run.error = error
    await db.commit()


async def _execute_round(db: AsyncSession, trigger: str, force: bool) -> PaperCrawlRun | None:
    """执行一轮抓取并写 runs 表（成功/失败都写）；被 Q11 幂等跳过时返回 None。

    force=True（手动「立即检索」）：跳过同日幂等，跑完整一轮；不写进程内当日标记
    （schedule 的幂等语义不受手动轮影响，表内当日记录仍是第二重保险）。

    轮②（P26）：runs 行**轮始 insert**（status=running + progress 初始形态），
    轮内逐源 update 同一行（progress.per_source / done_keywords / current_keyword），
    轮末置 success + phase=done；中译回填阶段 phase=translating。
    失败时 rollback 只回滚当前未提交事务（runs 行此前已独立提交、仍然存活），
    故 failed 态**原位 update 同一行**（ORM 对象过期后赋值即触发 refresh）。
    """
    started_at = datetime.now(UTC)  # 轮次发起时刻：digest 窗口锚点（见 _write_run）
    if not force:
        if already_ran_today():
            return None
        if await _papers_created_today(db):
            mark_ran_today()  # 双保险：表内已有当日记录
            return None

    subs = await collect_subscriptions(db)
    stats: dict = {"per_source": {}, "users": len(subs), "fetched": 0, "added": 0}
    total_keywords = sum(len(sub.keywords) * len(sub.sources) for sub in subs)
    progress = _initial_progress(total_keywords)
    progress["per_source"] = stats["per_source"]  # 与 stats 共享同一字典，源计数自动可见
    if not subs:
        logger.info("无可抓取用户（无文献权限或无有效订阅关键词），本轮跳过")
        if not force:
            mark_ran_today()
        progress["phase"] = "done"
        return await _write_run(
            db, trigger, stats, "success", run_at=started_at, progress=progress
        )

    # 轮始 insert runs 行：检索进度条（P26）从此刻可轮询到本行
    run = await _write_run(
        db, trigger, stats, "running", run_at=started_at, progress=progress
    )
    since_date = datetime.now(UTC).date() - timedelta(days=settings.papers_days_back)
    added = 0

    async def _report(source_name: str, done_keywords: int) -> None:
        """每源完成推进进度：关键词计数 + 当前批次标签，落库供轮询。"""
        progress["done_keywords"] += done_keywords
        first_kw = subs_keywords_first()
        progress["current_keyword"] = f"{source_name} · {first_kw}"
        await _update_run(db, run, stats=stats, progress=progress)

    # 关键词标签取当前订阅批次的首词（展示口径：源 · 关键词组）
    def subs_keywords_first() -> str:
        kws = [k for sub in subs if sub.keywords for k in sub.keywords]
        return (kws[0] + f" 等 {len(kws)} 词") if kws else ""

    try:
        for sub in subs:
            added += await _crawl_subscription(
                db, sub, stats, since_date, progress_reporter=_report
            )
        if not force:
            mark_ran_today()
        progress["phase"] = "translating"
        progress["current_keyword"] = ""
        await _update_run(db, run, stats=stats, progress=progress)
        translated = await _backfill_translations(db)
        if translated:
            logger.info("中译回填 %d 篇", translated)
        stats["translated"] = translated
        stats["added"] = added
        progress["phase"] = "done"
        await _update_run(db, run, stats=stats, progress=progress, status="success")
        return run
    except Exception as exc:
        await db.rollback()  # 复位未提交的入库半成品；runs 行此前已提交，原位更新
        logger.exception("抓取轮次失败（trigger=%s）", trigger)
        await _update_run(
            db, run, stats=stats, progress=progress,
            status="failed", error=str(exc)[:1000],
        )
        return run


async def _crawl_subscription(
    db: AsyncSession,
    sub: UserSubscription,
    stats: dict,
    base_since: date,
    progress_reporter: "object | None" = None,
) -> int:
    """按单用户订阅计划逐源抓取并入库；返回本轮新入库篇数。

    key 认证升级：provider.key_service 非空时从 service_keys 取匙注入（取不到 =
    匿名态）；P21：since/until 按用户年份参数折算传源，authors/if_min 后过滤。
    供 _execute_round（每日/手动轮）与 run_semantic_search（P13 语义检索）共用。
    progress_reporter（轮② P26 可选）：每源完成时回调
    ``await progress_reporter(源名, 该源关键词数)`` 推进 runs.progress。
    """
    added = 0
    since = _sub_since_date(sub, base_since)
    until = _sub_until_date(sub)
    for source_name in sub.sources:
        provider = get_provider(source_name)
        if provider is None:
            logger.warning("用户 %d 勾选了未注册源 %s，跳过", sub.user_id, source_name)
            continue
        api_key = None
        key_service = getattr(provider, "key_service", None)
        if key_service:
            api_key = await fetch_service_api_key(db, key_service)
        try:
            # 契约可选参数按实现签名探测注入：老版两参实现（含测试替身）零改动兼容，
            # 新实现接收 until_date（P21）与 api_key（key 认证升级）
            params = inspect.signature(provider.search).parameters
            call_kwargs: dict = {}
            if "until_date" in params:
                call_kwargs["until_date"] = until
            if "api_key" in params:
                call_kwargs["api_key"] = api_key
            items = await provider.search(list(sub.keywords), since, **call_kwargs)
        except httpx.HTTPError as exc:
            logger.warning("源 %s 抓取失败（用户 %d）：%s", source_name, sub.user_id, exc)
            if progress_reporter is not None:
                await progress_reporter(source_name, len(sub.keywords))
            continue
        await asyncio.sleep(RATE_LIMIT_SLEEP)  # 源间 polite 限速（非重试）
        items = _apply_crawl_filters(items, sub)
        src_stats = stats["per_source"].setdefault(source_name, {"fetched": 0, "added": 0})
        src_stats["fetched"] += len(items)
        stats["fetched"] += len(items)
        seen_keys: set[str] = set()
        for item in items:
            keys = [k for k in item.dedupe_keys if k]
            if any(k in seen_keys for k in keys):
                continue  # 轮内跨源去重：doi > arxiv_id > external_id
            seen_keys.update(keys)
            tags, hits = tag_paper(item.title, item.abstract)
            paper_id, is_new = await _upsert_item(db, item, tags, hits, sub.user_id)
            await _attribute_paper(db, paper_id, [sub.user_id])
            if is_new:
                added += 1
                src_stats["added"] += 1
        await db.commit()
        logger.info("用户 %d 源 %s 入库完成（累计新增 %d）", sub.user_id, source_name, added)
        if progress_reporter is not None:
            await progress_reporter(source_name, len(sub.keywords))
    return added


async def run_daily_crawl(db: AsyncSession, trigger: str = "schedule") -> int:
    """执行一轮文献抓取（Q11 同日幂等），写 runs 表，返回本轮新入库文献数。

    PRD 4.8 {added: n} 的 n；被幂等跳过时返回 0 且不写 runs（本轮未执行）。
    Hatchet cron 与 /internal/jobs/papers-crawl 共用本函数。
    """
    run = await _execute_round(db, trigger=trigger, force=False)
    return run.stats.get("added", 0) if run is not None else 0


async def run_manual_crawl(db: AsyncSession) -> dict:
    """「立即检索」：force 跑一轮抓取，返回 {added, runs_id, per_source}。

    进程内 asyncio 锁防并发：已有轮次进行中抛 CrawlAlreadyRunning（路由转 409）。
    """
    if _crawl_lock.locked():
        raise CrawlAlreadyRunning()
    async with _crawl_lock:
        run = await _execute_round(db, trigger="manual", force=True)
    assert run is not None  # force=True 不会被幂等跳过
    return {
        "added": run.stats.get("added", 0),
        "runs_id": run.id,
        "per_source": {
            source: counts["fetched"] for source, counts in run.stats["per_source"].items()
        },
    }


# ── P13 本期：自然语言检索（大白话 → AI 扩词 → 临时聚合抓取） ──
async def _user_subscription_for(db: AsyncSession, user_id: int, keywords: list[str]) -> UserSubscription | None:
    """组装单用户临时抓取计划：语义扩词替换订阅词，源/P21 参数沿用该用户配置。"""
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id, UserSetting.key == "subscribe_sources"
            )
        )
    ).scalar_one_or_none()
    srcs = [str(s).strip() for s in (row.value or {}).get("sources", []) if str(s).strip()] if row else []
    prefs_row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id, UserSetting.key == "papers_prefs"
            )
        )
    ).scalar_one_or_none()
    prefs = parse_papers_prefs(prefs_row.value) if prefs_row is not None else PAPERS_PREFS_DEFAULTS
    return UserSubscription(
        user_id=user_id,
        keywords=tuple(keywords),
        sources=tuple(srcs) if srcs else tuple(DEFAULT_SOURCES),
        year_from=prefs["year_from"],
        year_to=prefs["year_to"],
        authors=tuple(prefs["authors"]),
        if_min=prefs["if_min"],
    )


async def run_semantic_search(db: AsyncSession, user_id: int, keywords: list[str]) -> dict:
    """P13 本期：按语义扩词结果临时跑一轮单用户聚合抓取。

    - 复用 _crawl_subscription（与每日/手动轮同一入库管线：去重、打标、幂等 upsert、
      归属），但**不写订阅词**——keywords 仅本轮使用，subscribe_keywords 保持原样；
    - 源勾选与 P21 抓取参数沿用该用户配置（papers_prefs），与订阅抓取同口径；
    - 写 runs(trigger=semantic)：digest「最近一轮成功检索」窗口随之刷新，页内立即可见；
    - 与每日/手动轮共用 _crawl_lock：并发冲突抛 CrawlAlreadyRunning（路由转 409）。
    """
    if not keywords:
        return {"added": 0, "runs_id": None, "per_source": {}}
    if _crawl_lock.locked():
        raise CrawlAlreadyRunning()
    async with _crawl_lock:
        sub = await _user_subscription_for(db, user_id, keywords)
        started_at = datetime.now(UTC)
        stats: dict = {"per_source": {}, "users": 1, "fetched": 0, "added": 0}
        base_since = datetime.now(UTC).date() - timedelta(days=settings.papers_days_back)
        try:
            added = await _crawl_subscription(db, sub, stats, base_since)
            stats["added"] = added
            run = await _write_run(db, "semantic", stats, "success", run_at=started_at)
        except Exception as exc:
            await db.rollback()
            logger.exception("语义检索轮次失败（用户 %d）", user_id)
            run = await _write_run(
                db, "semantic", stats, "failed", error=str(exc)[:1000], run_at=started_at
            )
            return {
                "added": 0,
                "runs_id": run.id,
                "per_source": {},
            }
    return {
        "added": stats["added"],
        "runs_id": run.id,
        "per_source": {
            source: counts["fetched"] for source, counts in stats["per_source"].items()
        },
    }


# ── 7 天滚动清理（P14）：每日检索后清「未收藏且无笔记且入库 ≥7 天」的论文 ──
# 幂等口径同 digest 先例：进程内日期标记（Hatchet cron 每日一次，重启不重复清理）。
_last_cleanup_date: str | None = None


def cleanup_already_ran_today() -> bool:
    return _last_cleanup_date == _today_str()


def mark_cleanup_ran_today() -> None:
    global _last_cleanup_date
    _last_cleanup_date = _today_str()


async def cleanup_stale_papers(db: AsyncSession, now: datetime | None = None) -> dict:
    """删除「未收藏、无笔记、入库 ≥ settings.papers_retention_days 天」的论文。

    - 保护口径（P14）：paper_favorites / paper_notes 任一表有行即永久保留（跨用户：
      任何一人收藏/笔记都保护该篇）；今日 digest 展示的论文入库不足 7 天天然不在
      清理窗口内；
    - 连带删除 paper_users 归属（显式删 + FK ondelete CASCADE 双保险；COS 产物
      本批未落地，只清表）；
    - 返回 {"deleted": n, "cutoff": iso}；now 可注入便于测试时间边界。
    """
    ref = now or datetime.now(UTC)
    cutoff = ref - timedelta(days=settings.papers_retention_days)
    stale_ids = (
        await db.execute(
            select(Paper.id)
            .where(Paper.created_at <= cutoff)
            .where(Paper.id.not_in(select(PaperFavorite.paper_id)))
            .where(Paper.id.not_in(select(PaperNote.paper_id)))
        )
    ).scalars().all()
    deleted = 0
    if stale_ids:
        await db.execute(delete(PaperUser).where(PaperUser.paper_id.in_(stale_ids)))
        result = await db.execute(delete(Paper).where(Paper.id.in_(stale_ids)))
        deleted = result.rowcount or 0
        await db.commit()
        logger.info(
            "7 天滚动清理：删除 %d 篇（入库早于 %s，未收藏且无笔记）", deleted, cutoff.date()
        )
    else:
        await db.commit()  # 无删除也复位事务，保持会话可用
    return {"deleted": deleted, "cutoff": cutoff.date().isoformat()}


async def run_daily_cleanup(db: AsyncSession) -> dict:
    """Hatchet cron / internal 触发的每日清理：幂等（同日跳过）后执行并写日志。"""
    if cleanup_already_ran_today():
        logger.info("papers-daily-cleanup 今日已执行，跳过（幂等）")
        return {"deleted": 0, "skipped": True}
    result = await cleanup_stale_papers(db)
    mark_cleanup_ran_today()
    return {**result, "skipped": False}
