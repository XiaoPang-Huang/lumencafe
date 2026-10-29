"""收藏并解析全链路（P16/P20）：下载 OA 全文 → 存 COS papers/ → MinerU 精准解析 → 状态机。

链路四步（Hatchet workflow papers-parse 与进程内降级共用
:func:`run_parse_pipeline`，入口幂等语义一致）：

- :func:`download_oa_pdf`：优先 ``paper.url`` 直链（arXiv abs 页自动改 pdf 直链），
  失败/内容非 PDF 走 Unpaywall 补链（doi → OA pdf url；免费 API 只需 email 参数）。
  共享 httpx 总机下载，30MB 上限流式强制，tenacity 瞬时重试（retry.py 预设，
  4xx/非 PDF 不重试）；返回 ``(pdf_bytes, source)``，source ∈ direct|unpaywall。
- :func:`store_pdf`：原始 PDF 落 ``papers/pdfs/{yyyy}/{mm}/{paper_id}.pdf``（P20 年月分层）。
- :func:`mineru_parse`：MinerU 精准解析 API（service_keys ``mineru`` 行 Bearer token，
  base_url 已填 https://mineru.net/api/v4）。文件上传流：
  ``POST /file-urls/batch`` 取签名直传地址 → ``PUT`` 上传 PDF →
  ``POST /extract/task``（model_version=vlm）建任务 → 轮询 ``GET /extract/task/{task_id}``
  （state: pending/running/done/failed，done 拿 full_zip_url）→ 下载 zip。
- :func:`store_parsed`：zip 拆存（P20）：``papers/parsed/{id}/full.md`` +
  ``content_list.json``（批注锚点/问答引用的根基）+ ``meta.json``
  （model_version/页数/解析时间；页数优先取 MinerU _meta.json 的 page_size，
  不可得从 content_list.json 的 page_idx 推断，再不可得留 null）。

状态机写 ``papers.parse_status``：none → pending → running → done | failed
（``parse_error`` 记原因，前端错误区可见）。幂等（拍板：重试 = 再次点按钮）：
done 不再跑；pending/running 拒绝重入（API 409）；failed/none 可全链重跑。
存储全经 storage 抽象层 ``"papers"`` app——{app}/ 前缀硬隔离（P11），
COS key 恒 ``papers/`` 开头。
"""
import asyncio
import io
import json
import logging
import zipfile
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.papers import Paper
from app.services import paper_translate
from app.services.http_client import get_http_client
from app.services.retry import external_retry
from app.services.service_keys import get_key
from app.services.storage import Storage, get_storage

logger = logging.getLogger("lumencafe.paper_parse")

# ── 常量（显式声明，不依赖隐式默认）──
MAX_PDF_BYTES = 30 * 1024 * 1024  # 全文下载上限 30MB（流式强制，超限即失败）
UNPAYWALL_EMAIL = "lumencafe@local"  # Unpaywall 免费 API 的礼貌参数（mailto 口径）
MINERU_SERVICE_KEY = "mineru"  # service_keys 服务名（行内存 Bearer token）
MINERU_DEFAULT_BASE = "https://mineru.net/api/v4"
MINERU_MODEL_VERSION = "vlm"  # 精准解析模型版本（拍板 P16）
MINERU_POLL_INTERVAL = 3.0  # 任务轮询间隔（秒）
MINERU_POLL_TIMEOUT = 600.0  # 任务轮询总超时（秒，排队+解析给足余量）
_PDF_MAGIC = b"%PDF-"  # PDF 魔数：直链/补链内容校验（HTML 落地页不算全文）
_PARSE_ERROR_MAX = 1000  # parse_error 入库截断长度（Text 列，防异常消息爆炸）


class PdfDownloadError(RuntimeError):
    """OA 全文下载失败（直链与 Unpaywall 补链均不可用/内容非法）。"""


class MinerUConfigError(RuntimeError):
    """MinerU 未配置（service_keys 无启用中的 mineru 行）——响亮报错引导配置。"""


class MinerUError(RuntimeError):
    """MinerU 解析链路失败（建任务/轮询/产物不合法）。"""


class ParseAlreadyRunning(RuntimeError):
    """该文献已在解析中（pending/running），拒绝重入。"""


# ── 下载：直链 → Unpaywall 补链 ───────────────────────────
def _arxiv_pdf_url(url: str) -> str:
    """arXiv abs 落地页 → pdf 直链（abs 页是 HTML，下载会撞魔数校验）。"""
    if "/abs/" in url:
        return url.replace("/abs/", "/pdf/", 1)
    return url


