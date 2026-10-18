"""内部任务触发（PRD §4.8，架构设计 §5.5/Q11）。

- 不走用户 JWT：X-Internal-Token 比对 LUMEN_INTERNAL_TOKEN（常量时间比对）；
- 同日幂等去重：进程内当日执行标记，重复触发返回 {added: 0}；
- 执行体在 services/papers_crawl.py，批次 2 填充（本期 {added: 0}）。
"""
from fastapi import APIRouter, Depends

from app.deps import internal_token_guard
from app.services import papers_crawl

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/jobs/papers-crawl")
async def run_papers_crawl(_=Depends(internal_token_guard)):
    if papers_crawl.already_ran_today():
        return {"added": 0}  # 同日重复触发，幂等跳过
    papers_crawl.mark_ran_today()
    added = await papers_crawl.run_daily_crawl()
    return {"added": added}
