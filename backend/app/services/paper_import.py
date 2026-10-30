"""文献导入服务（轮②，P25/P28）：PDF 上传 + arXiv ID / DOI 粘贴两路导入。

拍板 P25：一期导入形态 = ① PDF 上传（≤30MB，走 MinerU 解析状态机）② arXiv ID /
DOI 粘贴（自动拉元数据 + 下载 OA 全文 + 解析）；**下载失败必须通知用户**——
条目仍落库（papers.origin=import），接口返回明确失败信息，前端 toast 告知。
P30 解耦后细分：元数据失败 → parse_status=failed + parse_error（P25 原口径）；
全文下载失败 → fulltext_status=none + fulltext_error、parse_status 保持 none
且绝不自动触发解析（解析交给用户拿到文件后手动点），前端引导「可点[获取全文]
重试或[上传]本地文件」。

两路统一出口 :func:`import_to_library`：
1. 先建 papers 行（origin=import，owner=导入者本人 user_id，P23 行级隔离）+
   paper_users 归属 + paper_library 行（added_via=import）——**条目先于下载落库**，
   后续任何失败都落在「已存在的条目」上，不会出现失败即丢失；
2. identifier 路：拉元数据（arXiv Atom API / Crossref works）→ 写题录 →
   下载 OA 全文（arXiv 走其 pdf 直链；DOI 走 Unpaywall 最佳 OA 位置，与
   paper_parse 补链同一口径）；
3. 失败口径（P30 解耦后「导入成功」与「获取全文成败」分开展示）：
   - **元数据拉取失败**（题录都拿不到）：条目置 failed + 原因（P25 保留可重试），
     抛 :class:`ImportFailedError`；
   - **全文下载失败**（题录已落库，OA 全文拿不到）：条目保留、
     ``fulltext_status=none`` + ``fulltext_error`` 记真实原因、
     **parse_status 保持 none 且绝不自动触发解析**（解析是独立动作，用户拿到
     文件后手动点）——抛 :class:`ImportDownloadError`（路由层转「已添加但下载
     失败」响应，前端引导 [获取全文] 重试或 [上传] 本地文件）；
4. 全文就绪（PDF 路上传即就绪）→ 触发解析状态机
   （:func:`paper_parse.run_parse_pipeline` 的 pdf_bytes 通道：跳过 OA 下载步，
   阶段条从「上传」段起；Hatchet 事件分支先把 PDF 落 COS 再推事件，工作体
   只读 COS——存文件是导入自身职责，解析路绝不在解析时补下载）。

元数据口径：
- arXiv：export.arxiv.org/api/query?id_list=（官方 Atom，免费无密钥），题录取
  标题/作者/摘要/发布时间/arxiv 扩展 doi；落地页 = abs 页；
- DOI：api.crossref.org/works/{doi}（免费，带礼貌参数 mailto）；题录取
  title/container-title/issued/author/被引数；摘要为 JATS 片段，粗去标签
  （无摘要则为空串——不臆造）；落地页 = https://doi.org/{doi}。

去重键（papers.pmid 列，同用户内唯一）：arxiv:{id} / doi:{doi 小写} /
import:{uuid}（PDF 上传无外部键，uuid 占位）。同用户重复导入同一 arXiv/DOI
命中唯一索引 → ON CONFLICT 直返已有条目（幂等，不重复建行）。
"""
import base64
import binascii
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.papers import Paper, PaperLibrary, PaperUser
from app.services import paper_parse
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.sources.arxiv import ARXIV_NS, ATOM_NS

logger = logging.getLogger("lumencafe.papers")

IMPORT_MAX_FILENAME = 255  # 原始文件名长度上限（入库前截断）
_IMPORT_ERROR_MAX = 1000  # parse_error 入库截断长度（与 paper_parse 同口径）

# 标识符识别：arXiv 新旧编号（1601.00001 / 1601.00001v2）、带前缀、abs/pdf 链接；
# DOI（10.{registrant}/{suffix}，兼容 https://doi.org/ 前缀与大小写）
_ARXIV_ID_RE = re.compile(r"(?:^|\b)(\d{4}\.\d{4,5})(?:v\d+)?\b")
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"(?:^|doi\.org/)(10\.\d{4,9}/\S+)$", re.IGNORECASE)


