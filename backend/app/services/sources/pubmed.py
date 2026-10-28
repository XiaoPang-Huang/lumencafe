"""PubMed 数据源（NCBI E-utilities；由 papers_crawl.py 收编而来，逻辑搬家不改语义）。

- esearch/efetch 及 XML 解析原样来自旧 papers_crawl.py（NCBI 限速 ≤3 req/s：
  请求间 ≥0.4s，efetch 分批 ≤100、批间 sleep），瞬时错误由 tenacity 重试（4xx 不重试）；
- 增强一处：parse_efetch 额外提取 ArticleId IdType="doi"（跨源去重键用），其余字段语义不变；
- PubMedProvider 实现 SourceProvider 契约：search(keywords, since_date) → list[PaperItem]。
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.config import settings
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.base import PaperItem, dedupe_items

logger = logging.getLogger("lumencafe.papers")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_BATCH_SIZE = 100  # efetch 单批最多 100 个 pmid
RATE_LIMIT_SLEEP = 0.4  # NCBI 限速 ≤3 req/s：请求间至少间隔 0.4s


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


@external_retry()
async def esearch(
    client: httpx.AsyncClient,
    keyword: str,
    retmax: int,
    days_back: int,
    maxdate: date | None = None,
) -> list[str]:
    """按关键词检索最近 days_back 天内发表的文献，返回 pmid 列表。

    瞬时错误（网络类/5xx/429）由 tenacity 重试（指数退避，最小间隔 ≥0.5s
    对齐 NCBI ≤3 req/s 纪律）；4xx 不重试。
    maxdate（P21 年份上限折算日期）经 esearch 的 maxdate+datetype=pdat 走服务端过滤；
    不传 = 截止今天。
    """
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
        "maxdate": (maxdate or today).strftime("%Y/%m/%d"),
        "sort": "pub date",
    }
    resp = await client.get(
        f"{EUTILS_BASE}/esearch.fcgi", params=params, headers=build_headers()
    )
    resp.raise_for_status()
    data = resp.json()
    idlist = data.get("esearchresult", {}).get("idlist", [])
    return [str(pmid) for pmid in idlist]


@external_retry()
async def efetch(client: httpx.AsyncClient, pmids: list[str]) -> str:
    """按 pmid 分批拉取题录 XML，批次间 sleep 限速（polite，非重试），拼接后返回。

    瞬时错误由 tenacity 重试；整批重发幂等（NCBI 只读接口）。
    """
    if not pmids:
        return ""
    chunks = [pmids[i : i + EFETCH_BATCH_SIZE] for i in range(0, len(pmids), EFETCH_BATCH_SIZE)]
    parts: list[str] = []
    for idx, chunk in enumerate(chunks):
        if idx > 0:
            await asyncio.sleep(RATE_LIMIT_SLEEP)
        params = {**_common_params(), "db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
        resp = await client.post(
            f"{EUTILS_BASE}/efetch.fcgi", data=params, headers=build_headers()
        )
        resp.raise_for_status()
        parts.append(resp.text)
        logger.info("efetch 第 %d/%d 批完成（%d 篇）", idx + 1, len(chunks), len(chunk))
    return "".join(parts)


def _element_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _coerce_year(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d{4})", text)
    return int(match.group(1)) if match else None


def _parse_pub_date(article: ET.Element) -> date | None:
    """解析发表日期。

    字段优先级（PubMed XML 的坑，2026-10-29 用户抓出 2027 年论文）：
    1. ``Article/ArticleDate`` = 在线实际发表日（e-pub，真实首发时间）——**优先**；
    2. ``JournalIssue/PubDate`` = 纸刊期号日期，出版社常提前分配（2026-10 就能挂
       "2027 Jan"），只能作 fallback；
    3. 年份 sanity：结果晚于「当前本地年 + 1」视为期号预分配错误，回落另一字段，
       仍未来则返回 None（不编造日期）。
    MedlineDate（如 "2024 Jan-Feb"）只取其中年份，月份不可得。
    """
    # 容忍度：纸刊期号日期允许最多提前约 4 个月（当年 10 月挂 "2027 Jan" 属正常
    # 期号预分配）；超过则视为脏数据，回落下一候选，全未来返回 None（不编造）。
    horizon = date.today() + timedelta(days=120)

    candidates: list[date] = []

    article_date = article.find("ArticleDate")
    if article_date is not None:
        y = _coerce_year((article_date.findtext("Year") or "").strip() or None)
        if y:
            m = _coerce_year((article_date.findtext("Month") or "").strip() or None) or 1
            d = _coerce_year((article_date.findtext("Day") or "").strip() or None) or 1
            try:
                candidates.append(date(y, min(max(m, 1), 12), min(max(d, 1), 28)))
            except ValueError:
                candidates.append(date(y, 1, 1))

    pub_date = article.find("Journal/JournalIssue/PubDate")
    if pub_date is not None:
        y = _coerce_year((pub_date.findtext("Year") or "").strip() or None)
        if y:
            candidates.append(date(y, 1, 1))
        else:
            medline_el = pub_date.find("MedlineDate")
            y = _coerce_year((medline_el.text or "").strip() if medline_el is not None else None)
            if y:
                candidates.append(date(y, 1, 1))

    for cand in candidates:
        if cand <= horizon:
            return cand
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


def _parse_doi(art: ET.Element) -> str:
    """从 PubMedData/ArticleIdList 提取 DOI（跨源去重键用）。"""
    for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
        if (aid.get("IdType") or "").lower() == "doi" and aid.text:
            return aid.text.strip()
    return ""


def parse_efetch(xml_text: str) -> list[dict[str, Any]]:
    """解析 efetch 返回的 XML，提取每篇文献的题录字段（含 doi，见 _parse_doi）。"""
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
                "doi": _parse_doi(art),
            }
        )
    return papers


class PubMedProvider:
    """PubMed 数据源（SourceProvider 契约实现）。"""

    name = "pubmed"
    display_name = "PubMed（生物医学）"
    key_service = None  # 匿名源（可选 NCBI 账号提速，本期不接 key 注入）

    async def search(
        self,
        keywords: list[str],
        since_date: date,
        until_date: date | None = None,
        api_key: str | None = None,
    ) -> list[PaperItem]:
        """按关键词逐个 esearch → efetch → 解析；关键词间 NCBI polite 限速。

        until_date（P21 年份上限）经 esearch maxdate 走 NCBI 服务端过滤；
        api_key 形参为契约对齐保留（PubMed 本期不接 key 注入，忽略）。
        """
        today = datetime.now(UTC).date()
        days_back = max((today - since_date).days, 0)
        client = get_http_client()  # 共享总机：复用 TCP/TLS 连接
        items: list[PaperItem] = []
        for idx, keyword in enumerate(keywords):
            if idx > 0:
                await asyncio.sleep(RATE_LIMIT_SLEEP)
            # maxdate 仅在有年份上限时按关键字传参（无上限调用保持四参形态，
            # 兼容按旧签名打桩的调用方/测试替身）
            if until_date is not None:
                pmids = await esearch(
                    client, keyword, settings.papers_retmax, days_back, maxdate=until_date
                )
            else:
                pmids = await esearch(client, keyword, settings.papers_retmax, days_back)
            if not pmids:
                continue
            await asyncio.sleep(RATE_LIMIT_SLEEP)
            xml = await efetch(client, pmids)
            for record in parse_efetch(xml):
                pub_date = record["pub_date"]
                items.append(
                    PaperItem(
                        title=record["title"],
                        authors=tuple(record["authors"]),
                        abstract=record["abstract"],
                        year=pub_date.year if pub_date else None,
                        doi=record["doi"],
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{record['pmid']}/",
                        source=self.name,
                        external_id=record["pmid"],
                        journal=record["journal"],
                        pub_date=pub_date,
                    )
                )
        return dedupe_items(items)