def _ensure_pdf(data: bytes, where: str) -> None:
    """内容魔数校验：不是 PDF 即失败（触发补链或整体失败）。"""
    if not data.startswith(_PDF_MAGIC):
        raise PdfDownloadError(f"{where} 返回的不是 PDF 内容")


@external_retry()
async def _fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    """带重试的直下载（仅瞬时错误重试，见 retry.py；30MB 流式上限强制）。"""
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_bytes(65536):
            total += len(chunk)
            if total > MAX_PDF_BYTES:
                raise PdfDownloadError(
                    f"PDF 超过 {MAX_PDF_BYTES // (1024 * 1024)}MB 上限，已中止下载"
                )
            chunks.append(chunk)
    return b"".join(chunks)


@external_retry()
async def _unpaywall_pdf_url(client: httpx.AsyncClient, doi: str) -> str:
    """doi → Unpaywall OA 全文链接（best → first，优先 url_for_pdf）。"""
    resp = await client.get(
        f"https://api.unpaywall.org/v2/{doi}", params={"email": UNPAYWALL_EMAIL}
    )
    resp.raise_for_status()
    data = resp.json()
    for loc_key in ("best_oa_location", "first_oa_location"):
        loc = data.get(loc_key)
        if isinstance(loc, dict):
            pdf_url = loc.get("url_for_pdf") or loc.get("url")
            if pdf_url:
                return str(pdf_url)
    raise PdfDownloadError("Unpaywall 未收录该文献的开放获取全文链接")


async def download_oa_pdf(db: AsyncSession, paper: Paper) -> tuple[bytes, str]:
    """下载 OA 全文：优先 ``paper.url`` 直链，失败走 Unpaywall 补链。

    返回 ``(pdf_bytes, source)``；source = direct（直链成功）| unpaywall（补链成功）。
    双通道均失败抛出 :class:`PdfDownloadError`（原因拼接，前端错误区展示）。
    """
    client = get_http_client()
    errors: list[str] = []

    if paper.url:
        direct_url = _arxiv_pdf_url(paper.url) if paper.source == "arxiv" else paper.url
        try:
            data = await _fetch_bytes(client, direct_url)
            _ensure_pdf(data, f"直链 {direct_url}")
            return data, "direct"
        except Exception as exc:  # noqa: BLE001 - 补链兜底，原因汇总后外抛
            reason = str(exc) or exc.__class__.__name__
            errors.append(f"直链下载失败：{reason}")
            logger.warning("paper_id=%s 直链下载失败：%s", paper.id, reason)

    doi = (paper.doi or "").replace("https://doi.org/", "").strip()
    if doi:
        try:
            oa_url = await _unpaywall_pdf_url(client, doi)
            data = await _fetch_bytes(client, oa_url)
            _ensure_pdf(data, f"Unpaywall {oa_url}")
            return data, "unpaywall"
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or exc.__class__.__name__
            errors.append(f"Unpaywall 补链失败：{reason}")
            logger.warning("paper_id=%s Unpaywall 补链失败：%s", paper.id, reason)

    raise PdfDownloadError("；".join(errors) or "该文献无可用全文链接（无 url/doi）")


# ── 存储：原始 PDF + 解析产物（P20 目录结构）────────────────
def pdf_object_key(paper_id: int, now: datetime | None = None) -> str:
    """P20：pdfs/{yyyy}/{mm}/{paper_id}.pdf（年月分层；app 前缀由存储层补）。"""
    t = now or datetime.now().astimezone()
    return f"pdfs/{t.year:04d}/{t.month:02d}/{paper_id}.pdf"


async def store_pdf(storage: Storage, paper: Paper, data: bytes) -> str:
    """原始 PDF 落存储（app=papers，最终 key 恒 papers/pdfs/...）。"""
    key = pdf_object_key(paper.id)
    await storage.put("papers", key, data)
    logger.info("paper_id=%s PDF 已存储：papers/%s（%d bytes）", paper.id, key, len(data))
    return key


def _find_zip_member(names: list[str], basename: str) -> str | None:
    """zip 内按文件名定位成员。

    MinerU 产物两种命名都见过（2026-10-29 真实复测）：裸名 ``content_list.json``
    与带任务前缀的 ``{uuid}_content_list.json``——后者 basename 以 ``_ + 目标名``
    结尾。两种都认；外层目录包裹不影响（只比 basename）。
    """
    for name in names:
        base = name.rstrip("/").split("/")[-1]
        if base == basename or base.endswith("_" + basename):
            return name
    return None


