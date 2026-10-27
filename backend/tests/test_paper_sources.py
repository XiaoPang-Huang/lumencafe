"""文献数据源测试（论文域步 A）：四新源各 1 例（mock HTTP）+ 去重键 + 注册表。

mock 方式学 test_http_retry.py：monkeypatch httpx.AsyncClient.get/post 按 URL
分发假响应，provider 代码路径一致走共享总机但不真连外网。
"""

from datetime import date

import httpx

from app.services.sources import (
    DEFAULT_SOURCES,
    PaperItem,
    get_provider,
    list_providers,
    resolve_sources,
)
from app.services.sources.arxiv import ArxivProvider
from app.services.sources.base import dedupe_items
from app.services.sources.doaj import DoajProvider
from app.services.sources.openalex import OpenAlexProvider
from app.services.sources.semantic_scholar import SemanticScholarProvider

SINCE = date(2026, 10, 20)

# ── 各源假响应样例 ───────────────────────────────────────
_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2601.12345v2</id>
    <updated>2026-10-26T00:00:00Z</updated>
    <published>2026-10-25T00:00:00Z</published>
    <title>Graph Neural Networks for   Protein Folding</title>
    <summary>We propose a GNN method for protein folding.</summary>
    <author><name>Alice Zhang</name></author>
    <author><name>Bob Li</name></author>
    <arxiv:doi>10.1000/gnn.2026</arxiv:doi>
    <arxiv:journal_ref>Test Conf 2026</arxiv:journal_ref>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2501.99999v1</id>
    <published>2026-10-10T00:00:00Z</published>
    <title>Old paper outside window</title>
    <summary>Too old.</summary>
    <author><name>Carol Wang</name></author>
  </entry>