class ImportInputError(ValueError):
    """导入请求本身不合法（格式/大小/内容非 PDF）——路由层转 422。"""


class ImportFailedError(RuntimeError):
    """元数据拉取失败：条目已落 failed 态，原因即异常消息。"""


class ImportDownloadError(ImportFailedError):
    """OA 全文下载失败：条目与题录已落库（origin=import），fulltext_error 记原因，
    parse_status 保持 none 且未触发解析——「已添加但自动下载全文失败」。"""


def classify_identifier(raw: str) -> tuple[str, str]:
    """识别粘贴内容：返回 (arxiv, 纯编号) | (doi, 规范化 doi)；识别不了抛 InputError。

    兼容形态：``2401.12345`` / ``2401.12345v3`` / ``arXiv:2401.12345`` /
    ``https://arxiv.org/abs/2401.12345`` / ``10.1000/xyz`` /
    ``https://doi.org/10.1000/xyz`` / 裸 doi 带 ``doi:`` 前缀。
    """
    text = (raw or "").strip()
    if not text:
        raise ImportInputError("请输入 arXiv ID 或 DOI")
    url_match = _ARXIV_URL_RE.search(text)
    if url_match:
        return "arxiv", url_match.group(1)
    id_match = _ARXIV_ID_RE.search(text)
    if id_match and ("arxiv" in text.lower() or re.fullmatch(
        r"arXiv\s*:?\s*\d{4}\.\d{4,5}(v\d+)?", text, re.IGNORECASE
    ) or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", text)):
        return "arxiv", id_match.group(1)
    doi_text = text
    if doi_text.lower().startswith("doi:"):
        doi_text = doi_text[4:].strip()
    doi_text = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi_text, flags=re.IGNORECASE).strip()
    doi_match = re.fullmatch(r"10\.\d{4,9}/\S+", doi_text, re.IGNORECASE)
    if doi_match:
        return "doi", doi_text.lower()
    raise ImportInputError(
        "无法识别的标识符：支持 arXiv ID（如 2401.12345）或 DOI（如 10.1000/xyz）"
    )


def decode_pdf_base64(b64: str) -> bytes:
    """前端 FileReader dataURL 的 base64 段 → bytes；非法/超限抛 ImportInputError。"""
    cleaned = (b64 or "").split(",")[-1].strip()  # 兼容整段 dataURL 传入
    if not cleaned:
        raise ImportInputError("PDF 内容为空")
    try:
        data = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImportInputError("PDF 内容不是合法的 base64 编码") from exc
    if len(data) > paper_parse.MAX_PDF_BYTES:
        raise ImportInputError(
            f"PDF 超过 {paper_parse.MAX_PDF_BYTES // (1024 * 1024)}MB 上限，"
            "请压缩后重新上传"
        )
    return data


def title_from_filename(filename: str) -> str:
    """元数据从文件名起表（拍板轮②）：去路径/扩展名，_ - 折空格，首字母不动。"""
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.pdf$", "", base, flags=re.IGNORECASE).strip()
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem[:512] or "导入的 PDF 文献"


# ── 元数据拉取（arXiv Atom / Crossref）────────────────────
def _atom_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.text or "").strip()


@external_retry()
async def _fetch_arxiv_atom(client: httpx.AsyncClient, arxiv_id: str) -> str:
    """arXiv 官方 Atom API 按 id 查元数据（免费无密钥）。"""
    resp = await client.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id},
    )
    resp.raise_for_status()
    return resp.text


