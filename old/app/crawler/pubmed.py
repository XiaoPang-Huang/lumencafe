"""PubMed E-utilities 客户端。

- esearch：按关键词检索近期文献，返回 pmid 列表
- efetch：按 pmid 批量拉取题录 XML（每批 ≤100，批次间限速 ≤3 req/s）
- parse_efetch：用标准库 xml.etree 解析 XML，提取标题/摘要/期刊/作者/日期
- tag_paper：按规则打标签（标题+摘要文本，大小写不敏感，可多命中）
"""
import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger("island.crawler")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_BATCH_SIZE = 100  # efetch 单批最多 100 个 pmid
# NCBI 限速要求 ≤3 req/s，批次/关键词之间 sleep 保证不超限
RATE_LIMIT_SLEEP = 0.4

# 打标规则：标签 -> 命中词列表（大小写不敏感，可多命中）
TAG_RULES: dict[str, list[str]] = {
    "AD": ["alzheimer", "dementia"],
    "PD": ["parkinson"],
    "ALS": ["als", "amyotrophic"],
    "scale": [
        "mmse",
        "moca",
        "updrs",
        "hoehn-yahr",
        "cdr",
        "mini-mental",
        "montreal cognitive",
    ],
}


def build_headers() -> dict[str, str]:
    """构造请求头。NCBI 建议 User-Agent 带联系邮箱（可选）。"""
    headers = {"User-Agent": "island-papers/1.0"}
    if settings.ncbi_email:
        headers["User-Agent"] += f" (contact: {settings.ncbi_email})"
    return headers


def _common_params() -> dict[str, str]:
    """esearch/efetch 共用的身份参数。"""
    params: dict[str, str] = {"tool": "island-papers"}
    if settings.ncbi_email:
        params["email"] = settings.ncbi_email
    return params


async def esearch(
    client: httpx.AsyncClient,
    keyword: str,
    retmax: int = 20,
    days_back: int = 3,
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
        params = {
            **_common_params(),
            "db": "pubmed",
            "id": ",".join(chunk),
            "retmode": "xml",
        }
        resp = await client.post(f"{EUTILS_BASE}/efetch.fcgi", data=params)
        resp.raise_for_status()
        parts.append(resp.text)
        logger.info("efetch 第 %d/%d 批完成（%d 篇）", idx + 1, len(chunks), len(chunk))
    return "".join(parts)


def _element_text(el: ET.Element | None) -> str:
    """取元素全部文本（含内嵌子标签，如 <b> <i>）。"""
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
    """解析作者列表："LastName FM" 格式；团体作者取 CollectiveName。"""
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
        abstract_parts = [
            _element_text(ab) for ab in article.findall("Abstract/AbstractText")
        ]
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
    """按规则打标签：在标题+摘要中大小写不敏感匹配，可多命中。

    返回 (标签列表, 实际命中的关键词列表)。
    """
    text = f"{title}\n{abstract}".lower()
    tags: list[str] = []
    hit_words: list[str] = []
    for tag, words in TAG_RULES.items():
        matched = [w for w in words if w in text]
        if matched:
            tags.append(tag)
            hit_words.extend(matched)
    return tags, hit_words
