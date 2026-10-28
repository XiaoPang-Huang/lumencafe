"""文献抓取执行体（论文域步 A 改造：多源 × 按用户订阅聚合；步 B：runs 记录 + 手动触发）。

流程（步 A 拍板）：对每个有文献权限（app:papers）的用户——
按其勾选的订阅源（user_settings.subscribe_sources，未配置回落默认三源）×
其订阅关键词（subscribe_keywords，未配置回落 env 默认）逐源抓取（SourceProvider
契约，sources/ 目录）→ 轮内按 doi/arxiv_id/external_id 去重 →
打标（tag_paper 不动，TAG_RULES 沿用）→ papers 幂等 upsert（pmid 列 = 全局
去重键；doi 命中既有行则只补归属，跨源同一篇不重复入库）→ paper_users 归属。

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
from app.services.sources.pubmed import RATE_LIMIT_SLEEP  # NCBI polite 限速复用为源间隔

logger = logging.getLogger("lumencafe.papers")

TRANSLATE_MAX_PER_ROUND = 20  # 中译单轮 ≤20 篇（PRD 4.8）
TRANSLATE_INTERVAL = 1.0  # 中译篇间 ≥1s（PRD 4.8）
HIGH_RELEVANCE_MIN_KEYWORDS = 2  # digest 高相关阈值：命中订阅关键词数 ≥2（先简单后精细）

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
    """一个用户的抓取计划：勾选源 × 订阅关键词。"""

    user_id: int
    keywords: tuple[str, ...]
    sources: tuple[str, ...]


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
    """每个有文献权限用户的 (关键词, 源) 计划。

    关键词：user_settings.subscribe_keywords.value.keywords，未配置回落 env 默认
    （papers_default_keywords）；关键词为空的用户本轮跳过（与旧版语义一致）。
    源：user_settings.subscribe_sources.value.sources，未配置回落默认三源
    （sources.DEFAULT_SOURCES，见注册表 docstring）。
    """
    user_ids = await _papers_permission_user_ids(db)
    if not user_ids:
        return []

    rows = (
        await db.execute(select(UserSetting).where(UserSetting.key.in_(
            ["subscribe_keywords", "subscribe_sources"]
        )))
    ).scalars().all()
    keywords_by_user: dict[int, list[str]] = {}
    sources_by_user: dict[int, list[str]] = {}
    for row in rows:
        if row.key == "subscribe_keywords":
            kws = [str(k).strip() for k in (row.value or {}).get("keywords", []) if str(k).strip()]
            if kws:
                keywords_by_user[row.user_id] = kws
        elif row.key == "subscribe_sources":
            srcs = [str(s).strip() for s in (row.value or {}).get("sources", []) if str(s).strip()]
            if srcs:
                sources_by_user[row.user_id] = srcs

    defaults = [k.strip() for k in (settings.papers_default_keywords or "").split(",") if k.strip()]

    subs: list[UserSubscription] = []
    for uid in user_ids:
        kws = keywords_by_user.get(uid) or defaults
        if not kws:
            continue  # 无有效关键词：本轮不为其抓取（不回落别人配置的源）
        srcs = sources_by_user.get(uid) or list(DEFAULT_SOURCES)
        subs.append(UserSubscription(user_id=uid, keywords=tuple(kws), sources=tuple(srcs)))
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


async def _find_existing_paper_id(db: AsyncSession, item: PaperItem) -> int | None:
    """跨源去重查找：先按全局键（pmid 列），再按 doi（部分唯一索引列）。"""
    key = external_key(item)
    pid = (
        await db.execute(select(Paper.id).where(Paper.pmid == key))
    ).scalar_one_or_none()
    if pid is not None:
        return pid
    if item.doi:
        pid = (
            await db.execute(select(Paper.id).where(Paper.doi == item.doi.lower()))
        ).scalar_one_or_none()
        if pid is not None:
            return pid
    return None


# 已存在行允许刷新的元数据列（P15：跨源重复命中时补全/更新题录元数据；
# title/abstract/abstract_zh/tags/keywords 不在其列——不覆盖既有正文与中译）
_METADATA_REFRESH_COLS = ("doi", "journal", "authors", "pub_date", "cited_count", "if_approx")


def _metadata_values(item: PaperItem) -> dict:
    """PaperItem → 可刷新元数据列的值字典（pub_date 由 year 兜底）。"""
    return {
        "doi": item.doi.lower() if item.doi else None,
        "journal": item.journal,
        "authors": list(item.authors),
        "pub_date": item.pub_date or (date(item.year, 1, 1) if item.year else None),
        "cited_count": item.cited_count,
        "if_approx": item.if_approx,
    }


async def _refresh_metadata(db: AsyncSession, paper_id: int, item: PaperItem) -> None:
    """对已存在行刷新元数据列（P15，空值不回填：源没有就不覆盖已有值）。"""
    values = {k: v for k, v in _metadata_values(item).items() if v not in (None, "", [])}
    if values:
        await db.execute(update(Paper).where(Paper.id == paper_id).values(**values))


async def _upsert_item(
    db: AsyncSession, item: PaperItem, tags: list[str], hits: list[str]
) -> tuple[int, bool]:
    """单篇入库：跨源去重后 papers 幂等 upsert；返回 (paper_id, 是否新插入)。

    同一篇被多源命中时（doi/arxiv 相同），第二轮起只补归属不重复建行；命中已存在
    行时刷新元数据列（P15，空值不回填）。真正并发撞车由 pmid 唯一约束 +
    ON CONFLICT DO UPDATE（仅元数据列，语义同上）兜底。
    """
    key = external_key(item)
    existing = await _find_existing_paper_id(db, item)
    if existing is not None:
        await _refresh_metadata(db, existing, item)
        return existing, False
    stmt = (
        pg_insert(Paper)
        .values(
            pmid=key,
            source=item.source or "unknown",
            title=item.title,
            abstract=item.abstract,
            tags=tags,
            keywords=hits,
            **_metadata_values(item),
        )
        .on_conflict_do_update(
            index_elements=["pmid"],
            set_={col: getattr(pg_insert(Paper).excluded, col) for col in _METADATA_REFRESH_COLS},
        )
    )
    await db.execute(stmt)
    paper_id = (
        await db.execute(select(Paper.id).where(Paper.pmid == key))
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


# ── 轮次执行与 runs 记录（步 B） ──────────────────────────
# 「立即检索」并发护栏：进程内 asyncio 锁，同一时刻只允许一轮抓取。
_crawl_lock = asyncio.Lock()


async def _write_run(
    db: AsyncSession, trigger: str, stats: dict, status: str, error: str | None = None
) -> PaperCrawlRun:
    """写一行抓取轮次记录并提交；返回 run 行（含 ORM 生成的自增 id）。"""
    run = PaperCrawlRun(trigger=trigger, stats=stats, status=status, error=error)
    db.add(run)
    await db.commit()
    return run


async def _execute_round(db: AsyncSession, trigger: str, force: bool) -> PaperCrawlRun | None:
    """执行一轮抓取并写 runs 表（成功/失败都写）；被 Q11 幂等跳过时返回 None。

    force=True（手动「立即检索」）：跳过同日幂等，跑完整一轮；不写进程内当日标记
    （schedule 的幂等语义不受手动轮影响，表内当日记录仍是第二重保险）。
    失败时先 rollback 再写 failed 行，然后原异常上抛（Hatchet 侧据此标记运行失败）。
    """
    if not force:
        if already_ran_today():
            return None
        if await _papers_created_today(db):
            mark_ran_today()  # 双保险：表内已有当日记录
            return None

    subs = await collect_subscriptions(db)
    stats: dict = {"per_source": {}, "users": len(subs), "fetched": 0, "added": 0}
    if not subs:
        logger.info("无可抓取用户（无文献权限或无有效订阅关键词），本轮跳过")
        if not force:
            mark_ran_today()
        return await _write_run(db, trigger, stats, "success")

    since_date = datetime.now(UTC).date() - timedelta(days=settings.papers_days_back)
    added = 0
    try:
        for sub in subs:
            for source_name in sub.sources:
                provider = get_provider(source_name)
                if provider is None:
                    logger.warning("用户 %d 勾选了未注册源 %s，跳过", sub.user_id, source_name)
                    continue
                try:
                    items = await provider.search(list(sub.keywords), since_date)
                except httpx.HTTPError as exc:
                    logger.warning("源 %s 抓取失败（用户 %d）：%s", source_name, sub.user_id, exc)
                    continue
                await asyncio.sleep(RATE_LIMIT_SLEEP)  # 源间 polite 限速（非重试）
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
                    paper_id, is_new = await _upsert_item(db, item, tags, hits)
                    await _attribute_paper(db, paper_id, [sub.user_id])
                    if is_new:
                        added += 1
                        src_stats["added"] += 1
                await db.commit()
                logger.info(
                    "用户 %d 源 %s 入库完成（累计新增 %d）", sub.user_id, source_name, added
                )
        if not force:
            mark_ran_today()
        translated = await _backfill_translations(db)
        if translated:
            logger.info("中译回填 %d 篇", translated)
        stats["translated"] = translated
        stats["added"] = added
        return await _write_run(db, trigger, stats, "success")
    except Exception as exc:
        await db.rollback()  # 会话可能处于中断事务，先复位再写 failed 行
        logger.exception("抓取轮次失败（trigger=%s）", trigger)
        return await _write_run(db, trigger, stats, "failed", error=str(exc)[:1000])


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