</feed>"""

_OPENALEX_JSON = {
    "results": [
        {
            "id": "https://openalex.org/W123456789",
            "display_name": "Deep learning for dementia detection",
            "publication_year": 2026,
            "publication_date": "2026-10-22",
            "doi": "https://doi.org/10.1000/dementia.2026",
            "abstract_inverted_index": {"Deep": [0], "learning": [1], "helps": [2, 4], "detection": [3]},
            "authorships": [
                {"author": {"display_name": "Dan Wu"}},
                {"author": {"display_name": "Eve Chen"}},
            ],
            "primary_location": {"source": {"display_name": "J Alzheimer Stud"}},
        }
    ]
}

_S2_JSON = {
    "data": [
        {
            "paperId": "abc123def456",
            "title": "Reinforcement learning in robotics",
            "abstract": "We study RL for robot control.",
            "year": 2026,
            "publicationDate": "2026-10-21",
            "venue": "Robotics Conf",
            "url": "https://www.semanticscholar.org/paper/abc123def456",
            "authors": [{"name": "Frank Liu"}, {"name": "Grace Sun"}],
            "externalIds": {"DOI": "10.1000/rl.2026", "ArXiv": "2601.77777", "CorpusId": 777},
        },
        {
            "paperId": "old999",
            "title": "Ancient study",
            "year": 2020,
            "authors": [],
            "externalIds": {},
        },
    ]
}

_DOAJ_JSON = {
    "results": [
        {
            "id": "doaj-uuid-0001",
            "bibjson": {
                "title": "Open education in rural areas",
                "abstract": "We survey open education access.",
                "year": "2026",
                "author": [{"name": "Hannah Zhao"}],
                "identifier": [{"type": "doi", "id": "10.1000/edu.2026"}],
                "journal": {"title": "J Open Education"},
                "link": [{"url": "https://example.edu/article.pdf", "type": "fulltext"}],
            },
        },
        {
            "id": "doaj-uuid-old",
            "bibjson": {
                "title": "Legacy article",
                "year": "2019",
                "author": [],
            },
        },
    ]
}


def _patched_get(monkeypatch, routes: dict):
    """routes: {url 前缀: (status, payload dict | xml str)}；按 URL 前缀分发假响应。"""

    async def fake_get(self: httpx.AsyncClient, url, **kwargs):
        for prefix, (status, payload) in routes.items():
            if str(url).startswith(prefix):
                req = httpx.Request("GET", str(url))
                if isinstance(payload, str):
                    return httpx.Response(status, request=req, text=payload)
                return httpx.Response(status, request=req, json=payload)
        req = httpx.Request("GET", str(url))
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


async def test_arxiv_provider_parses_atom(monkeypatch):
    _patched_get(monkeypatch, {"https://export.arxiv.org/api/query": (200, _ARXIV_ATOM)})
    items = await ArxivProvider().search(["protein folding"], SINCE)
    assert len(items) == 1  # 10-10 的旧文被 since_date 过滤
    item = items[0]
    assert item.source == "arxiv"
    assert item.arxiv_id == "2601.12345"  # 版本号已剥
    assert item.external_id == "2601.12345"
    assert item.title == "Graph Neural Networks for Protein Folding"  # 空白已归一
    assert item.authors == ("Alice Zhang", "Bob Li")
    assert item.doi == "10.1000/gnn.2026"
    assert item.journal == "Test Conf 2026"
    assert item.pub_date == date(2026, 10, 25)
    assert item.url == "https://arxiv.org/abs/2601.12345"
    assert item.dedupe_keys[0] == "doi:10.1000/gnn.2026"  # doi 优先于 arxiv 键


async def test_openalex_provider_parses_works(monkeypatch):
    _patched_get(monkeypatch, {"https://api.openalex.org/works": (200, _OPENALEX_JSON)})
    items = await OpenAlexProvider().search(["dementia"], SINCE)
    assert len(items) == 1
    item = items[0]
    assert item.source == "openalex"
    assert item.external_id == "W123456789"
    assert item.doi == "10.1000/dementia.2026"  # 前缀已剥
    assert item.abstract == "Deep learning helps detection helps"  # 倒排索引已重建
    assert item.authors == ("Dan Wu", "Eve Chen")
    assert item.journal == "J Alzheimer Stud"
    assert item.pub_date == date(2026, 10, 22)
    assert item.year == 2026


async def test_semantic_scholar_provider_parses_papers(monkeypatch):
    _patched_get(
        monkeypatch, {"https://api.semanticscholar.org/graph/v1/paper/search": (200, _S2_JSON)}
    )
    items = await SemanticScholarProvider().search(["robotics"], SINCE)
    assert len(items) == 1  # 2020 旧文被过滤
    item = items[0]
    assert item.source == "semantic_scholar"
    assert item.external_id == "abc123def456"
    assert item.doi == "10.1000/rl.2026"
    assert item.arxiv_id == "2601.77777"
    assert item.authors == ("Frank Liu", "Grace Sun")
    assert item.journal == "Robotics Conf"
    assert item.pub_date == date(2026, 10, 21)


async def test_doaj_provider_parses_articles(monkeypatch):
    _patched_get(monkeypatch, {"https://doaj.org/api/search/articles": (200, _DOAJ_JSON)})
    items = await DoajProvider().search(["open education"], SINCE)
    assert len(items) == 1  # 2019 旧文被 year 过滤
    item = items[0]
    assert item.source == "doaj"
    assert item.external_id == "doaj-uuid-0001"
    assert item.doi == "10.1000/edu.2026"
    assert item.authors == ("Hannah Zhao",)
    assert item.journal == "J Open Education"
    assert item.year == 2026
    assert item.url == "https://example.edu/article.pdf"


def test_dedupe_items_cross_key():
    """去重优先级：doi > arxiv_id > external_id；同 doi 不同源的条目只留首条。"""
    a = PaperItem(title="A", source="arxiv", external_id="2601.1", arxiv_id="2601.1",
                  doi="10.1/x")
    b = PaperItem(title="B", source="openalex", external_id="W1", doi="10.1/X")  # 同 doi 大小写不同
    c = PaperItem(title="C", source="pubmed", external_id="900001")
    assert dedupe_items([a, b, c]) == [a, c]


def test_registry_lists_all_five_sources():
    keys = [p.name for p in list_providers()]
    assert keys == ["pubmed", "arxiv", "openalex", "semantic_scholar", "doaj"]
    assert DEFAULT_SOURCES == ("pubmed", "arxiv", "openalex")
    # 每个源都具备契约三件套
    for p in list_providers():
        assert isinstance(p.name, str) and p.name
        assert isinstance(p.display_name, str) and p.display_name


def test_resolve_sources_fallback_and_skip_unknown():
    assert [p.name for p in resolve_sources(None)] == list(DEFAULT_SOURCES)
    assert [p.name for p in resolve_sources([])] == list(DEFAULT_SOURCES)
    assert [p.name for p in resolve_sources(["doaj"])] == ["doaj"]
    # 未知 key 静默跳过，全无效回落默认
    assert [p.name for p in resolve_sources(["nope", "arxiv"])] == ["arxiv"]
    assert [p.name for p in resolve_sources(["nope"])] == list(DEFAULT_SOURCES)
    assert get_provider("pubmed") is not None
    assert get_provider("nope") is None


def test_openalex_abstract_reconstruction_empty():
    from app.services.sources.openalex import _reconstruct_abstract

    assert _reconstruct_abstract(None) == ""
    assert _reconstruct_abstract({}) == ""


def test_arxiv_parse_error_returns_empty():
    from app.services.sources.arxiv import _parse_atom

    assert _parse_atom("not xml at all", "kw") == []