async def store_parsed(
    storage: Storage, paper_id: int, zip_bytes: bytes, model_version: str
) -> dict:
    """MinerU zip 拆存（P20）：parsed/{id}/full.md + content_list.json + meta.json。

    返回 {"page_count": int|None, "keys": [三个对象 key（不含 app 前缀）]}。
    产物缺 full.md/content_list.json 视为解析失败（:class:`MinerUError`）。
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU 返回的解析产物不是合法 zip") from exc
    names = [n for n in zf.namelist() if not n.endswith("/")]
    full_name = _find_zip_member(names, "full.md")
    content_name = _find_zip_member(names, "content_list.json")
    if not full_name or not content_name:
        raise MinerUError(
            f"解析产物不完整（缺 full.md/content_list.json）：{names[:10]}"
        )
    full_md = zf.read(full_name)
    content_list = zf.read(content_name)

    # 页数：优先 MinerU _meta.json 的 page_size，回落 content_list.json page_idx 推断
    page_count: int | None = None
    meta_name = _find_zip_member(names, "_meta.json") or _find_zip_member(names, "meta.json")
    if meta_name:
        try:
            src_meta = json.loads(zf.read(meta_name))
            if isinstance(src_meta.get("page_size"), int):
                page_count = src_meta["page_size"]
        except (ValueError, TypeError):
            page_count = None  # 元数据损坏不阻断主产物
    if page_count is None:
        try:
            items = json.loads(content_list)
            pages = [
                it["page_idx"]
                for it in items
                if isinstance(it, dict) and isinstance(it.get("page_idx"), int)
            ]
            if pages:
                page_count = max(pages) + 1
        except (ValueError, TypeError):
            page_count = None  # 推断不可得则省（拍板 P20：不可得省）

    meta_out = {
        "paper_id": paper_id,
        "model_version": model_version,
        "page_count": page_count,
        "parsed_at": datetime.now().astimezone().isoformat(),
        "source_files": {"full_md": full_name, "content_list": content_name},
    }
    prefix = f"parsed/{paper_id}"
    keys = [
        f"{prefix}/full.md",
        f"{prefix}/content_list.json",
        f"{prefix}/meta.json",
    ]
    await storage.put("papers", keys[0], full_md)
    await storage.put("papers", keys[1], content_list)
    await storage.put(
        "papers", keys[2], json.dumps(meta_out, ensure_ascii=False, indent=2).encode()
    )
    logger.info(
        "paper_id=%s 解析产物已存储：papers/%s/*（page_count=%s）",
        paper_id, prefix, page_count,
    )
    return {"page_count": page_count, "keys": keys}


# ── MinerU 精准解析 API（已核实接口，service_keys `mineru` 行 Bearer token）──
async def _mineru_config(db: AsyncSession) -> tuple[str, str]:
    """取 MinerU 凭证；(base_url, token)；缺失/未启用抛 MinerUConfigError（响亮）。"""
    row = await get_key(db, MINERU_SERVICE_KEY)
    if row is None or not row.api_key:
        raise MinerUConfigError(
            "MinerU 未配置：请在管理页 Key 管理添加 service_key=mineru 并启用"
            "（精准解析 API 的 Bearer token，base_url 填 https://mineru.net/api/v4）"
        )
    base = (row.base_url or MINERU_DEFAULT_BASE).rstrip("/")
    return base, row.api_key


def _unwrap(payload: object) -> dict:
    """MinerU 响应解包：data 包裹层缺失时回落顶层（防御实现差异）。"""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload
    return {}


@external_retry()
async def _mineru_batch_upload_url(
    client: httpx.AsyncClient, base: str, headers: dict, filename: str
) -> tuple[str, str]:
    """第 1 步：POST /file-urls/batch 取签名直传地址，返回 (batch_id, upload_url)。

    官方流程（2026-10-29 核实文档）：本地上传链路 = 申请直传 → PUT 上传 →
    **系统自动提交解析任务（无需再调 extract/task）** → 按 batch_id 轮询。
    """
    resp = await client.post(
        f"{base}/file-urls/batch",
        json={"files": [{"name": filename}], "model_version": MINERU_MODEL_VERSION},
        headers=headers,
    )
    resp.raise_for_status()
    data = _unwrap(resp.json())
    urls = data.get("file_urls")
    batch_id = data.get("batch_id")
    if not batch_id or not isinstance(urls, list) or not urls or not urls[0]:
        raise MinerUError(f"file-urls/batch 响应缺 batch_id/file_urls：{str(resp.text)[:200]}")
    return str(batch_id), str(urls[0])


@external_retry()
async def _mineru_put_upload(
    client: httpx.AsyncClient, upload_url: str, pdf_bytes: bytes
) -> None:
    """第 2 步：PUT 上传 PDF 到签名直传地址（签名 URL 自带鉴权，不带 Bearer）。

    注意：OSS 签名是按「无 Content-Type」算的，任何显式 Content-Type 都会破坏
    签名导致 403（2026-10-29 真实首测踩中；MinerU 文档明确要求 PUT 不带 Content-Type）。
    httpx 对裸 bytes 不自动加 Content-Type，这里也绝不能手动加。
    """
    resp = await client.put(upload_url, content=pdf_bytes)
    resp.raise_for_status()


@external_retry()
async def _mineru_batch_state(
    client: httpx.AsyncClient, base: str, headers: dict, batch_id: str
) -> dict:
    """第 3 步：GET /extract-results/batch/{batch_id} 轮询批量任务状态。

    返回首个文件条目 dict（含 state/full_zip_url/err_msg）；状态含
    waiting-file（等上传）/pending/running/done/failed。
    """
    resp = await client.get(f"{base}/extract-results/batch/{batch_id}", headers=headers)
    resp.raise_for_status()
    data = _unwrap(resp.json())
    results = data.get("extract_result") or []
    if not results:
        raise MinerUError(f"extract-results/batch 无 extract_result：{str(resp.text)[:200]}")
    first = results[0]
    if not isinstance(first, dict):
        raise MinerUError(f"extract_result 条目异常：{str(first)[:200]}")
    return first


@external_retry()
async def _mineru_download_zip(client: httpx.AsyncClient, zip_url: str) -> bytes:
    """第 5 步：下载解析产物 zip。"""
    resp = await client.get(zip_url, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


async def mineru_parse(
    db: AsyncSession,
    pdf_bytes: bytes,
    filename: str,
    phase_hook: "object | None" = None,
) -> tuple[bytes, str]:
    """MinerU 精准解析全流程，返回 ``(zip_bytes, model_version)``。

    凭证从 service_keys ``mineru`` 行取（缺失抛 :class:`MinerUConfigError`）；
    任务轮询到 done 取 full_zip_url，failed/超时抛 :class:`MinerUError`。

    phase_hook（轮② P26 可选）：异步回调 ``await phase_hook(phase)``，
    在 上传(upload)→排队(queue)→解析中(parsing) 阶段推进时通知调用方写
    papers.parse_phase；不传则零开销（旧调用方/单测兼容）。
    """
    base, token = await _mineru_config(db)
    headers = {"Authorization": f"Bearer {token}"}
    client = get_http_client()

    batch_id, upload_url = await _mineru_batch_upload_url(client, base, headers, filename)
    if phase_hook is not None:
        await phase_hook("upload")
    await _mineru_put_upload(client, upload_url, pdf_bytes)
    if phase_hook is not None:
        await phase_hook("queue")
    logger.info("MinerU 已上传，batch_id=%s（file=%s，任务由系统自动提交）", batch_id, filename)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + MINERU_POLL_TIMEOUT
    reported_running = False  # running 阶段只上报一次（轮询周期 3s，避免重复写库）
    while True:
        state = await _mineru_batch_state(client, base, headers, batch_id)
        status = str(state.get("state") or "").lower()
        if status == "running" and phase_hook is not None and not reported_running:
            reported_running = True
            await phase_hook("parsing")
        if status == "done":
            zip_url = state.get("full_zip_url")
            if not zip_url:
                raise MinerUError("MinerU 任务完成但未返回 full_zip_url")
            return await _mineru_download_zip(client, str(zip_url)), MINERU_MODEL_VERSION
        if status == "failed":
            reason = state.get("err_msg") or state.get("error") or "未知原因"
            raise MinerUError(f"MinerU 解析失败：{reason}")
        if loop.time() > deadline:
            raise MinerUError(
                f"MinerU 解析超时（>{int(MINERU_POLL_TIMEOUT)}s，batch_id={batch_id}）"
            )
        await asyncio.sleep(MINERU_POLL_INTERVAL)


# ── 状态机：单篇解析管线（Hatchet 任务体与进程内降级共用）────
async def _set_phase(db: AsyncSession, paper: Paper, phase: str | None) -> None:
    """写 papers.parse_phase 并提交（轮② P26 五段阶段条数据源；独立短事务）。"""
    paper.parse_phase = phase
    await db.commit()


async def run_parse_pipeline(
    db: AsyncSession, paper_id: int, user_id: int, pdf_bytes: bytes | None = None
) -> dict:
    """单篇收藏并解析全链：download → store_pdf → mineru_parse → store_parsed。

    状态机写 papers.parse_status（none/pending → running → done|failed）：
    - done：幂等直返，不再跑（重试靠前端按钮，failed 才允许重跑）；
    - running/pending：抛 :class:`ParseAlreadyRunning`（API 层已 409，双保险）；
    - 任一步失败：parse_status=failed + parse_error=原因（截断入库），返回终态字典
      （不向外抛——workflow 与进程内调用方都要落状态，重试 = 再次点按钮）。

    parse_phase（轮② P26）随链路推进：download（OA 下载）→ upload（存 COS +
    MinerU 直传）→ queue（MinerU 排队）→ parsing（MinerU 解析中）；done 清空、
    failed 保留在出错段（前端该段标红）。

    pdf_bytes（轮② P25 导入用）：调用方已备好全文（PDF 上传/arXiv/DOI 下载
    完成）时传入——跳过 OA 下载步，阶段直接从 upload 起；user_id 仅作触发
    审计（归属隔离在 API 层已校验）。
    """
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one_or_none()
    if paper is None:
        raise PdfDownloadError(f"文献不存在：paper_id={paper_id}")

    if paper.parse_status == "done":
        return {
            "paper_id": paper_id,
            "parse_status": "done",
            "parse_error": None,
            "parsed_at": paper.parsed_at,
        }
    if paper.parse_status == "running":
        raise ParseAlreadyRunning(f"文献正在解析中（{paper.parse_status}），请稍后再试")
    # pending 是 API 层占坑（防并发双跑），工作体接手即置 running，合法入口

    paper.parse_status = "running"
    paper.parse_error = None
    paper.parse_phase = "upload" if pdf_bytes is not None else "download"
    await db.commit()
    logger.info("papers-parse 开始：paper_id=%s user_id=%s", paper_id, user_id)

    try:
        if pdf_bytes is None:
            pdf_bytes, pdf_source = await download_oa_pdf(db, paper)
        else:
            pdf_source = "upload"  # 轮②导入：全文由调用方提供（上传/arXiv/DOI）
        await _set_phase(db, paper, "upload")
        storage = await get_storage(db)
        await store_pdf(storage, paper, pdf_bytes)

        async def _phase_hook(phase: str) -> None:
            await _set_phase(db, paper, phase)

        zip_bytes, model_version = await mineru_parse(
            db, pdf_bytes, f"{paper_id}.pdf", phase_hook=_phase_hook
        )
        parsed = await store_parsed(storage, paper_id, zip_bytes, model_version)
    except Exception as exc:
        logger.exception("papers-parse 失败：paper_id=%s", paper_id)
        error = (str(exc) or exc.__class__.__name__)[:_PARSE_ERROR_MAX]
        paper.parse_status = "failed"
        paper.parse_error = error
        # parse_phase 保留在出错段（前端五段条该段标红）；失败前未进链路则为 download
        if paper.parse_phase is None:
            paper.parse_phase = "download"
        await db.commit()
        return {
            "paper_id": paper_id,
            "parse_status": "failed",
            "parse_error": error,
            "parsed_at": None,
        }

    paper.parse_status = "done"
    paper.parse_error = None
    paper.parse_phase = None  # 完成清空（done 由 parse_status 承载）
    paper.parsed_at = datetime.now().astimezone()
    await db.commit()
    logger.info(
        "papers-parse 完成：paper_id=%s（source=%s page_count=%s）",
        paper_id, pdf_source, parsed["page_count"],
    )
    # 轮③ P27：papers_prefs.auto_translate 开启 → 解析 done 自动触发中英对照
    # 翻译（独立降级：翻译失败只落 translate_error，不回传阻断解析结果）
    await paper_translate.maybe_auto_translate(db, paper_id, user_id)
    return {
        "paper_id": paper_id,
        "parse_status": "done",
        "parse_error": None,
        "parsed_at": paper.parsed_at,
        "pdf_source": pdf_source,
        **parsed,
    }


__all__ = [
    "MAX_PDF_BYTES",
    "MINERU_MODEL_VERSION",
    "MINERU_SERVICE_KEY",
    "MinerUConfigError",
    "MinerUError",
    "ParseAlreadyRunning",
    "PdfDownloadError",
    "download_oa_pdf",
    "mineru_parse",
    "pdf_object_key",
    "run_parse_pipeline",
    "store_parsed",
    "store_pdf",
]
