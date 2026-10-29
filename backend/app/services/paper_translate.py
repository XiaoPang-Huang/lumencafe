"""段落级中英对照翻译服务（轮③，拍板 P27/P24）：按需生成、逐块翻译、永久缓存。

链路（POST /papers/{id}/translate 触发，状态机复用解析模式）：

- 取块：读 COS ``parsed/{id}/content_list.json``，经
  :func:`app.services.paper_content.load_parsed_content` 归一化——block_id 与
  批注锚点同一套 ``p{页}_b{页内序}`` 规则，译文与批注/原文严格同锚；
- 分批：text 类块（type=="text" 且文本非空）按 block_id 顺序每批 ≤15 段
  （:data:`BATCH_MAX_BLOCKS`），已有译文的块跳过（增量补译，重解析后新块
  只译增量）；
- 调用：走网关按消费者路由（app_key=``papers_translate``，未配置指派回落
  默认路由），经 model_caller 编排（备用链兜底 + 熔断 + llm_call_logs 记账，
  费用随网关记账）；系统提示词内置常量：学术中译、保留术语与公式符号、
  严格 JSON 返回 ``{"块id": "译文"}``；
- 容错：单批返回非 JSON / 缺块 → 该批失败块重试一次；重试仍失败 → 已得
  译文照常落盘（增量不丢），整体置 failed 且 translate_error 记原因；
- 落盘：每批合并已有 translation.json 增量写回 COS
  ``parsed/{id}/translation.json``（一次翻译永久缓存，P27）；
- 状态机：papers.translate_status none|running|done|failed（可空=none）。
  done 幂等直返（「重新翻译」走 force=true 清缓存全量重译）；running 拒重入
  （API 409）；failed/none 可重跑（增量跳过已译块）。

自动翻译（轮③ P27）：papers_prefs.auto_translate（默认关）开启时，
:func:`maybe_auto_translate` 在解析状态机完成处（run_parse_pipeline done
之后）自动触发；翻译失败不影响解析结果（独立降级，原因落 translate_error）。
"""
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.papers import Paper
from app.services import model_caller, paper_content, papers_crawl
from app.services.storage import Storage, StorageNotFoundError, get_storage

logger = logging.getLogger("lumencafe.paper_translate")

# ── 常量（显式声明，不依赖隐式默认）──
TRANSLATE_APP_KEY = "papers_translate"  # 模型指派 app_key（未配置回落默认路由）
BATCH_MAX_BLOCKS = 15  # 每批最多段落数（P27 拍板 ≤15）
TRANSLATE_TIMEOUT = 120.0  # 单批翻译超时（秒；批量段落给足余量）
RETRY_ONCE = 1  # JSON 解析失败/缺块的重试次数（拍板：失败块重试一次）
_ERROR_MAX = 1000  # translate_error 入库截断长度
TRANSLATION_KEY = "parsed/{paper_id}/translation.json"  # 对象键模板（不含 app 前缀）

# 系统提示词（内置常量，拍板 P27）：学术中译 + 保留术语与公式符号 + 严格 JSON
TRANSLATE_SYSTEM = (
    "你是学术文献翻译助手，专长神经退行性疾病领域论文。把用户给出的 JSON 对象"
    "（键为段落块 id，值为英文原文）逐段翻译成通顺、忠实的中文学术译文。"
    "要求：①保留专业术语（可附英文原词）；②保留公式与符号原样（如 α、β、≤、"
    "p < 0.05、变量下标）；③不增删原文信息，段落一一对应；④严格只返回一个 "
    "JSON 对象，键与原键完全一致，值为对应中文译文；不要输出解释、markdown "
    "代码块或其他任何文字。"
)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class TranslateAlreadyRunning(RuntimeError):
    """该文献正在翻译中（running），拒绝重入。"""


def translation_key(paper_id: int) -> str:
    """translation.json 的对象键（app=papers 由存储层补前缀）。"""
    return TRANSLATION_KEY.format(paper_id=paper_id)


# ── 翻译块提取与译文解析（纯函数，便于单测锚定）────────────────
def translatable_blocks(blocks: list[dict]) -> list[dict]:
    """从归一化块数组取可译 text 块：type=="text" 且文本非空（保持原序）。

    block_id 与批注锚点同规则（p{页}_b{页内序}），译文天然与原文/批注同锚。
    """
    out: list[dict] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if str(b.get("type") or "") != "text":
            continue
        text = str(b.get("text") or "").strip()
        if not text:
            continue
        out.append({"block_id": str(b["block_id"]), "text": text})
    return out


