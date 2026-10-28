"""Semantic Scholar 数据源（免费，全学科，Graph API v1；顺带 TLDR/引用数二期用）。

- GET api.semanticscholar.org/graph/v1/paper/search：query=关键词，
  fields 显式声明（title/abstract/year/authors/externalIds/url/venue/publicationDate）；
  免费档约 1 req/s，429 由 tenacity 重试收口（papers_crawl 另有统一 polite sleep）；
- externalIds 同时给出 DOI / ArXiv / CorpusId，是跨源去重的富矿；
- publicationDate 为空（部分老记录）时按 year >= since.year 兜底过滤。
"""
import logging
from datetime import date

import httpx

from app.config import settings
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.base import PaperItem, dedupe_items

logger = logging.getLogger("lumencafe.papers")

S2_BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,abstract,year,authors,externalIds,url,venue,publicationDate,citationCount"


@external_retry()
async def _query(client: httpx.AsyncClient, keyword: str, limit: int, api_key: str | None = None) -> dict:
    """单次 S2 paper/search 查询；429/5xx 由 tenacity 重试。

    - api_key（service_keys 取匙注入）：x-api-key 请求头（S2 Graph API 认证头），
      无 key 走匿名共享池（限流激进，429 由重试收口，行为与升级前一致）。
    """
    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    resp = await client.get(
        f"{S2_BASE}/paper/search",
        params={"query": keyword, "limit": max(min(limit, 100), 1), "fields": FIELDS},
        headers=headers or None,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_papers(data: dict, keyword: str) -> list[PaperItem]:
    """解析 S2 响应为 PaperItem 列表（调用方再做日期过滤）。"""
    items: list[PaperItem] = []
    for paper in data.get("data", []) or []:
        paper_id = str(paper.get("paperId") or "")
        if not paper_id:
            continue
        ext = paper.get("externalIds") or {}
        pub_date: date | None = None
        raw_date = str(paper.get("publicationDate") or "")[:10]
        try:
            pub_date = date.fromisoformat(raw_date)
        except ValueError:
            pass
        year = paper.get("year")
        citation = paper.get("citationCount")  # 元数据增强（P15）：被引数
        items.append(
            PaperItem(
                title=str(paper.get("title") or ""),
                authors=tuple(
                    str(a.get("name") or "") for a in paper.get("authors", []) or [] if a.get("name")
                ),
                abstract=str(paper.get("abstract") or ""),
                year=int(year) if year else (pub_date.year if pub_date else None),
                doi=str(ext.get("DOI") or ""),
                arxiv_id=str(ext.get("ArXiv") or ""),
                url=str(paper.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"),
                source="semantic_scholar",
                external_id=paper_id,
                journal=str(paper.get("venue") or ""),
                pub_date=pub_date,
                cited_count=int(citation) if citation is not None else None,
            )
        )
    return items


class SemanticScholarProvider:
    """Semantic Scholar 数据源（SourceProvider 契约实现）。"""

    name = "semantic_scholar"
    display_name = "Semantic Scholar（全学科）"
    key_service = "semantic_scholar"  # service_keys 服务名；无匙 = 匿名共享池

    async def search(
        self,
        keywords: list[str],
        since_date: date,
        until_date: date | None = None,
        api_key: str | None = None,
    ) -> list[PaperItem]:
        client = get_http_client()
        items: list[PaperItem] = []
        for keyword in keywords:
            data = await _query(client, keyword, settings.papers_retmax, api_key=api_key)
            items.extend(_parse_papers(data, keyword))

        def _keep(item: PaperItem) -> bool:
            if item.pub_date is not None:
                if item.pub_date < since_date:
                    return False
                # P21 年份上限：S2 无日期区间参数，客户端后过滤兜底
                return until_date is None or item.pub_date <= until_date
            if item.year is not None:
                if item.year < since_date.year:
                    return False
                return until_date is None or item.year <= until_date.year
            return True  # 无日期条目保守保留

        return dedupe_items([i for i in items if _keep(i)])
