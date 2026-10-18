"""文献抓取执行体（批次 2 填充，PRD §4.8 + 架构设计 §3.8/Q11；NCBI 解析沿用旧版 pubmed.py）。

流程：聚合订阅关键词（用户设置 subscribe_keywords，未配置用户回落 env 默认）→
NCBI esearch（≤3 req/s）→ efetch 分批（≤100/批、批间 sleep）→ 解析打标 →
papers ON CONFLICT(pmid) DO NOTHING 入库 + paper_users 归属（ON CONFLICT 幂等）→
LLM 中译回填（单轮 ≤20 篇、篇间 ≥1s，走网关默认路由，失败跳过不阻塞抓取）。

同日去重双保险（Q11）：进程内日期标记 + papers 表当日已有记录。
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.papers import Paper, PaperUser
from app.models.user_settings import UserSetting
from app.services import llm_gateway, route_service

logger = logging.getLogger("lumencafe.papers")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_BATCH_SIZE = 100  # efetch 单批最多 100 个 pmid
RATE_LIMIT_SLEEP = 0.4  # NCBI 限速 ≤3 req/s：请求间至少间隔 0.4s
TRANSLATE_MAX_PER_ROUND = 20  # 中译单轮 ≤20 篇（PRD 4.8）
TRANSLATE_INTERVAL = 1.0  # 中译篇间 ≥1s（PRD 4.8）

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


def already_ran_today() -> bool:
    return _last_run_date == datetime.now(UTC).date().isoformat()


def mark_ran_today() -> None:
    global _last_run_date
    _last_run_date = datetime.now(UTC).date().isoformat()


# ── NCBI E-utilities（沿用旧版 island 实现） ──────────────
def _common_params() -> dict[str, str]:
    params: dict[str, str] = {"tool": "lumencafe"}
    if settings.ncbi_email:
        params["email"] = settings.ncbi_email
    return params


def build_headers() -> dict[str, str]:
    headers = {"User-Agent": "lumencafe-papers/1.0"}
    if settings.ncbi_email:
        headers["User-Agent"] += f" (contact: {settings.ncbi_email})"
    return headers


async def esearch(
    client: httpx.AsyncClient, keyword: str, retmax: int, days_back: int
) -> list[str]:
    """按关键词检索最近 days_back 天内发表的文献，返回 pmid 列表。"""
    today = date.today()
    mindate = (today - timedelta(days=days_back)).strftime("%Y/%m/%d")
    params: dict[str, Any] = {
        **_common_params(),
        "db": "pubmed",
        "term": f"{keyword}[Title/Abstract]",
        "retmax": retmax,
        "retmode": "json",
        "datetype": "pdat",
        "mindate": mindate,
        "maxdate": today.strftime("%Y/%m/%d"),
        "sort": "pub date",
    }
    resp = await client.get(f"{EUTILS_BASE}/esearch.fcgi", params=params)
    resp.raise_for_status()
    data = resp.json()
    idlist = data.get("esearchresult", {}).get("idlist", [])
    return [str(pmid) for pmid in idlist]


async def efetch(client: httpx.AsyncClient, pmids: list[str]) -> str:
    """按 pmid 分批拉取题录 XML，批次间 sleep 限速，拼接后返回。"""
    if not pmids:
        return ""
    chunks = [pmids[i : i + EFETCH_BATCH_SIZE] for i in range(0, len(pmids), EFETCH_BATCH_SIZE)]
    parts: list[str] = []
    for idx, chunk in enumerate(chunks):
        if idx > 0:
            await asyncio.sleep(RATE_LIMIT_SLEEP)
        params = {**_common_params(), "db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
        resp = await client.post(f"{EUTILS_BASE}/efetch.fcgi", data=params)
        resp.raise_for_status()
        parts.append(resp.text)
        logger.info("efetch 第 %d/%d 批完成（%d 篇）", idx + 1, len(chunks), len(chunk))
    return "".join(parts)


def _element_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _parse_pub_date(article: ET.Element) -> date | None:
    """解析期刊发表日期；只有 MedlineDate（如 "2024 Jan-Feb"）时取其中的年份。"""
    pub_date = article.find("Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year_el = pub_date.find("Year")
    if year_el is not None and year_el.text:
        try:
            return date(int(year_el.text.strip()), 1, 1)
        except ValueError:
            return None
    medline_el = pub_date.find("MedlineDate")
    if medline_el is not None and medline_el.text:
        match = re.search(r"(\d{4})", medline_el.text)
        if match:
            return date(int(match.group(1)), 1, 1)
    return None


def _parse_authors(article: ET.Element) -> list[str]:
    authors: list[str] = []
    for author in article.findall("AuthorList/Author"):
        collective = _element_text(author.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last_name = _element_text(author.find("LastName"))
        initials = _element_text(author.find("Initials"))
        if last_name and initials:
            authors.append(f"{last_name} {initials}")
        elif last_name:
            authors.append(last_name)
    return authors


def parse_efetch(xml_text: str) -> list[dict[str, Any]]:
    """解析 efetch 返回的 XML，提取每篇文献的题录字段。"""
    if not xml_text.strip():
        return []
    root = ET.fromstring(xml_text)
    papers: list[dict[str, Any]] = []
    for art in root.findall(".//PubmedArticle"):
        medline = art.find("MedlineCitation")
        if medline is None:
            continue
        article = medline.find("Article")
        if article is None:
            continue
        pmid = _element_text(medline.find("PMID"))
        if not pmid:
            continue
        abstract_parts = [_element_text(ab) for ab in article.findall("Abstract/AbstractText")]
        papers.append(
            {
                "pmid": pmid,
                "title": _element_text(article.find("ArticleTitle")),
                "abstract": "\n".join(p for p in abstract_parts if p),
                "journal": _element_text(article.find("Journal/ISOAbbreviation"))
                or _element_text(article.find("Journal/Title")),
                "authors": _parse_authors(article),
                "pub_date": _parse_pub_date(article),
            }
        )
    return papers


def tag_paper(title: str, abstract: str) -> tuple[list[str], list[str]]:
    """按规则打标签：标题+摘要大小写不敏感匹配，可多命中；返回 (标签, 命中词)。"""
    text = f"{title}\n{abstract}".lower()
    tags: list[str] = []
    hit_words: list[str] = []
    for tag, words in TAG_RULES.items():
        matched = [w for w in words if w in text]
        if matched:
            tags.append(tag)
            hit_words.extend(matched)
    return tags, hit_words


# ── 订阅关键词聚合 ────────────────────────────────────────
async def collect_keywords(db: AsyncSession) -> dict[str, list[int]]:
    """关键词 → 订阅用户列表。

    用户设置（scope=user, key=subscribe_keywords, value={keywords:[...]}）优先；
    未配置任何关键词的用户回落 env 默认关键词（papers_default_keywords）。
    """
    rows = (
        await db.execute(select(UserSetting).where(UserSetting.key == "subscribe_keywords"))
    ).scalars().all()
    user_keywords: dict[int, list[str]] = {}
    configured: set[int] = set()
    for row in rows:
        kws = [str(k).strip() for k in (row.value or {}).get("keywords", []) if str(k).strip()]
        if kws:
            user_keywords[row.user_id] = kws
            configured.add(row.user_id)

    defaults = [k.strip() for k in (settings.papers_default_keywords or "").split(",") if k.strip()]

    from app.models.user import User

    all_users = (await db.execute(select(User.id))).scalars().all()
    keyword_map: dict[str, list[int]] = {}
    for uid in all_users:
        kws = user_keywords.get(uid) or defaults
        for kw in kws:
            (keyword_map.setdefault(kw, [])).append(uid)
    return keyword_map


# ── 入库 ────────────────────────────────────────────────
async def _upsert_paper(db: AsyncSession, record: dict[str, Any], tags: list[str], hits: list[str]) -> tuple[int, bool]:
    """papers 幂等入库（ON CONFLICT(pmid) DO NOTHING）；返回 (paper_id, 是否新插入)。"""
    stmt = (
        pg_insert(Paper)
        .values(
            pmid=record["pmid"],
            title=record["title"],
            abstract=record["abstract"],
            journal=record["journal"],
            authors=record["authors"],
            pub_date=record["pub_date"],
            tags=tags,
            keywords=hits,
        )
        .on_conflict_do_nothing(index_elements=["pmid"])
    )
    result = await db.execute(stmt)
    paper_id = (
        await db.execute(select(Paper.id).where(Paper.pmid == record["pmid"]))
    ).scalar_one()
    return paper_id, result.rowcount == 1


async def _attribute_paper(db: AsyncSession, paper_id: int, user_ids: list[int]) -> None:
    """归属记录幂等写入（ON CONFLICT DO NOTHING）。"""
    for uid in set(user_ids):
        await db.execute(
            pg_insert(PaperUser)
            .values(paper_id=paper_id, user_id=uid)
            .on_conflict_do_nothing(index_elements=["paper_id", "user_id"])
        )


async def _papers_created_today(db: AsyncSession) -> bool:
    """Q11 第二重去重：papers 表当日已有抓取记录即视为已执行。"""
    count = (
        await db.execute(
            select(func.count(Paper.id)).where(
                func.date(Paper.created_at) == datetime.now(UTC).date()
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
            logger.warning("PMID %s 中译失败，跳过：%s", paper.pmid, exc)
            continue
        if zh and zh.strip():
            paper.abstract_zh = zh.strip()
            done += 1
    if done:
        await db.commit()
    return done


async def run_daily_crawl(db: AsyncSession) -> int:
    """执行一轮文献抓取，返回本轮新入库文献数（PRD 4.8：{added: n}）。"""
    if already_ran_today():
        return 0
    if await _papers_created_today(db):
        mark_ran_today()  # 双保险：表内已有当日记录
        return 0

    keyword_map = await collect_keywords(db)
    if not keyword_map:
        logger.info("无订阅关键词（用户未配置且未设 env 默认），本轮跳过")
        mark_ran_today()
        return 0

    added = 0
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, headers=build_headers()) as client:
        for keyword, user_ids in keyword_map.items():
            try:
                pmids = await esearch(
                    client, keyword, settings.papers_retmax, settings.papers_days_back
                )
            except httpx.HTTPError as exc:
                logger.warning("esearch 失败（%s）：%s", keyword, exc)
                continue
            await asyncio.sleep(RATE_LIMIT_SLEEP)
            if not pmids:
                continue
            try:
                xml = await efetch(client, pmids)
            except httpx.HTTPError as exc:
                logger.warning("efetch 失败（%s）：%s", keyword, exc)
                continue
            for record in parse_efetch(xml):
                tags, hits = tag_paper(record["title"], record["abstract"])
                paper_id, is_new = await _upsert_paper(db, record, tags, hits)
                await _attribute_paper(db, paper_id, user_ids)
                if is_new:
                    added += 1
            await db.commit()
            logger.info("关键词「%s」入库完成（累计新增 %d）", keyword, added)

    mark_ran_today()
    translated = await _backfill_translations(db)
    if translated:
        logger.info("中译回填 %d 篇", translated)
    return added
