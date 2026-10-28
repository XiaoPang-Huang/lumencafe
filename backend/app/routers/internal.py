"""内部任务触发（PRD §4.8，架构设计 §5.5/Q11）。

- 不走用户 JWT：X-Internal-Token 比对 LUMEN_INTERNAL_TOKEN（常量时间比对）；
- 同日幂等去重：进程内当日标记 + papers 表当日记录双保险（Q11）；
- 执行体 services/papers_crawl.run_daily_crawl，返回本轮新入库数 {added: n}。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import internal_token_guard
from app.services import papers_crawl

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/jobs/papers-crawl")
async def run_papers_crawl(
    _=Depends(internal_token_guard), db: AsyncSession = Depends(get_db)
):
    if papers_crawl.already_ran_today():
        return {"added": 0}  # 同日重复触发，幂等跳过
    added = await papers_crawl.run_daily_crawl(db)
    papers_crawl.mark_ran_today()  # Q11 第一重：进程内日期标记
    return {"added": added}


@router.post("/jobs/papers-cleanup")
async def run_papers_cleanup(
    _=Depends(internal_token_guard), db: AsyncSession = Depends(get_db)
):
    """7 天滚动清理（P14）：Hatchet 未接线时的内部触发兜底，幂等同 cron 口径。"""
    return await papers_crawl.run_daily_cleanup(db)