def extract_translation_json(content: str) -> dict[str, str]:
    """从模型返回中解析严格 JSON 对象：剥 code fence → 截取首个 {...} → 校验。

    返回 {block_id: 译文}（仅保留非空字符串值）；解析失败/结构不符抛
    ValueError（调用方按「失败块」口径重试）。
    """
    cleaned = _CODE_FENCE_RE.sub("", content or "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 返回中找不到 JSON 对象")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise TypeError("AI 返回的 JSON 不是对象")
    out: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            out[key] = value.strip()
    if not out:
        raise ValueError("AI 返回的 JSON 对象为空")
    return out


# ── COS 存取（paper_parse 存取范式：经存储抽象层，app=papers）────
async def load_translation(storage: Storage, paper_id: int) -> dict[str, str]:
    """读已有 translation.json；对象缺失/损坏返回 {}（增量跳过的数据源）。"""
    try:
        raw = await storage.get("papers", translation_key(paper_id))
    except StorageNotFoundError:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("paper_id=%s translation.json 不是合法 JSON，按无缓存处理", paper_id)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip()
    }


async def _store_translation(
    storage: Storage, paper_id: int, translations: dict[str, str]
) -> None:
    """增量写回 translation.json（每批合并后落盘，长文部分进度不丢）。"""
    await storage.put(
        "papers",
        translation_key(paper_id),
        json.dumps(translations, ensure_ascii=False, indent=1).encode(),
    )


# ── 单批调用（网关编排：记账/兜底/熔断都在 model_caller）────────
async def _translate_batch(db: AsyncSession, batch: list[dict]) -> dict[str, str]:
    """翻译一批块：构造 system+user 消息走 model_caller.chat_once 返回译文表。

    路由/记账异常（RouteUnavailable/AllRoutesFailed 等）直接外抛——由状态机
    统一落 failed；JSON 解析失败/缺块由调用方按失败块口径重试。
    """
    payload = {b["block_id"]: b["text"] for b in batch}
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    content = await model_caller.chat_once(
        db, TRANSLATE_APP_KEY, messages, timeout=TRANSLATE_TIMEOUT
    )
    return extract_translation_json(content)


def _batch_payload(batch: list[dict], block_ids: list[str]) -> list[dict]:
    """按 id 集合从批次中取子集（重试只带失败块，省 token）。"""
    wanted = set(block_ids)
    return [b for b in batch if b["block_id"] in wanted]


