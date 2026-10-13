"""抓取编排：逐关键词 esearch → 汇总去重 → 过滤库内已有 → efetch → 解析打标 → 批量入库。"""
import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import SessionLocal
from ..llm.base import LLMNotConfiguredError
from ..llm.providers import get_llm
from ..models import Paper, PaperUser, UserSetting, WhitelistUser
from . import pubmed

logger = logging.getLogger("island.crawler")

SPACE_SETTINGS_USER = "space"

# 每轮最多翻译多少篇新增文献的中文摘要（LLM 调用有成本，超出的留给下轮）
MAX_TRANSLATE_PER_RUN = 20

# 订阅关键词设置：用户级（每人独立）；未设置的用户用 env 默认
SUBSCRIBE_KEY = "subscribe_keywords"


async def resolve_keywords_per_user() -> dict[str, list[str]]:
    """每个白名单用户的订阅关键词：user scope 设置优先，未配置回落 env 默认。"""
    default = [k for k in settings.subscribe_keywords if k]
    result: dict[str, list[str]] = {}
    async with SessionLocal() as session:
        users = (await session.execute(select(WhitelistUser))).scalars().all()
        for u in users:
            row = (
                await session.execute(
                    select(UserSetting).where(
                        UserSetting.user_id == u.openid,
                        UserSetting.scope == "user",
                        UserSetting.key == SUBSCRIBE_KEY,
                    )
                )
            ).scalar_one_or_none()
            words: list[str] = []
            if row and isinstance(row.value, dict) and row.value.get("words"):
                words = [str(w).strip() for w in row.value["words"] if str(w).strip()]
            result[u.openid] = words or list(default)
    return result


async def run_crawl(
    db: AsyncSession | None = None,
    days_back: int | None = None,
    retmax: int = 20,
) -> int:
    """执行一轮抓取，返回本次入库的新增文献条数。

    按用户关键词分别 esearch：每个 pmid 记录归属用户，文献流按人隔离。
    db 为 None 时自建会话（爬虫进程内使用）；由 API 侧复用时传入已有会话。
    """
    days = days_back if days_back is not None else settings.days_back
    user_keywords = await resolve_keywords_per_user()

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        headers=pubmed.build_headers(),
    ) as client:
        # 1. 逐用户逐关键词 esearch（关键词间限速），记录 pmid → 归属用户集合
        pmid_users: dict[str, set[str]] = {}
        first = True
        for openid, keywords in user_keywords.items():
            for keyword in keywords:
                if not first:
                    await asyncio.sleep(pubmed.RATE_LIMIT_SLEEP)
                first = False
                try:
                    ids = await pubmed.esearch(client, keyword, retmax=retmax, days_back=days)
                    logger.info("esearch %s %r -> %d 条", openid, keyword, len(ids))
                    for pid in ids:
                        pmid_users.setdefault(pid, set()).add(openid)
                except Exception:
                    logger.exception("esearch 失败，跳过：%s / %s", openid, keyword)
        pmids = list(pmid_users)
        if not pmids:
            logger.info("本轮没有候选文献")
            if db is not None:
                await backfill_translations(db)
                return 0
            async with SessionLocal() as session:
                await backfill_translations(session)
                return 0

        # 2. 过滤掉库里已存在的
        async def _fetch_and_store(session: AsyncSession) -> int:
            existing = set(
                (
                    await session.execute(
                        select(Paper.pmid).where(Paper.pmid.in_(pmids))
                    )
                )
                .scalars()
                .all()
            )
            fresh = [p for p in pmids if p not in existing]
            if not fresh:
                logger.info("候选文献均已入库，无需抓取")
                return 0

            # 3. efetch 拉取题录（内部分批限速）
            xml_text = await pubmed.efetch(client, fresh)
            parsed = pubmed.parse_efetch(xml_text)
            if not parsed:
                logger.warning("efetch 未解析到任何文献")
                return 0

            # 4. 打标 + ON CONFLICT DO NOTHING 批量入库（并发安全）
            for item in parsed:
                tags, hit_words = pubmed.tag_paper(item["title"], item["abstract"])
                stmt = (
                    pg_insert(Paper)
                    .values(
                        pmid=item["pmid"],
                        title=item["title"],
                        abstract=item["abstract"],
                        journal=item["journal"],
                        authors=item["authors"],
                        pub_date=item["pub_date"],
                        tags=tags,
                        keywords=hit_words,
                    )
                    .on_conflict_do_nothing(index_elements=["pmid"])
                )
                await session.execute(stmt)

            # 5. 写入文献 × 用户归属（含库内已有的 pmid——其他用户的关键词也可能命中老文献）
            id_map = {
                row.pmid: row.id
                for row in (
                    await session.execute(select(Paper.id, Paper.pmid).where(Paper.pmid.in_(pmids)))
                ).all()
            }
            for pmid, users in pmid_users.items():
                paper_id = id_map.get(pmid)
                if paper_id is None:
                    continue
                for openid in users:
                    await session.execute(
                        pg_insert(PaperUser)
                        .values(paper_id=paper_id, user_id=openid)
                        .on_conflict_do_nothing(index_elements=["paper_id", "user_id"])
                    )
            await session.commit()
            logger.info("本轮新增文献 %d 篇", len(parsed))

            # 6. best-effort：为新增文献生成中文摘要（LLM 未配置/失败都不影响入库）
            await translate_new_papers(session, parsed)
            return len(parsed)

        if db is not None:
            added = await _fetch_and_store(db)
            # 回填放在外层：没有新文献时存量 mock/缺失摘要也要升级
            await backfill_translations(db)
            return added
        async with SessionLocal() as session:
            added = await _fetch_and_store(session)
            await backfill_translations(session)
            return added


