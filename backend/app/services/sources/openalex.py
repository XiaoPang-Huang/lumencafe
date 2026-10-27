"""OpenAlex 数据源（免费无密钥，全学科 3 亿+ 作品；跨行业首选补充源）。

- GET api.openalex.org/works：search=关键词 + filter=from_publication_date（服务端过滤），
  per-page 上限 200；设置过联系邮箱可进 polite 池（mailto 参数，可选提速，非必需）；
- abstract_inverted_index 是「词 → 位置」倒排索引，需按位置重建摘要文本；
- doi 字段为完整 URL（https://doi.org/...），统一剥成裸 DOI；
- 瞬时错误由 tenacity 重试（OpenAlex 偶发 503/429 在重试覆盖内）。
"""
import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.base import PaperItem, dedupe_items

logger = logging.getLogger("lumencafe.papers")

OPENALEX_BASE = "https://api.openalex.org/works"
DOI_PREFIX = "https://doi.org/"


@external_retry()
async def _query(client: httpx.AsyncClient, keyword: str, since: date, per_page: int) -> dict:
    """单次 OpenAlex works 查询；瞬时错误由 tenacity 重试。"""
    params: dict[str, Any] = {
        "search": keyword,
        "filter": f"from_publication_date:{since.isoformat()}",
        "per-page": max(min(per_page, 200), 1),
        "page": 1,
    }
    if settings.ncbi_email:  # 复用联系邮箱进 polite 池（OpenAlex 官方建议）
        params["mailto"] = settings.ncbi_email
    resp = await client.get(OPENALEX_BASE, params=params)
    resp.raise_for_status()
    return resp.json()


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """把 abstract_inverted_index（词 → 位置列表）重建为摘要文本。"""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[int(i)] = word
    return " ".join(positions[i] for i in sorted(positions))


def _parse_works(data: dict, keyword: str) -> list[PaperItem]:
    """解析 OpenAlex works 响应为 PaperItem 列表（服务端已按日期过滤）。"""
    items: list[PaperItem] = []
    for work in data.get("results", []) or []:
        work_id = str(work.get("id") or "")  # https://openalex.org/W123456
        openalex_id = work_id.rsplit("/", 1)[-1]
        if not openalex_id:
            continue
        doi = str(work.get("doi") or "")
        doi = doi.removeprefix(DOI_PREFIX)
        authors = tuple(
            str(a.get("author", {}).get("display_name") or "")
            for a in work.get("authorships", []) or []
            if a.get("author", {}).get("display_name")
        )
        source = (work.get("primary_location") or {}).get("source") or {}
        pub_date: date | None = None
        raw_date = str(work.get("publication_date") or "")[:10]
        try:
            pub_date = date.fromisoformat(raw_date)
        except ValueError:
            pass
        year = work.get("publication_year")
        items.append(
            PaperItem(
                title=str(work.get("display_name") or ""),
                authors=authors,
                abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
                year=int(year) if year else (pub_date.year if pub_date else None),
                doi=doi,
                url=doi and f"{DOI_PREFIX}{doi}" or work_id,
                source="openalex",
                external_id=openalex_id,
                journal=str(source.get("display_name") or ""),
                pub_date=pub_date,
            )
        )
    return items


class OpenAlexProvider:
    """OpenAlex 数据源（SourceProvider 契约实现）。"""

    name = "openalex"
    display_name = "OpenAlex（全学科）"

    async def search(self, keywords: list[str], since_date: date) -> list[PaperItem]:
        client = get_http_client()
        items: list[PaperItem] = []
        for keyword in keywords:
            data = await _query(client, keyword, since_date, settings.papers_retmax)
            items.extend(_parse_works(data, keyword))
        return dedupe_items(items)
