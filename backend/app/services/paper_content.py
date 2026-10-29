"""批注式笔记内容服务（P8）：解析产物 content_list.json → 结构化段落 + 稳定锚点 block 标识。

block_id 规则（拍板 P8/P20；content_list.json 各项无显式 id，实测 MinerU 结构：
每项含 type/text/page_idx，可选 text_level/img_path/table_body 等）：

    p{page_idx + 1}_b{页内序号}

- 页码 1 起（人类可读，与解析页面对齐）；页内序号从 1 起，**按数组阅读顺序
  对全部块计数**（含 image/table/equation 等非文本块）——序号与数组序一一
  对应，同一份解析产物恒生成同一组 block_id（稳定性测试锚定此规则）；
- 解析产物不变 ⇒ block_id 不变；重解析导致内容位移时，批注不静默失效——
  anchor_quote（被选中原文，hypothes.is TextQuoteSelector 式精确引用）恒在
  右栏引用块可见，前端可用原文模糊找回段落（orphan 可见原则）。

块文本提取（防御解析，逐项容错，坏项跳过不拖垮全文）：
- text：text 字段；text_level 1-4 = 标题层级（缺省/0 = 正文）；
- table：table_body（MinerU 给 HTML）去标签为纯文本预览；缺省回落 table_caption；
- image：image_caption 列表拼接；
- 其他（equation/code/interline_equation…）：text 字段，缺省空串。

对象键（P20）：app=papers，key=parsed/{paper_id}/content_list.json，
经存储抽象层读取（COS 已配置走 COS，未配置回落 Local）。
"""
import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.storage import StorageNotFoundError, get_storage

logger = logging.getLogger("lumencafe.paper_content")

# ── 常量 ──────────────────────────────────────────────────
CONTENT_LIST_KEY = "parsed/{paper_id}/content_list.json"  # 对象键模板（不含 app 前缀）
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# 各类型块的文本字段候选（按优先级取第一个非空字符串）
_TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "text": ("text",),
    "table": ("table_body", "text", "table_caption", "table_footnote"),
    "image": ("text", "image_caption", "image_footnote"),
}
_DEFAULT_FIELDS: tuple[str, ...] = ("text", "text_level")


def content_list_key(paper_id: int) -> str:
    """content_list.json 的对象键（app=papers 由存储层补前缀）。"""
    return CONTENT_LIST_KEY.format(paper_id=paper_id)


def build_block_id(page_idx: int, seq_on_page: int) -> str:
    """p{page+1}_b{页内序}：页 1 起、页内序 1 起。"""
    return f"p{page_idx + 1}_b{seq_on_page}"


def _as_int(value: Any, default: int = 0) -> int:
    """防御：page_idx/text_level 非 int 时回落缺省（坏项不炸整篇）。"""
    return value if isinstance(value, int) else default


def _text_of(item: dict) -> str:
    """按类型取块文本（HTML 去标签 + 空白归一）；取不到返回空串。"""
    block_type = str(item.get("type") or "text")
    fields = _TEXT_FIELDS.get(block_type, _DEFAULT_FIELDS[:1])
    for field in fields:
        raw = item.get(field)
        if isinstance(raw, str) and raw.strip():
            return WS_RE.sub(" ", TAG_RE.sub(" ", raw)).strip()
        if isinstance(raw, list):  # caption/footnote 列表形态
            joined = " ".join(str(x) for x in raw if isinstance(x, str) and x.strip())
            if joined.strip():
                return WS_RE.sub(" ", joined).strip()
    return ""


def normalize_content_list(items: Any) -> list[dict]:
    """content_list.json（任意 JSON）→ 结构化块数组；非法输入返回空数组。

    纯函数，便于单测锚定 block_id 稳定性规则。逐项容错：非 dict 项跳过、
    文本为空且非文本类型（image 无 caption 等）的项也保留占位（块序号
    与数组序一一对应是稳定性前提，不允许中途删项造成序号漂移）。
    """
    if not isinstance(items, list):
        return []
    blocks: list[dict] = []
    page_counters: dict[int, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue  # 坏项跳过：防御，不影响其余块序号（坏项本无稳定位置）
        page_idx = _as_int(item.get("page_idx"), 0)
        page_counters[page_idx] = page_counters.get(page_idx, 0) + 1
        level_raw = item.get("text_level")
        text_level = level_raw if isinstance(level_raw, int) and level_raw > 0 else None
        blocks.append(
            {
                "block_id": build_block_id(page_idx, page_counters[page_idx]),
                "type": str(item.get("type") or "text"),
                "text": _text_of(item),
                "page_idx": page_idx,
                "text_level": text_level,
            }
        )
    return blocks


async def load_parsed_content(db: AsyncSession, paper_id: int) -> list[dict] | None:
    """读解析产物并结构化；无产物（未解析/对象缺失/JSON 损坏）返回 None。

    调用方按 None → 404「还没有解析产物」处理（拍板 P8：无解析产物给明确 404）。
    JSON 损坏与对象缺失同权——都是「这份解析产物不可用」。
    """
    storage = await get_storage(db)
    try:
        raw = await storage.get("papers", content_list_key(paper_id))
    except StorageNotFoundError:
        return None
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("paper_id=%s content_list.json 不是合法 JSON", paper_id)
        return None
    return normalize_content_list(items)


__all__ = [
    "build_block_id",
    "content_list_key",
    "load_parsed_content",
    "normalize_content_list",
]