async def fetch_arxiv_metadata(client: httpx.AsyncClient, arxiv_id: str) -> dict:
    """arXiv ID → 题录字典（title/authors/abstract/pub_date/doi/url）。"""
    xml_text = await _fetch_arxiv_atom(client, arxiv_id)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ImportFailedError(f"arXiv 元数据响应无法解析：{exc}") from exc
    entry = root.find(f"{ATOM_NS}entry")
    if entry is None:
        raise ImportFailedError(f"arXiv 未找到该文献（id={arxiv_id}），请核对编号")
    if entry.find(f"{ATOM_NS}title") is not None and "Error" in _atom_text(
        entry.find(f"{ATOM_NS}title")
    ):
        raise ImportFailedError(f"arXiv 未找到该文献（id={arxiv_id}），请核对编号")
    published = _atom_text(entry.find(f"{ATOM_NS}published"))[:10]
    pub_date: date | None = None
    try:
        pub_date = date.fromisoformat(published) if published else None
    except ValueError:
        pub_date = None
    authors = [
        _atom_text(a.find(f"{ATOM_NS}name"))
        for a in entry.findall(f"{ATOM_NS}author")
        if _atom_text(a.find(f"{ATOM_NS}name"))
    ]
    abstract = _atom_text(entry.find(f"{ATOM_NS}summary"))
    return {
        "title": _atom_text(entry.find(f"{ATOM_NS}title")) or f"arXiv:{arxiv_id}",
        "authors": authors,
        "abstract": abstract,
        "journal": _atom_text(entry.find(f"{ARXIV_NS}journal_ref")),
        "pub_date": pub_date,
        "doi": (_atom_text(entry.find(f"{ARXIV_NS}doi")) or "").lower() or None,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
    }


