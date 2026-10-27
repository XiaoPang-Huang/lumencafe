"""arXiv 数据源（官方 Atom API，免费无密钥；CS/物理/数学预印本）。

- GET export.arxiv.org/api/query：search_query=all:"关键词"，按提交时间倒序，
  客户端再按 published >= since_date 过滤（接口的 submittedDate 过滤语法对
  词组检索支持不稳定，客户端过滤更可靠）；
- Atom XML 解析用 ElementTree（命名空间 http://www.w3.org/2005/Atom；
  arxiv 扩展命名空间 http://arxiv.org/schemas/atom 提供 doi/journal_ref）；
- 瞬时错误由 tenacity 重试；arXiv 官方限速约 1 req/3s，请求间隔由调用方
  （papers_crawl）统一 polite sleep 收口。
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.base import PaperItem, dedupe_items

logger = logging.getLogger("lumencafe.papers")

ARXIV_BASE = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


@external_retry()
async def _query(client: httpx.AsyncClient, keyword: str, retmax: int) -> str:
    """单次 arXiv API 查询，返回 Atom XML 文本；瞬时错误由 tenacity 重试。"""
    params: dict[str, Any] = {
        "search_query": f'all:"{keyword}"',
        "start": 0,
        "max_results": max(min(retmax, 100), 1),  # 接口单页上限
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = await client.get(ARXIV_BASE, params=params)
    resp.raise_for_status()
    return resp.text


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.text or "").strip()


def _parse_atom(xml_text: str, keyword: str) -> list[PaperItem]:
    """解析 arXiv Atom 响应为 PaperItem 列表（调用方再做日期过滤）。"""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("arXiv 响应解析失败（%s）：%s", keyword, exc)
        return []
    items: list[PaperItem] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        raw_id = _text(entry.find(f"{ATOM_NS}id"))  # https://arxiv.org/abs/2401.12345v2
        match = re.search(r"/abs/([^/]+)$", raw_id)
        arxiv_id = match.group(1) if match else raw_id.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # 去版本号
        if not arxiv_id:
            continue
        published = _text(entry.find(f"{ATOM_NS}published"))[:10]  # YYYY-MM-DD
        pub_date: date | None = None
        year: int | None = None
        try:
            pub_date = date.fromisoformat(published)
            year = pub_date.year
        except ValueError:
            pass
        authors = tuple(
            _text(a.find(f"{ATOM_NS}name"))
            for a in entry.findall(f"{ATOM_NS}author")
            if _text(a.find(f"{ATOM_NS}name"))
        )
        items.append(
            PaperItem(
                title=_text(entry.find(f"{ATOM_NS}title")),
                authors=authors,
                abstract=_text(entry.find(f"{ATOM_NS}summary")),
                year=year,
                doi=_text(entry.find(f"{ARXIV_NS}doi")),
                arxiv_id=arxiv_id,
                url=f"https://arxiv.org/abs/{arxiv_id}",
                source="arxiv",
                external_id=arxiv_id,
                journal=_text(entry.find(f"{ARXIV_NS}journal_ref")),
                pub_date=pub_date,
            )
        )
    return items


class ArxivProvider:
    """arXiv 数据源（SourceProvider 契约实现）。"""

    name = "arxiv"
    display_name = "arXiv（预印本）"

    async def search(self, keywords: list[str], since_date: date) -> list[PaperItem]:
        client = get_http_client()
        items: list[PaperItem] = []
        for keyword in keywords:
            xml_text = await _query(client, keyword, settings.papers_retmax)
            items.extend(_parse_atom(xml_text, keyword))
        # 客户端日期过滤（published >= since_date；无日期条目保守保留）
        filtered = [i for i in items if i.pub_date is None or i.pub_date >= since_date]
        return dedupe_items(filtered)
