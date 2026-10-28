"""文献数据源市场编目（P17：源目录全量编目，docs/论文数据源目录-v1.md 的代码化子集）。

- 市场清单 = 本编目（全部条目，含未实现源）× 注册表（已实现源）合并：
  implemented 以注册表为准，未实现源只展示不可勾选（前端徽标「待接入」）；
- cost 三态：free（免费直接用）/ free_key（免费但需申请 key）/ paid（收费或订阅）；
- key_service 指向 service_keys 表的服务名（已实现的 openalex/semantic_scholar 即按此
  取匙注入请求头）；未实现源的 key_service 预留给后续批次接入时沿用；
- 新增「已接入」源：注册表加一行 + 本编目对应条目 implemented 由注册表推导为 True。
"""
from dataclasses import dataclass

# 分类常量（拍板 P17 七分类）
CAT_GENERAL = "综合索引"
CAT_BIOMED = "生物医学"
CAT_ENG = "理工"
CAT_SOCIAL = "社科人文"
CAT_CN = "中文国内"
CAT_PAID = "商业收费"
CAT_OA = "开放期刊"

# 费用三态
COST_FREE = "free"
COST_FREE_KEY = "free_key"
COST_PAID = "paid"


@dataclass(frozen=True)
class SourceCatalogEntry:
    """市场编目条目（展示与引导用，不参与抓取调度）。"""

    key: str  # 源 key（与注册表 provider.name 对齐；未实现源为预留 key）
    name: str  # 展示名
    category: str  # 七分类之一
    cost: str  # free / free_key / paid
    key_service: str | None  # key 表服务名（cost=free 为 None）
    description: str  # 一句话说明（市场展示）