# ── 状态机：单篇翻译管线 ─────────────────────────────────────
async def _refresh_paper(db: AsyncSession, paper_id: int) -> Paper:
    """重读行（model_caller 记账会独立提交，事务边界后重取防过期对象）。"""
    return (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one()


async def run_translate_pipeline(
    db: AsyncSession, paper_id: int, user_id: int, force: bool = False
) -> dict:
    """单篇段落级中英对照翻译全链：取块 → 分批 → 网关 → 增量落盘。

    状态机写 papers.translate_status（none → running → done|failed）：
    - done 且非 force：幂等直返（「重新翻译」由前端带 force=true 触发）；
    - running：抛 :class:`TranslateAlreadyRunning`（API 层已 409，双保险）；
    - 无解析产物/网关失败/重试后仍有缺块：failed + translate_error（截断入库），
      已得译文照常保留在 translation.json（增量可续），返回终态字典不外抛。

    user_id 仅作触发审计（归属隔离在 API 层已校验）。
    """
    paper = await _refresh_paper(db, paper_id)
    status = paper.translate_status or "none"
    if status == "running":
        raise TranslateAlreadyRunning(
            f"文献正在翻译中（{status}），请稍后再试"
        )

    blocks = await paper_content.load_parsed_content(db, paper_id)
    if blocks is None:
        error = "该文献还没有解析产物，请先完成解析再翻译"
        paper.translate_status = "failed"
        paper.translate_error = error
        await db.commit()
        return {
            "paper_id": paper_id,
            "translate_status": "failed",
            "translate_error": error,
            "translated_blocks": 0,
            "total_blocks": 0,
        }
    targets = translatable_blocks(blocks)

    storage = await get_storage(db)
    existing: dict[str, str] = {} if force else await load_translation(storage, paper_id)
    if status == "done" and not force:
        # 幂等直返：已译条目回读计数，total 按当前正文 text 块口径
        return {
            "paper_id": paper_id,
            "translate_status": "done",
            "translate_error": None,
            "translated_blocks": len(existing),
            "total_blocks": len(targets),
        }

    storage = await get_storage(db)
    pending = [b for b in targets if b["block_id"] not in existing]
    if not targets or not pending:
        # 没有 text 块或全部已译：直接 done（幂等语义，不空转网关）
        paper.translate_status = "done"
        paper.translate_error = None
        await db.commit()
        return {
            "paper_id": paper_id,
            "translate_status": "done",
            "translate_error": None,
            "translated_blocks": len(existing),
            "total_blocks": len(targets),
        }

    paper.translate_status = "running"
    paper.translate_error = None
    await db.commit()
    logger.info(
        "papers-translate 开始：paper_id=%s user_id=%s 待译=%d/%d force=%s",
        paper_id, user_id, len(pending), len(targets), force,
    )

    merged = dict(existing)
    failed_block_ids: list[str] = []
    try:
        for start in range(0, len(pending), BATCH_MAX_BLOCKS):
            batch = pending[start : start + BATCH_MAX_BLOCKS]
            batch_ids = {b["block_id"] for b in batch}
            got: dict[str, str] = {}
            try:
                got = await _translate_batch(db, batch)
                got = {k: v for k, v in got.items() if k in batch_ids}
            except Exception as exc:  # noqa: BLE001 - 调用失败/JSON 解析失败同口径
                logger.warning(
                    "paper_id=%s 翻译批次失败（%d 块）：%s",
                    paper_id, len(batch), exc,
                )
            missing = [bid for bid in batch_ids if bid not in got]
            if missing:
                # 拍板：失败块重试一次（只带缺块，省 token）
                try:
                    retry = await _translate_batch(db, _batch_payload(batch, missing))
                    retry = {k: v for k, v in retry.items() if k in set(missing)}
                    got.update(retry)
                except Exception as exc:  # noqa: BLE001 - 重试失败按缺块计
                    logger.warning(
                        "paper_id=%s 翻译重试失败（%d 块）：%s",
                        paper_id, len(missing), exc,
                    )
                missing = [bid for bid in batch_ids if bid not in got]
                failed_block_ids.extend(missing)
            merged.update(got)
            await _store_translation(storage, paper_id, merged)
    except Exception as exc:  # 存储层等意外：落 failed 不外抛
        logger.exception("papers-translate 失败：paper_id=%s", paper_id)
        error = (str(exc) or exc.__class__.__name__)[:_ERROR_MAX]
        paper = await _refresh_paper(db, paper_id)
        paper.translate_status = "failed"
        paper.translate_error = error
        await db.commit()
        return {
            "paper_id": paper_id,
            "translate_status": "failed",
            "translate_error": error,
            "translated_blocks": len(merged),
            "total_blocks": len(targets),
        }

    if failed_block_ids:
        error = f"{len(failed_block_ids)} 个段落翻译失败，可重试（已译进度已保存）"
        paper = await _refresh_paper(db, paper_id)
        paper.translate_status = "failed"
        paper.translate_error = error
        await db.commit()
        logger.warning("paper_id=%s 翻译缺块失败：%s", paper_id, error)
        return {
            "paper_id": paper_id,
            "translate_status": "failed",
            "translate_error": error,
            "translated_blocks": len(merged),
            "total_blocks": len(targets),
        }

    paper = await _refresh_paper(db, paper_id)
    paper.translate_status = "done"
    paper.translate_error = None
    await db.commit()
    logger.info(
        "papers-translate 完成：paper_id=%s（%d/%d 块）", paper_id, len(merged), len(targets)
    )
    return {
        "paper_id": paper_id,
        "translate_status": "done",
        "translate_error": None,
        "translated_blocks": len(merged),
        "total_blocks": len(targets),
    }


# ── 自动翻译（轮③ P27：papers_prefs.auto_translate，默认关）────
async def maybe_auto_translate(db: AsyncSession, paper_id: int, user_id: int) -> None:
    """解析完成处联动：prefs.auto_translate 开启则自动触发翻译。

    任何失败只落 translate_error（状态机内），绝不回传阻断解析链路——
    自动翻译是体验增强，不是解析成功的前置条件。
    """
    from app.models.user_settings import UserSetting

    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == user_id, UserSetting.key == "papers_prefs"
            )
        )
    ).scalar_one_or_none()
    prefs = papers_crawl.parse_papers_prefs(row.value if row is not None else None)
    if not prefs.get("auto_translate"):
        return
    try:
        await run_translate_pipeline(db, paper_id, user_id)
    except Exception as exc:  # noqa: BLE001 - 自动翻译失败不阻断解析
        logger.warning(
            "auto_translate 触发失败（paper_id=%s）：%s", paper_id, exc
        )


__all__ = [
    "BATCH_MAX_BLOCKS",
    "TRANSLATE_APP_KEY",
    "TRANSLATE_SYSTEM",
    "TranslateAlreadyRunning",
    "extract_translation_json",
    "load_translation",
    "maybe_auto_translate",
    "run_translate_pipeline",
    "translatable_blocks",
    "translation_key",
]
