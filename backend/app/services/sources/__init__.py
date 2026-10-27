"""文献数据源注册表（论文域步 A，契约冻结——加源只动这里，管线零改动）。

- _REGISTRY 集中登记全部 SourceProvider 实现（key = provider.name）；
- get_provider / list_providers 是 papers_crawl 与 /papers/sources 的唯一取源入口；
- DEFAULT_SOURCES：用户未配置 subscribe_sources 时的默认勾选（PubMed + arXiv + OpenAlex，
  拍板 P2：全官方免费 API；S2/DOAJ 默认不勾，防免费档限流拖累每日抓取）。

新增数据源步骤：在 sources/ 下实现 SourceProvider 契约 → 在 _REGISTRY 注册一行，
papers_crawl 聚合、/papers/sources 清单、前端勾选框全部自动生效。
"""
from app.services.sources.arxiv import ArxivProvider
from app.services.sources.base import PaperItem, SourceProvider, dedupe_items
from app.services.sources.doaj import DoajProvider
from app.services.sources.openalex import OpenAlexProvider
from app.services.sources.pubmed import PubMedProvider
from app.services.sources.semantic_scholar import SemanticScholarProvider

__all__ = [
    "DEFAULT_SOURCES",
    "PaperItem",
    "SourceProvider",
    "dedupe_items",
    "get_provider",
    "list_providers",
    "resolve_sources",
]

# 用户未配置 subscribe_sources 时的默认勾选源（拍板 P2）
DEFAULT_SOURCES: tuple[str, ...] = ("pubmed", "arxiv", "openalex")

_REGISTRY: dict[str, SourceProvider] = {
    p.name: p
    for p in (
        PubMedProvider(),
        ArxivProvider(),
        OpenAlexProvider(),
        SemanticScholarProvider(),
        DoajProvider(),
    )
}


def get_provider(name: str) -> SourceProvider | None:
    """按 key 取源；未注册返回 None（调用方跳过并记日志）。"""
    return _REGISTRY.get(name)


def list_providers() -> list[SourceProvider]:
    """全部已注册源（/papers/sources 清单用，注册顺序即展示顺序）。"""
    return list(_REGISTRY.values())


def resolve_sources(names: list[str] | None) -> list[SourceProvider]:
    """把用户勾选的源 key 列表解析为 provider 列表。

    未配置/全无效 → 回落 DEFAULT_SOURCES；部分无效 key 静默跳过（前端正则约束外兜底）。
    """
    if not names:
        names = list(DEFAULT_SOURCES)
    out: list[SourceProvider] = []
    for name in names:
        provider = _REGISTRY.get(str(name).strip().lower())
        if provider is not None and provider not in out:
            out.append(provider)
    if not out:
        out = [_REGISTRY[n] for n in DEFAULT_SOURCES]
    return out
