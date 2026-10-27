"""DOAJ 数据源（Directory of Open Access Journals，免费无密钥，开放获取期刊）。

- GET doaj.org/api/search/articles/{关键词}：?page=1&pageSize=N（上限 100），
  期刊文章粒度（覆盖偏人文社科与 OA 期刊，量小属预期）；
- bibjson.identifier 是 [{type, id}] 列表，取 type=doi 的做 DOI（跨源去重键）；
  无 DOI 时用结果自带 id（DOAJ 内部 ID）做 external_id；
- 日期只有 year 粒度：year >= since.year 过滤；无 year 条目保守保留。
"""
import logging
from datetime import date

import httpx

from app.config import settings
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.base import PaperItem, dedupe_items

logger = logging.getLogger("lumencafe.papers")

DOAJ_BASE = "https://doaj.org/api/search/articles"


@external_retry()
async def _query(client: httpx.AsyncClient, keyword: str, page_size: int) -> dict:
    """单次 DOAJ 文章检索；瞬时错误由 tenacity 重试。"""
    resp = await client.get(
        f"{DOAJ_BASE}/{keyword}",
        params={"page": 1, "pageSize": max(min(page_size, 100), 1)},
    )
    resp.raise_for_status()
    return resp.json()


def _extract_doi(identifiers: list | None) -> str:
    for ident in identifiers or []:
        if str(ident.get("type") or "").lower() == "doi" and ident.get("id"):
            return str(ident["id"]).strip()
    return ""


def _parse_results(data: dict, keyword: str) -> list[PaperItem]:
    """解析 DOAJ 响应为 PaperItem 列表（调用方再做日期过滤）。"""
    items: list[PaperItem] = []
    for result in data.get("results", []) or []:
        bib = result.get("bibjson") or {}
        doaj_id = str(result.get("id") or "")
        title = str(bib.get("title") or "")
        if not title:
            continue
        year_raw = bib.get("year")
        year: int | None = None
        try:
            year = int(str(year_raw)) if year_raw not in (None, "") else None
        except ValueError:
            year = None
        links = bib.get("link") or []
        url = next(
            (str(l.get("url") or "") for l in links if l.get("url")),
            f"https://doaj.org/article/{doaj_id}" if doaj_id else "",
        )
        journal = str((bib.get("journal") or {}).get("title") or "")
        items.append(
            PaperItem(
                title=title,
                authors=tuple(
                    str(a.get("name") or "") for a in bib.get("author", []) or [] if a.get("name")
                ),
                abstract=str(bib.get("abstract") or ""),
                year=year,
                doi=_extract_doi(bib.get("identifier")),
                url=url,
                source="doaj",
                external_id=doaj_id,
                journal=journal,
            )
        )
    return items


class DoajProvider:
    """DOAJ 数据源（SourceProvider 契约实现）。"""

    name = "doaj"
    display_name = "DOAJ（开放获取期刊）"

    async def search(self, keywords: list[str], since_date: date) -> list[PaperItem]:
        client = get_http_client()
        items: list[PaperItem] = []
        for keyword in keywords:
            data = await _query(client, keyword, settings.papers_retmax)
            items.extend(_parse_results(data, keyword))
        filtered = [i for i in items if i.year is None or i.year >= since_date.year]
        return dedupe_items(filtered)
