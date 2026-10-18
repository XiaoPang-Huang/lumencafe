"""文献接口（PRD §4.8，权限点 app:papers，批次 2）。

- /papers/daily：仅本人订阅抓到的文献（paper_users 归属隔离），tag JSONB `@>` 筛选；
- 收藏为幂等 toggle；笔记每人每篇一条 upsert；
- AI 解读全局缓存（paper_explanations 一篇一条，成功才入库，命中直返）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.papers import (
    Paper,
    PaperExplanation,
    PaperFavorite,
    PaperNote,
    PaperUser,
)
from app.models.user import User
from app.schemas.papers import (
    ExplainResponse,
    NoteRequest,
    PaperDetailOut,
    PaperOut,
    SaveResponse,
)
from app.services import llm_gateway, route_service

router = APIRouter(prefix="/papers", tags=["papers"])

EXPLAIN_PROMPT = (
    "你是神经退行性疾病领域的文献解读助手。基于给出的论文标题与摘要输出中文解读，"
    "固定四段式（用①②③④标出）：①研究背景与问题 ②方法概要 ③主要发现 ④局限与意义。"
    "只依据摘要内容，不要臆测；摘要信息不足时明确说明。直接输出解读正文。"
    "\n\n标题：{title}\n\n摘要：{abstract}"
)


async def _reader(user: User = Depends(require_permission("app:papers"))) -> User:
    return user


def _out(p: Paper, saved: bool = False) -> PaperOut:
    return PaperOut(
        id=p.id,
        pmid=p.pmid,
        title=p.title,
        abstract=p.abstract,
        abstract_zh=p.abstract_zh,
        journal=p.journal,
        authors=list(p.authors or []),
        pub_date=p.pub_date,
        tags=list(p.tags or []),
        keywords=list(p.keywords or []),
        created_at=p.created_at,
        saved=saved,
    )


async def _saved_ids(db: AsyncSession, user_id: int, paper_ids: list[int]) -> set[int]:
    if not paper_ids:
        return set()
    rows = (
        await db.execute(
            select(PaperFavorite.paper_id).where(
                PaperFavorite.user_id == user_id, PaperFavorite.paper_id.in_(paper_ids)
            )
        )
    ).scalars().all()
    return set(rows)


async def _get_mine(db: AsyncSession, user_id: int, pid: int) -> Paper:
    """归属隔离：仅 paper_users 中属于我的文献可见（不泄露存在性，统一 404）。"""
    owned = (
        await db.execute(
            select(PaperUser.id).where(PaperUser.user_id == user_id, PaperUser.paper_id == pid)
        )
    ).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    paper = (await db.execute(select(Paper).where(Paper.id == pid))).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="文献不存在")
    return paper


@router.get("/daily", response_model=list[PaperOut])
async def daily_papers(
    tag: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """每日推送：本人订阅抓到的文献，created_at 倒序；tag 为 JSONB 包含筛选。"""
    stmt = (
        select(Paper)
        .join(PaperUser, PaperUser.paper_id == Paper.id)
        .where(PaperUser.user_id == user.id)
        .order_by(Paper.created_at.desc(), Paper.id.desc())
        .limit(limit)
    )
    if tag:
        stmt = stmt.where(Paper.tags.contains([tag]))
    papers = list((await db.execute(stmt)).scalars().all())
    saved = await _saved_ids(db, user.id, [p.id for p in papers])
    return [_out(p, p.id in saved) for p in papers]


@router.get("/favorites", response_model=list[PaperOut])
async def favorite_papers(
    user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(Paper)
            .join(PaperFavorite, PaperFavorite.paper_id == Paper.id)
            .where(PaperFavorite.user_id == user.id)
            .order_by(PaperFavorite.created_at.desc())
        )
    ).scalars().all()
    return [_out(p, True) for p in rows]


@router.get("/{pid}", response_model=PaperDetailOut)
async def paper_detail(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    paper = await _get_mine(db, user.id, pid)
    note = (
        await db.execute(
            select(PaperNote).where(PaperNote.user_id == user.id, PaperNote.paper_id == pid)
        )
    ).scalar_one_or_none()
    explanation = (
        await db.execute(select(PaperExplanation).where(PaperExplanation.paper_id == pid))
    ).scalar_one_or_none()
    saved = await _saved_ids(db, user.id, [pid])
    return PaperDetailOut(
        **_out(paper, pid in saved).model_dump(),
        note=note.content if note else "",
        explanation=explanation.content if explanation else None,
        explanation_model=explanation.model if explanation else "",
    )


@router.post("/{pid}/save", response_model=SaveResponse)
async def toggle_save(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """幂等切换收藏：已收藏 → 取消；未收藏 → 收藏。"""
    await _get_mine(db, user.id, pid)
    stmt = pg_insert(PaperFavorite).values(paper_id=pid, user_id=user.id).on_conflict_do_nothing(
        index_elements=["paper_id", "user_id"]
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount == 1:
        return SaveResponse(saved=True)
    # 已存在 → 取消收藏
    existing = (
        await db.execute(
            select(PaperFavorite).where(
                PaperFavorite.user_id == user.id, PaperFavorite.paper_id == pid
            )
        )
    ).scalar_one_or_none()
    if existing is None:  # 并发下恰好被他人删（不可能，同 user_id），兜底
        return SaveResponse(saved=False)
    await db.delete(existing)
    await db.commit()
    return SaveResponse(saved=False)


@router.post("/{pid}/note")
async def upsert_note(
    pid: int,
    body: NoteRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """笔记 upsert：每人每篇一条，覆盖更新。"""
    await _get_mine(db, user.id, pid)
    stmt = (
        pg_insert(PaperNote)
        .values(paper_id=pid, user_id=user.id, content=body.content)
        .on_conflict_do_update(
            index_elements=["paper_id", "user_id"],
            set_={"content": body.content},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


@router.post("/{pid}/explain", response_model=ExplainResponse)
async def explain_paper(
    pid: int, user: User = Depends(_reader), db: AsyncSession = Depends(get_db)
):
    """AI 解读：命中缓存直返；未命中调网关默认路由生成并写全局缓存（成功才入库）。"""
    paper = await _get_mine(db, user.id, pid)
    cached = (
        await db.execute(select(PaperExplanation).where(PaperExplanation.paper_id == pid))
    ).scalar_one_or_none()
    if cached is not None:
        return ExplainResponse(content=cached.content, model=cached.model, cached=True)

    route = await route_service.resolve_default(db)
    if route is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    try:
        content = await llm_gateway.chat_once(
            route.cfg,
            [
                {"role": "system", "content": "你是文献解读助手，直接输出解读正文。"},
                {
                    "role": "user",
                    "content": EXPLAIN_PROMPT.format(
                        title=paper.title, abstract=paper.abstract[:6000]
                    ),
                },
            ],
            timeout=60.0,
        )
    except llm_gateway.UpstreamError as exc:
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试") from exc
    if not content or not content.strip():
        raise HTTPException(status_code=502, detail="AI 解读生成失败，请稍后再试")

    stmt = (
        pg_insert(PaperExplanation)
        .values(paper_id=pid, content=content.strip(), model=route.model_name)
        .on_conflict_do_nothing(index_elements=["paper_id"])  # 并发兜底：先成者入库
    )
    await db.execute(stmt)
    await db.commit()
    return ExplainResponse(content=content.strip(), model=route.model_name, cached=False)
