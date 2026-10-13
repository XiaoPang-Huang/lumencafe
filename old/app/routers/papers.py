"""文献推送路由：每日推送 / 收藏 / 笔记 / AI 解读。

约定（与脚手架一致）：全走 get_current_user 鉴权；响应直接 dict / HTTPException(detail)，
不做 code 包装。404 统一为「论文不存在」。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..llm.base import LLMNotConfiguredError
from ..llm.providers import get_llm
from ..models import (
    Paper,
    PaperExplanation,
    PaperFavorite,
    PaperNote,
    PaperUser,
    WhitelistUser,
)
from ..schemas import NoteIn

logger = logging.getLogger("island")

router = APIRouter(tags=["papers"])

# 标签筛选合法值（与爬虫打标规则一致）
VALID_TAGS = ("AD", "PD", "ALS", "scale")

# LLM 未开通时的友好文案（路由层统一使用）
EXPLAIN_NOT_OPEN = "AI 解读暂未开通，敬请期待"


def paper_to_dict(paper: Paper, favorite: bool) -> dict:
    """文献卡片/详情统一序列化。"""
    return {
        "id": paper.id,
        "pmid": paper.pmid,
        "title": paper.title,
        "abstract": paper.abstract,
        "abstract_zh": paper.abstract_zh or "",
        "journal": paper.journal,
        "authors": paper.authors or [],
        "pub_date": str(paper.pub_date) if paper.pub_date else None,
        "tags": paper.tags or [],
        "keywords": paper.keywords or [],
        "favorite": favorite,
        "created_at": paper.created_at.isoformat() if paper.created_at else None,
    }


async def favorite_id_set(db: AsyncSession, openid: str, papers: list[Paper]) -> set[int]:
    """批量查询当前用户对这些文献的收藏状态。"""
    ids = [p.id for p in papers]
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(PaperFavorite.paper_id).where(
                PaperFavorite.user_id == openid,
                PaperFavorite.paper_id.in_(ids),
            )
        )
    ).scalars().all()
    return set(rows)


async def get_paper_or_404(db: AsyncSession, paper_id: int) -> Paper:
    paper = (
        await db.execute(select(Paper).where(Paper.id == paper_id))
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


@router.get("/papers/daily")
async def papers_daily(
    tag: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """每日推送列表：只出本人订阅抓到的文献（paper_users 归属），created_at 倒序，可按标签筛选。"""
    stmt = (
        select(Paper)
        .join(PaperUser, PaperUser.paper_id == Paper.id)
        .where(PaperUser.user_id == user.openid)
        .order_by(Paper.created_at.desc(), Paper.id.desc())
        .limit(limit)
    )
    if tag:
        if tag not in VALID_TAGS:
            raise HTTPException(status_code=400, detail=f"非法标签：{tag}（可选：{'/'.join(VALID_TAGS)}）")
        # JSONB 包含查询：tags 数组里含该标签
        stmt = stmt.where(Paper.tags.op("@>")([tag]))
    papers = (await db.execute(stmt)).scalars().all()
    favs = await favorite_id_set(db, user.openid, list(papers))
    return {"papers": [paper_to_dict(p, p.id in favs) for p in papers]}


@router.get("/papers/favorites")
async def papers_favorites(
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """当前用户的收藏列表（收藏时间倒序），结构与每日推送一致。"""
    papers = (
        await db.execute(
            select(Paper)
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == user.openid)
            .order_by(PaperFavorite.created_at.desc())
        )
    ).scalars().all()
    return {"papers": [paper_to_dict(p, True) for p in papers]}


@router.get("/papers/{paper_id}")
async def paper_detail(
    paper_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单篇详情：收藏状态 + 本人笔记（无则 null）+ 全局缓存的 AI 解读（无则 null）。"""
    paper = await get_paper_or_404(db, paper_id)
    fav = (
        await db.execute(
            select(PaperFavorite).where(
                PaperFavorite.user_id == user.openid,
                PaperFavorite.paper_id == paper.id,
            )
        )
    ).scalar_one_or_none()
    note = (
        await db.execute(
            select(PaperNote).where(
                PaperNote.user_id == user.openid,
                PaperNote.paper_id == paper.id,
            )
        )
    ).scalar_one_or_none()
    explanation = (
        await db.execute(
            select(PaperExplanation).where(PaperExplanation.paper_id == paper.id)
        )
    ).scalar_one_or_none()
    return {
        **paper_to_dict(paper, fav is not None),
        "note": note.content if note else None,
        "note_updated_at": note.updated_at.isoformat() if note else None,
        "explanation": explanation.content if explanation else None,
    }


@router.post("/papers/{paper_id}/save")
async def paper_save(
    paper_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """幂等切换收藏状态，返回 {saved: bool}。"""
    paper = await get_paper_or_404(db, paper_id)
    row = (
        await db.execute(
            select(PaperFavorite).where(
                PaperFavorite.user_id == user.openid,
                PaperFavorite.paper_id == paper.id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        saved = False
    else:
        db.add(PaperFavorite(user_id=user.openid, paper_id=paper.id))
        saved = True
    await db.commit()
    return {"saved": saved}


@router.post("/papers/{paper_id}/note")
async def paper_note(
    paper_id: int,
    body: NoteIn,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """本人笔记 upsert（每人每篇一条，重复保存覆盖），返回 {ok, content, updated_at}。"""
    paper = await get_paper_or_404(db, paper_id)
    stmt = (
        pg_insert(PaperNote)
        .values(user_id=user.openid, paper_id=paper.id, content=body.content)
        .on_conflict_do_update(
            index_elements=["user_id", "paper_id"],
            set_={"content": body.content, "updated_at": datetime.utcnow()},
        )
    )
    await db.execute(stmt)
    await db.commit()
    note = (
        await db.execute(
            select(PaperNote).where(
                PaperNote.user_id == user.openid,
                PaperNote.paper_id == paper.id,
            )
        )
    ).scalar_one_or_none()
    return {
        "ok": True,
        "content": note.content if note else body.content,
        "updated_at": note.updated_at.isoformat() if note else None,
    }


@router.post("/papers/{paper_id}/explain")
async def paper_explain(
    paper_id: int,
    user: WhitelistUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI 解读：缓存命中直返；未命中走 LLM 层生成并写全局缓存。

    LLM 未配置返回 503 友好文案；生成失败返回 502，半截内容不入库。
    """
    paper = await get_paper_or_404(db, paper_id)

    cached = (
        await db.execute(
            select(PaperExplanation).where(PaperExplanation.paper_id == paper.id)
        )
    ).scalar_one_or_none()
    if cached is not None:
        return {"explanation": cached.content}

    try:
        llm = await get_llm("explain")
        content = await llm.explain(paper.title, paper.abstract or "")
    except LLMNotConfiguredError as exc:
        logger.info("AI 解读未开通：%s", exc)
        raise HTTPException(status_code=503, detail=EXPLAIN_NOT_OPEN)
    except Exception:
        logger.exception("AI 解读生成失败：paper_id=%d", paper.id)
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试")

    if not content:
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试")

    # 生成完整成功后才写缓存（异常路径不会执行到这里，天然避免半截入库）
    db.add(PaperExplanation(paper_id=paper.id, model=llm.model, content=content))
    await db.commit()
    return {"explanation": content}
