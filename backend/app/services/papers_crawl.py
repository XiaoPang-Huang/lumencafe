"""文献抓取执行体（批次 2 填充）。

本期（T04）只交付接口骨架：同日去重 + 令牌守卫 + 测试（架构设计 Q11）。
批次 2 在此实现 NCBI esearch/efetch（≤3 req/s、efetch 分批 ≤100/批）、
打标、中译回填，并升级去重为「进程内标记 + papers 表当日记录」双保险。
"""
from datetime import UTC, datetime

# 进程内当日执行标记（日期戳；重启不重复抓取）
_last_run_date: str | None = None


def already_ran_today() -> bool:
    return _last_run_date == datetime.now(UTC).date().isoformat()


def mark_ran_today() -> None:
    global _last_run_date
    _last_run_date = datetime.now(UTC).date().isoformat()


async def run_daily_crawl() -> int:
    """执行一轮文献抓取，返回本轮新入库数。批次 2 填充，本期恒 0。"""
    return 0