async def translate_new_papers(session: AsyncSession, parsed: list[dict[str, Any]]) -> None:
    """为新增文献生成中文摘要（标题+摘要中译）。

    best-effort：LLM 未配置、单篇失败、整体异常都只记日志，不影响抓取主流程。
    """
    try:
        llm = await get_llm("translate")
    except LLMNotConfiguredError:
        logger.info("LLM 未配置，跳过中文摘要生成")
        return
    done = 0
    for item in parsed[:MAX_TRANSLATE_PER_RUN]:
        if done >= MAX_TRANSLATE_PER_RUN:
            break
        if not item.get("abstract"):
            continue
        try:
            zh = await llm.translate_abstract(item["title"], item["abstract"])
        except Exception:
            logger.exception("摘要翻译失败 pmid=%s", item["pmid"])
            continue
        await session.execute(
            Paper.__table__.update()
            .where(Paper.pmid == item["pmid"])
            .values(abstract_zh=zh)
        )
        done += 1
        await asyncio.sleep(1)  # 供应商限速
    if done:
        await session.commit()
        logger.info("已生成 %d 篇中文摘要", done)


async def backfill_translations(session: AsyncSession) -> int:
    """回填存量文献的中文摘要：abstract_zh 为空或仍是 mock 占位的，逐篇翻译更新。"""
    try:
        llm = await get_llm("translate")
    except LLMNotConfiguredError:
        return 0
    rows = (
        await session.execute(
            select(Paper)
            .where(
                Paper.abstract != "",
                or_(Paper.abstract_zh.is_(None), Paper.abstract_zh.like("%mock%")),
            )
            .order_by(Paper.created_at.desc())
            .limit(MAX_TRANSLATE_PER_RUN)
        )
    ).scalars().all()
    done = 0
    for p in rows:
        try:
            p.abstract_zh = await llm.translate_abstract(p.title, p.abstract)
        except Exception:
            logger.exception("回填翻译失败 pmid=%s", p.pmid)
            continue
        done += 1
        await asyncio.sleep(1)
    if done:
        await session.commit()
        logger.info("回填中文摘要 %d 篇", done)
    return done


async def fetch_detail(pmid: str) -> dict[str, Any] | None:
    """按单个 pmid 拉取题录（预留：详情补抓等场景）。"""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        headers=pubmed.build_headers(),
    ) as client:
        xml_text = await pubmed.efetch(client, [pmid])
        papers = pubmed.parse_efetch(xml_text)
        return papers[0] if papers else None
