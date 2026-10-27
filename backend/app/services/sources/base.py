"""文献数据源契约（论文域步 A，契约冻结——学 skillhub.py 协议冻结模式）。

- SourceProvider 协议冻结为 name / display_name / search(keywords, since_date) 三件套，
  新增数据源只加实现不改契约，papers_crawl 管线零改动；
- PaperItem 为跨源统一题录结构（title/authors/abstract/year/doi/arxiv_id/url/source），
  另带 external_id（源内唯一 ID，入库去重主键）与 journal/pub_date（papers 表落库需要）；
- 所有实现：外部调用走共享 httpx 总机（http_client.py），瞬时错误由 tenacity 重试
  （retry.py 的 external_retry），4xx（除 429）不重试。
"""
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PaperItem:
    """跨源统一题录项（抓取结果的最小公共结构）。

    - source：源 key（pubmed/arxiv/openalex/semantic_scholar/doaj）；
    - external_id：源内唯一 ID（pmid / arXiv 编号 / OpenAlex W... / S2 paperId / DOAJ id），
      与 source 组合成 papers.pmid 列的全局去重键；
    - doi / arxiv_id：跨源去重键（小写归一后比较）；
    - year / pub_date：至少有一个非空（pub_date 优先，year 兜底建 date）。
    """

    title: str
    authors: tuple[str, ...] = ()
    abstract: str = ""
    year: int | None = None
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    source: str = ""
    external_id: str = ""
    journal: str = ""
    pub_date: date | None = None

    @property
    def dedupe_keys(self) -> tuple[str, ...]:
        """去重键优先级：doi > arxiv_id > source:external_id（全部小写归一）。"""
        keys: list[str] = []
        if self.doi:
            keys.append(f"doi:{self.doi.lower()}")
        if self.arxiv_id:
            keys.append(f"arxiv:{self.arxiv_id.lower()}")
        if self.source and self.external_id:
            keys.append(f"{self.source}:{self.external_id}".lower())
        return tuple(keys) if keys else ("",)


class SourceProvider(Protocol):
    """文献数据源只读契约：关键词检索最近文献。

    实现要求：
    - search 返回 since_date（含）以来发表的文献，按发表时间倒序优先；
    - 每关键词的抓取上限读 settings.papers_retmax，最近天数口径由调用方折算成
      since_date 传入（契约只认日期，不认天数）；
    - HTTP 层一律走 get_http_client() 并用 @external_retry() 装饰内部请求函数；
    - 任一关键词失败应向外抛 httpx.HTTPError（由调用方记日志跳过），
      不得静默吞掉整轮结果。
    """

    name: str
    display_name: str

    async def search(self, keywords: list[str], since_date: date) -> list[PaperItem]:
        """按关键词列表检索 since_date 以来的文献，合并去重后返回。"""
        ...


def dedupe_items(items: list[PaperItem]) -> list[PaperItem]:
    """源内/跨关键词按去重键保序去重（doi > arxiv_id > external_id，全小写归一）。"""
    seen: set[str] = set()
    out: list[PaperItem] = []
    for item in items:
        keys = [k for k in item.dedupe_keys if k]
        if any(k in seen for k in keys):
            continue
        seen.update(keys)
        out.append(item)
    return out
