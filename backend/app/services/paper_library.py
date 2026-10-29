"""我的文献工作台服务（轮①，P22/P23/P24）：加入/列表/删除 + 级联清理。

- :func:`add_to_library`：加入我的文献（幂等 upsert，ON CONFLICT DO NOTHING）；
- :func:`list_library`：我的文献列表（库行 JOIN 题录，created_at 倒序）；
- :func:`delete_from_library`：删除（拍板 P24 级联语义）——
  本人关联全清（paper_library 行 / paper_favorites 行 / paper_users 归属 /
  paper_notes 全文笔记 + 批注，批注出链由 FK CASCADE 不涉及跨行残留，因为出链
  只指向本人批注）；**行主**  （papers.user_id == 本人）再删 papers 行
  （FK CASCADE 带走 paper_explanations）并回收 COS 产物五件：
  ``parsed/{id}/full.md + content_list.json + meta.json + translation.json``
  （轮③ P27 译文缓存）+
  ``pdfs/{yyyy}/{mm}/{id}.pdf``（按 ``pdfs/`` 前缀列全后按 paper_id 结尾过滤，
  兼容任意年月分层）；非行主（历史公共行）只解除本人归属，不动行与产物
  （拍板 P23：删除任何文献只解除本人归属 + 删本人批注，另一用户不受影响）。

COS 清理失败不阻断库内删除（产物成了孤儿文件，日志告警人工兜底）；
存储半配置（StorageConfigError）同理降级为告警——删除是用户显式指令，
不能因为存储故障把数据删一半卡死。
"""
import logging

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.papers import (
    Paper,
    PaperFavorite,
    PaperLibrary,
    PaperNote,
    PaperUser,
)
from app.services.storage import StorageNotFoundError, get_storage

logger = logging.getLogger("lumencafe.papers")


async def add_to_library(
    db: AsyncSession, paper_id: int, user_id: int, added_via: str = "crawl"
) -> None:
    """加入我的文献（幂等）：已有行不动（保留最早加入时间与途径）。"""
    await db.execute(
        pg_insert(PaperLibrary)
        .values(paper_id=paper_id, user_id=user_id, added_via=added_via)
        .on_conflict_do_nothing(index_elements=["user_id", "paper_id"])
    )
    await db.commit()


async def list_library(
    db: AsyncSession, user_id: int
) -> list[tuple[PaperLibrary, Paper]]:
    """我的文献列表：库行 JOIN 题录，加入时间倒序（新加入在前）。"""
    rows = (
        await db.execute(
            select(PaperLibrary, Paper)
            .join(Paper, Paper.id == PaperLibrary.paper_id)
            .where(PaperLibrary.user_id == user_id)
            .order_by(PaperLibrary.created_at.desc(), PaperLibrary.id.desc())
        )
    ).all()
    return [(lib, paper) for lib, paper in rows]


async def _delete_cos_artifacts(storage: object, paper_id: int) -> list[str]:
    """回收 COS 产物五件（parsed/{id} 四件含译文 + pdfs 分层 PDF）；返回实际删除的 key。"""
    keys = [
        f"parsed/{paper_id}/full.md",
        f"parsed/{paper_id}/content_list.json",
        f"parsed/{paper_id}/meta.json",
        f"parsed/{paper_id}/translation.json",  # 轮③ P27：中英对照译文缓存同回收
    ]
    try:
        pdfs = await storage.list("papers", "pdfs/")  # type: ignore[attr-defined]
        keys.extend(k for k in pdfs if k.endswith(f"/{paper_id}.pdf"))
    except Exception as exc:  # noqa: BLE001 - 列表失败不阻断已定位键的删除
        logger.warning("列 COS pdfs/ 前缀失败（paper_id=%s）：%s", paper_id, exc)
    deleted: list[str] = []
    for key in keys:
        try:
            await storage.delete("papers", key)  # type: ignore[attr-defined]
            deleted.append(key)
        except StorageNotFoundError:
            continue  # 幂等：对象已不在（如未解析过就没有 parsed/ 三件）
        except Exception as exc:  # noqa: BLE001 - 单键失败不阻断其余键
            logger.warning("删 COS 对象失败（papers/%s）：%s", key, exc)
    return deleted


async def delete_from_library(
    db: AsyncSession, paper_id: int, user_id: int
) -> dict:
    """删除我的文献（P24 级联）；返回 {"deleted_paper": bool, "cos_deleted": [...]}。

    deleted_paper=True 表示本人是行主、papers 行已级联删除；False 表示只解除
    本人归属（历史共享行，其他用户不受影响）。
    """
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one_or_none()
    if paper is None:
        return {"deleted_paper": False, "cos_deleted": []}

    # 本人关联全清（FK ondelete CASCADE 双保险：显式删 + 行删兜底）
    await db.execute(
        delete(PaperLibrary).where(
            PaperLibrary.paper_id == paper_id, PaperLibrary.user_id == user_id
        )
    )
    await db.execute(
        delete(PaperFavorite).where(
            PaperFavorite.paper_id == paper_id, PaperFavorite.user_id == user_id
        )
    )
    await db.execute(
        delete(PaperUser).where(
            PaperUser.paper_id == paper_id, PaperUser.user_id == user_id
        )
    )
    await db.execute(
        delete(PaperNote).where(
            PaperNote.paper_id == paper_id, PaperNote.user_id == user_id
        )
    )

    cos_deleted: list[str] = []
    deleted_paper = paper.user_id == user_id  # 行主才删行 + 产物（P24）
    if deleted_paper:
        try:
            storage = await get_storage(db)
            cos_deleted = await _delete_cos_artifacts(storage, paper_id)
        except Exception as exc:  # noqa: BLE001 - 存储故障降级告警，不阻断删除
            logger.warning("回收 COS 产物失败（paper_id=%s）：%s", paper_id, exc)
        await db.delete(paper)  # FK CASCADE：explanations/users/favorites/notes/library

    await db.commit()
    return {"deleted_paper": deleted_paper, "cos_deleted": cos_deleted}