# 编目顺序 = 市场展示顺序：已接 5 源在前（按注册表顺序），其余按分类分组
SOURCE_CATALOG: tuple[SourceCatalogEntry, ...] = (
    # ── 已接入（与 _REGISTRY 的 5 源一一对应） ──
    SourceCatalogEntry(
        key="pubmed", name="PubMed（生物医学）", category=CAT_BIOMED, cost=COST_FREE,
        key_service=None, description="NCBI 生物医学 3600 万+ 权威题录，每日抓取默认源",
    ),
    SourceCatalogEntry(
        key="arxiv", name="arXiv（预印本）", category=CAT_ENG, cost=COST_FREE,
        key_service=None, description="物理/数学/CS 预印本 240 万+，新成果首发阵地",
    ),
    SourceCatalogEntry(
        key="openalex", name="OpenAlex（全学科）", category=CAT_GENERAL,
        cost=COST_FREE_KEY, key_service="openalex",
        description="全学科 3 亿+ 作品索引；配免费 key 额度提升约 10 倍（$1/天免费额度）",
    ),
    SourceCatalogEntry(
        key="semantic_scholar", name="Semantic Scholar（全学科）", category=CAT_GENERAL,
        cost=COST_FREE_KEY, key_service="semantic_scholar",
        description="AI 驱动全学科 2 亿+；匿名池限流激进，配 key 显著提速",
    ),
    SourceCatalogEntry(
        key="doaj", name="DOAJ（开放获取期刊）", category=CAT_OA, cost=COST_FREE,
        key_service=None, description="开放获取期刊白名单 2 万+ 期刊、900 万+ 文章",
    ),
    # ── 综合索引（待接入） ──
    SourceCatalogEntry(
        key="crossref", name="Crossref", category=CAT_GENERAL, cost=COST_FREE,
        key_service=None, description="DOI 元数据权威底座，补全题录与引用数交叉验证",
    ),
    SourceCatalogEntry(
        key="core", name="CORE", category=CAT_GENERAL, cost=COST_FREE,
        key_service=None, description="开放获取全文最强免费源，5700 万+ OA 全文直链",
    ),
    SourceCatalogEntry(
        key="base", name="BASE（比勒菲尔德学术搜索）", category=CAT_GENERAL,
        cost=COST_FREE_KEY, key_service="base",
        description="全球机构库 OA 覆盖 4 亿+，免费注册凭证接入",
    ),
    # ── 生物医学（待接入） ──
    SourceCatalogEntry(
        key="europe_pmc", name="Europe PMC", category=CAT_BIOMED, cost=COST_FREE,
        key_service=None, description="PubMed 超集：PMC 全文+预印本+专利，免费 10 req/s",
    ),
    SourceCatalogEntry(
        key="biorxiv_medrxiv", name="bioRxiv / medRxiv", category=CAT_BIOMED,
        cost=COST_FREE, key_service=None,
        description="生命科学/医学预印本，补「预印本→正式发表」链路",
    ),
    SourceCatalogEntry(
        key="embase", name="Embase", category=CAT_BIOMED, cost=COST_PAID,
        key_service="embase", description="Elsevier 深度标引生物医学库，需机构订阅启用",
    ),
    SourceCatalogEntry(
        key="cochrane", name="Cochrane Library", category=CAT_BIOMED, cost=COST_PAID,
        key_service="cochrane", description="循证医学系统综述与临床试验，API 随订阅提供",
    ),
    # ── 理工（待接入） ──
    SourceCatalogEntry(
        key="dblp", name="dblp", category=CAT_ENG, cost=COST_FREE,
        key_service=None, description="计算机科学会议/期刊题录权威，790 万+ 作者消歧",
    ),
    SourceCatalogEntry(
        key="ieee_xplore", name="IEEE Xplore", category=CAT_ENG, cost=COST_FREE_KEY,
        key_service="ieee_xplore", description="电子电气/CS 期刊会议标准，免费 key 约 200 次/天",
    ),
    SourceCatalogEntry(
        key="nasa_ads", name="NASA ADS", category=CAT_ENG, cost=COST_FREE_KEY,
        key_service="nasa_ads", description="天文/物理/地球物理 1600 万+，免费 token 5000 次/天",
    ),
    # ── 社科人文（待接入） ──
    SourceCatalogEntry(
        key="ssrn", name="SSRN", category=CAT_SOCIAL, cost=COST_FREE,
        key_service=None, description="社科/经济/法/商预印本 200 万+ 全文，网页跳转源",
    ),
    SourceCatalogEntry(
        key="repec", name="RePEc / IDEAS", category=CAT_SOCIAL, cost=COST_FREE,
        key_service=None, description="经济学工作论文（NBER/CEPR 等）最全免费源",
    ),
    # ── 中文国内（待接入） ──
    SourceCatalogEntry(
        key="cnki", name="中国知网（CNKI）", category=CAT_CN, cost=COST_PAID,
        key_service="cnki", description="亿级中文题录；推荐官网导出题录文件导入形态",
    ),
    SourceCatalogEntry(
        key="aminer", name="AMiner（智谱）", category=CAT_CN, cost=COST_FREE_KEY,
        key_service="aminer", description="中英双语 3 亿+ 论文 API，按次计费极低价（0.01 元/次）",
    ),
    # ── 商业收费（待接入，配 key/订阅即用） ──
    SourceCatalogEntry(
        key="scopus", name="Scopus（Elsevier）", category=CAT_PAID, cost=COST_PAID,
        key_service="scopus", description="全学科 2.5 亿+，机构订阅用户配 key 即用",
    ),
    SourceCatalogEntry(
        key="web_of_science", name="Web of Science", category=CAT_PAID,
        cost=COST_FREE_KEY, key_service="web_of_science",
        description="Clarivate 核心合集；Starter 免费档 50 req/ 天，影响因子官方数据源",
    ),
    SourceCatalogEntry(
        key="springer_nature", name="Springer Nature", category=CAT_PAID,
        cost=COST_FREE_KEY, key_service="springer_nature",
        description="Meta API 免费 500 次/天，元数据+OA 全文 JATS",
    ),
)


def catalog_index() -> dict[str, SourceCatalogEntry]:
    """key → 编目条目的索引（/papers/sources 合并注册表用）。"""
    return {e.key: e for e in SOURCE_CATALOG}
