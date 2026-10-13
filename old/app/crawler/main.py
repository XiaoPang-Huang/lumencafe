"""爬虫进程入口。

用法：
    python -m app.crawler.main            # 常驻：每天本地时间 push_time 抓取一次
    python -m app.crawler.main --once     # 立即抓取一次后退出
    python -m app.crawler.main --days 7   # 覆盖抓取窗口天数
"""
import argparse
import asyncio
import logging
from datetime import datetime, timedelta

from ..config import settings
from .service import run_crawl

logger = logging.getLogger("island.crawler")


def seconds_until_next_push(push_time: str) -> float:
    """计算到下一个本地时间 push_time（HH:MM）的秒数。"""
    try:
        hour_str, minute_str = push_time.split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
    except ValueError:
        hour, minute = 8, 0  # 配置非法时退回默认 08:00
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def loop_forever(days_back: int | None) -> None:
    """常驻循环：睡到下一个推送时间 → 抓取 → 记录日志。"""
    while True:
        wait = seconds_until_next_push(settings.push_time)
        next_run = datetime.now() + timedelta(seconds=wait)
        logger.info("下次抓取：%s（%.0f 秒后）", next_run.strftime("%Y-%m-%d %H:%M:%S"), wait)
        await asyncio.sleep(wait)
        try:
            added = await run_crawl(days_back=days_back)
            logger.info("定时抓取完成，新增 %d 篇", added)
        except Exception:
            logger.exception("定时抓取失败，等待下一轮")


def main() -> None:
    parser = argparse.ArgumentParser(description="小岛文献抓取器（PubMed）")
    parser.add_argument("--once", action="store_true", help="立即抓取一次后退出")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="抓取窗口天数（默认取配置 ISLAND_DAYS_BACK=%d）" % settings.days_back,
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.once:
        added = asyncio.run(run_crawl(days_back=args.days))
        logger.info("单次抓取完成，新增 %d 篇", added)
    else:
        asyncio.run(loop_forever(args.days))


if __name__ == "__main__":
    main()
