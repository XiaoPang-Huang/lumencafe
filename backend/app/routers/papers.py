"""文献接口（PRD §4.8，权限点 app:papers，批次 2；步 A 多源扩展）。

- /papers/daily：仅本人订阅抓到的文献（paper_users 归属隔离），tag JSONB `@>` 筛选；
- 收藏为幂等 toggle；笔记每人每篇一条 upsert；
- AI 解读全局缓存（paper_explanations 一篇一条，成功才入库，命中直返）；
- 步 A：/papers/sources 已注册源清单（订阅设置勾选框）；
  /papers/suggest-keywords 大白话 → AI 生成订阅关键词（不写库，保存走 /me/settings）。
"""
import json
import logging
import re

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
    SourceOut,
    SuggestKeywordsRequest,
    SuggestKeywordsResponse,
)
from app.services import llm_gateway, route_service
from app.services.sources import list_providers

router = APIRouter(prefix="/papers", tags=["papers"])

logger = logging.getLogger("lumencafe.papers")

EXPLAIN_PROMPT = (
    "你是神经退行性疾病领域的文献解读助手。基于给出的论文标题与摘要输出中文解读，"
    "固定四段式（用①②③④标出）：①研究背景与问题 ②方法概要 ③主要发现 ④局限与意义。"
    "只依据摘要内容，不要臆测；摘要信息不足时明确说明。直接输出解读正文。"
    "\n\n标题：{title}\n\n摘要：{abstract}"
)

# 步 A：AI 生成订阅关键词的系统提示词（内置常量；app_key=papers_config 解析路由）
SUGGEST_KEYWORDS_APP_KEY = "papers_config"
SUGGEST_KEYWORDS_SYSTEM = (
    "你是学术文献订阅关键词提炼助手。用户用一句大白话描述研究方向，"
    "你要提炼成 8-12 个适合在文献数据库（PubMed/arXiv/OpenAlex 等）检索的关键词。"
    "要求：中英文都给出（英文关键词用于国际库检索，中文用于说明可附）；"
    "每个关键词 1-4 个词，覆盖核心概念、关键方法、应用场景等同义表达；"
    "不要输出任何解释、编号或多余文字，严格返回 JSON 字符串数组，"
    '形如 ["关键词1", "keyword 2", ...]。'
)
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


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


@router.get("/sources", response_model=list[SourceOut])
async def list_paper_sources(user: User = Depends(_reader)):
    """已注册文献源清单（key + 展示名），订阅设置弹窗的勾选框数据源（步 A）。"""
    return [SourceOut(key=p.name, name=p.display_name) for p in list_providers()]


def _parse_keyword_array(content: str) -> list[str]:
    """解析 LLM 返回为关键词数组：剥 code fence → json.loads → 校验字符串数组。

    返回保序去重、去空白后的关键词；解析失败/结构不符抛 ValueError（路由层转 502）。
    """
    cleaned = _CODE_FENCE_RE.sub("", content or "").strip()
    data = json.loads(cleaned)
    if not isinstance(data, list) or not all(isinstance(k, str) for k in data):
        raise ValueError("AI 返回不是 JSON 字符串数组")
    out: list[str] = []
    for kw in data:
        kw = kw.strip()
        if kw and kw not in out:
            out.append(kw)
    if not out:
        raise ValueError("AI 返回的关键词数组为空")
    return out


@router.post("/suggest-keywords", response_model=SuggestKeywordsResponse)
async def suggest_keywords(
    body: SuggestKeywordsRequest,
    user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
):
    """大白话 → AI 生成 8-12 个中英检索关键词（步 A 拍板 P4）。

    走网关按消费者路由（app_key=papers_config，未配置指派回落默认路由）；
    不写库——用户勾选确认后由前端调 /me/settings 保存 subscribe_keywords。
    """
    plan = await route_service.resolve_for(db, SUGGEST_KEYWORDS_APP_KEY)
    if plan is None:
        raise HTTPException(
            status_code=503, detail="模型未配置，请联系管理员在模型管理页设置默认路由"
        )
    try:
        content = await llm_gateway.chat_once(
            plan.candidates[0].cfg,
            [
                {"role": "system", "content": SUGGEST_KEYWORDS_SYSTEM},
                {"role": "user", "content": body.description.strip()},
            ],
            timeout=60.0,
        )
    except llm_gateway.UpstreamError as exc:
        logger.warning("生成订阅关键词失败：%s", exc)
        raise HTTPException(status_code=502, detail="AI 生成失败，请稍后再试") from exc
    try:
        keywords = _parse_keyword_array(content)
    except (ValueError, TypeError) as exc:
        logger.warning("订阅关键词解析失败：%s（原文：%.200s）", exc, content)
        raise HTTPException(
            status_code=502, detail="AI 返回内容无法解析为关键词数组，请重试"
        ) from exc
    return SuggestKeywordsResponse(keywords=keywords)


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