@external_retry()
async def _fetch_crossref_works(client: httpx.AsyncClient, doi: str) -> dict:
    """Crossref works 单条查询（免费 API，mailto 礼貌参数）。"""
    resp = await client.get(
        f"https://api.crossref.org/works/{doi}",
        params={"mailto": paper_parse.UNPAYWALL_EMAIL},
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise ImportFailedError("Crossref 响应结构异常（缺 message）")
    return data["message"]


def _crossref_date(parts: object) -> date | None:
    """Crossref date-parts（[[y,m,d],...]）→ date；缺月日折算 1 日。"""
    if isinstance(parts, dict):
        inner = parts.get("date-parts")
        if isinstance(inner, list) and inner and isinstance(inner[0], list) and inner[0]:
            seq = inner[0]
            try:
                return date(int(seq[0]), int(seq[1]) if len(seq) > 1 else 1,
                            int(seq[2]) if len(seq) > 2 else 1)
            except (TypeError, ValueError):
                return None
    return None


def _strip_jats(text: str) -> str:
    """Crossref 摘要为 JATS XML 片段：粗去标签取纯文本（不完美但够用）。"""
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", plain).strip()


async def fetch_crossref_metadata(client: httpx.AsyncClient, doi: str) -> dict:
    """DOI → Crossref 题录（title/authors/abstract/journal/pub_date/cited/url）。"""
    try:
        msg = await _fetch_crossref_works(client, doi)
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise ImportFailedError(f"Crossref 未找到该 DOI（{doi}），请核对") from exc
        raise ImportFailedError(f"Crossref 元数据查询失败：{exc}") from exc
    title = ""
    if isinstance(msg.get("title"), list) and msg["title"]:
        title = str(msg["title"][0]).strip()
    journal = ""
    if isinstance(msg.get("container-title"), list) and msg["container-title"]:
        journal = str(msg["container-title"][0]).strip()
    authors = []
    for a in msg.get("author") or []:
        if isinstance(a, dict):
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
    cited = msg.get("is-referenced-by-count")
    return {
        "title": title or f"doi:{doi}",
        "authors": authors,
        "abstract": _strip_jats(str(msg.get("abstract") or "")),
        "journal": journal,
        "pub_date": _crossref_date(msg.get("issued")),
        "doi": doi,
        "url": f"https://doi.org/{doi}",
        "cited_count": int(cited) if isinstance(cited, int) else None,
    }


async def resolve_doi_pdf_url(client: httpx.AsyncClient, doi: str) -> str:
    """DOI → OA 全文 pdf 直链（Unpaywall 最佳位置，与 paper_parse 补链同口径）。"""
    try:
        return await paper_parse._unpaywall_pdf_url(client, doi)
    except Exception as exc:
        raise ImportFailedError(str(exc) or "Unpaywall 未收录开放获取全文") from exc


# ── 入库（条目先行：papers 行 + 归属 + 库行，失败也保留）────
async def _create_import_row(
    db: AsyncSession, user_id: int, dedupe_key: str, source: str, title: str
) -> tuple[Paper, bool]:
    """建导入条目（ON CONFLICT 幂等直返已有行）：origin=import + 归属 + 库行。

    返回 (paper, 是否新建)；已存在（同用户重复导入同一 arXiv/DOI）时不重复建行。
    """
    stmt = (
        pg_insert(Paper)
        .values(
            pmid=dedupe_key,
            user_id=user_id,
            origin="import",
            source=source,  # import（PDF）| arxiv | doi
            title=title,
            parse_status="pending",
        )
        .on_conflict_do_nothing(index_elements=["user_id", "pmid"])
    )
    result = await db.execute(stmt)
    paper = (
        await db.execute(
            select(Paper).where(Paper.user_id == user_id, Paper.pmid == dedupe_key)
        )
    ).scalar_one()
    await db.execute(
        pg_insert(PaperUser)
        .values(paper_id=paper.id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["paper_id", "user_id"])
    )
    await db.execute(
        pg_insert(PaperLibrary)
        .values(paper_id=paper.id, user_id=user_id, added_via="import")
        .on_conflict_do_nothing(index_elements=["user_id", "paper_id"])
    )
    await db.commit()
    return paper, bool(result.rowcount)


async def _mark_import_failed(db: AsyncSession, paper: Paper, reason: str) -> None:
    """导入失败：条目落 failed 态 + 原因（P25：失败保留可重试），原因截断入库。"""
    paper.parse_status = "failed"
    paper.parse_error = reason[:_IMPORT_ERROR_MAX]
    await db.commit()


# ── 对外入口 ─────────────────────────────────────────────
async def import_pdf(db: AsyncSession, user_id: int, filename: str, data: bytes) -> Paper:
    """PDF 上传导入：落库（元数据从文件名起表）→ 状态机（阶段条从「上传」起）。"""
    if len(data) > paper_parse.MAX_PDF_BYTES:
        raise ImportInputError(
            f"PDF 超过 {paper_parse.MAX_PDF_BYTES // (1024 * 1024)}MB 上限，请压缩后上传"
        )
    try:
        paper_parse._ensure_pdf(data, "上传文件")
    except paper_parse.PdfDownloadError as exc:
        raise ImportInputError(str(exc)) from exc
    safe_name = (filename or "imported.pdf").replace("\\", "/").rsplit("/", 1)[-1][
        :IMPORT_MAX_FILENAME
    ]
    paper, _created = await _create_import_row(
        db, user_id, f"import:{uuid.uuid4().hex[:20]}", "import",
        title_from_filename(safe_name),
    )
    if paper.parse_status == "done":
        return paper  # 幂等：同键已解析完成（理论上 uuid 不撞，防御）
    paper.fulltext_status = "uploaded"  # P30：PDF 上传即全文就绪（上传动作）
    await db.commit()
    logger.info("PDF 导入：paper_id=%s user_id=%s（%d bytes）", paper.id, user_id, len(data))
    await run_import_pipeline(db, paper.id, user_id, data)
    return paper


async def import_identifier(db: AsyncSession, user_id: int, raw: str) -> Paper:
    """arXiv ID / DOI 粘贴导入：拉元数据 → 写题录 → 下载 OA 全文 → 状态机。

    失败口径（P30 解耦，见模块 docstring）：
    - 元数据拉取失败 → 条目落 failed 态 + 原因（P25 保留可重试），
      抛 :class:`ImportFailedError`；
    - 全文下载失败（含 DOI 路 Unpaywall 无 OA 位置）→ 题录保留、
      ``fulltext_status=none`` + ``fulltext_error`` 记原因、
      **parse_status 归 none 且绝不触发解析**，抛 :class:`ImportDownloadError`
      （路由层转「已添加但自动下载全文失败」响应）。
    """
    kind, ident = classify_identifier(raw)
    client = get_http_client()
    dedupe_key = f"{kind}:{ident}"
    paper, _created = await _create_import_row(db, user_id, dedupe_key, kind, f"{kind}:{ident}")
    if paper.parse_status == "done":
        return paper  # 幂等：同用户重复导入同一 arXiv/DOI，已完成则直返不重跑

    # 阶段一：元数据（题录拿不到 = 条目无意义 → P25 failed 态）
    try:
        if kind == "arxiv":
            meta = await fetch_arxiv_metadata(client, ident)
        else:
            meta = await fetch_crossref_metadata(client, ident)
    except ImportFailedError as exc:
        await _mark_import_failed(db, paper, str(exc))  # P25：元数据失败落 failed 态
        raise
    except Exception as exc:
        reason = f"元数据拉取失败：{str(exc) or exc.__class__.__name__}"
        logger.warning("导入元数据失败（%s）：%s", dedupe_key, reason)
        await _mark_import_failed(db, paper, reason)
        raise ImportFailedError(reason) from exc

    for col, value in meta.items():
        setattr(paper, col, value)
    await db.commit()

    # 阶段二：OA 全文（arXiv pdf 直链 / DOI 走 Unpaywall 补链后下载——
    # 拿不到 ≠ 解析失败，与解析解耦展示）
    try:
        if kind == "arxiv":
            pdf_url = f"https://arxiv.org/pdf/{ident}"
        else:
            pdf_url = await resolve_doi_pdf_url(client, ident)
        data = await paper_parse._fetch_bytes(client, pdf_url)
        paper_parse._ensure_pdf(data, f"OA 全文 {pdf_url}")
    except Exception as exc:
        reason = (f"全文下载失败：{str(exc) or exc.__class__.__name__}")[
            : paper_parse._FULLTEXT_ERROR_MAX
        ]
        paper.fulltext_status = "none"
        paper.fulltext_error = reason
        paper.parse_status = "none"  # 绝不在无文件时触发解析（解析 = 独立动作）
        paper.parse_error = None
        await db.commit()
        logger.warning("导入全文下载失败（%s）：%s", dedupe_key, reason)
        raise ImportDownloadError(reason) from exc

    logger.info("标识符导入：paper_id=%s（%s:%s，%d bytes）", paper.id, kind, ident, len(data))
    paper.fulltext_status = "oa"  # P30：OA 全文已下载就绪（获取全文动作等价物）
    await db.commit()
    await run_import_pipeline(db, paper.id, user_id, data)
    return paper


async def run_import_pipeline(
    db: AsyncSession, paper_id: int, user_id: int, pdf_bytes: bytes
) -> dict:
    """导入条目触发解析状态机（pdf_bytes 通道：跳过 OA 下载步）。

    事件分支先把 PDF 落 COS 再推 Hatchet 事件——事件只带 (paper_id, user_id)，
    工作体按 collect-parse 同口径从 COS 读全文（P30：存文件是导入自身职责，
    解析路绝不在解析时补下载；早前「事件丢 pdf_bytes → 工作体回落下载路 →
    导入行无 url/doi 报『该文献无可用全文链接』且误标解析失败」即此断裂）。
    Hatchet 未接线时进程内同步执行（与 collect-parse 同一哲学，用户要的是
    结果可达）；进程内路径 run_parse_pipeline(pdf_bytes=...) 内部同键再存
    一遍（幂等覆盖）。
    """
    from app.services import pipeline  # 延迟导入：pipeline 反向加载 papers_crawl，防环

    # 先落 COS 再推事件（顺序即正确性）：事件只带 (paper_id, user_id)，worker
    # 拿到事件立即 run_parse_pipeline(pdf_bytes=None) 从 COS 读——若先推后存，
    # worker 与 store 竞速，find_pdf_key 扑空即误标解析失败（竞态窗口）。
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()
    storage = await paper_parse.get_storage(db)
    await paper_parse.store_pdf(storage, paper, pdf_bytes)

    if pipeline.push_parse_event(paper_id, user_id):
        return {"paper_id": paper_id, "parse_status": "pending", "parse_error": None}
    # 引擎未接线/推送失败：进程内同步执行；run_parse_pipeline(pdf_bytes=...)
    # 内部同键再存一遍（幂等覆盖，无害）
    return await paper_parse.run_parse_pipeline(db, paper_id, user_id, pdf_bytes=pdf_bytes)


__all__ = [
    "ImportDownloadError",
    "ImportFailedError",
    "ImportInputError",
    "classify_identifier",
    "decode_pdf_base64",
    "fetch_arxiv_metadata",
    "fetch_crossref_metadata",
    "import_identifier",
    "import_pdf",
    "resolve_doi_pdf_url",
    "title_from_filename",
]
