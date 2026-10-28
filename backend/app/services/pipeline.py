"""Hatchet 定时引擎接线（论文域步 B，组件选型 §三拍板：Go 引擎 + 复用现有 PG 独立库）。

形态与降级：
- 未配置 HATCHET_CLIENT_TOKEN（settings.hatchet_client_token 为空，compose 从
  .env 注入）→ start() 直接返回 False，不 import SDK、不建连——本地开发/测试
  无引擎可跑，定时抓取退化到 /internal/jobs/papers-crawl（内部令牌兜底）；
- SDK 未安装（ImportError）→ 告警并同样降级，不炸启动。

worker 形态：hatchet-sdk 1.x 的 Worker 要求独占事件循环（start() 自建 loop 并
阻塞当前线程），故跑在专用守护线程里（嵌入 api 容器进程，compose 净增仍只有
hatchet 引擎一个容器）；停服时经 run_coroutine_threadsafe 调 exit_gracefully
优雅退出，超时则随进程结束（daemon 线程）。

cron 任务：on_crons 声明式注册（worker 注册即生效），默认 30 7 * * *，由引擎
容器 TZ=Asia/Shanghai 解释为本地早 7:30；执行体 = papers_crawl.run_daily_crawl
同一函数（trigger=schedule），runs 表落库与手动/内部触发完全一致。

第二条 workflow（论文域增强 P14）：papers-daily-cleanup，默认 30 8 * * *（抓取后
1 小时，本地 8:30），执行 7 天滚动清理（未收藏且无笔记且入库 ≥7 天的论文），
幂等同 digest 先例（进程内日期标记）。两 task 共用 _session_task 的
专用引擎会话样板（worker 跑在 SDK 独占事件循环，连接不可跨循环复用）。

手动 crawl-now 不走 Hatchet：进程内同步执行、即时返回结果；若绕引擎转发，
用户点「立即检索」要承担引擎可用性 + gRPC 往返 + 轮询运行状态三重失败面，
收益为零（无重试/无并发语义需求）。定时与手动共用 _execute_round，口径天然一致。
"""
import asyncio
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from hatchet_sdk import Hatchet  # 仅类型标注；运行期惰性 import

logger = logging.getLogger("lumencafe.pipeline")

CRAWL_TASK_NAME = "papers-daily-crawl"
CLEANUP_TASK_NAME = "papers-daily-cleanup"

_hatchet: "Hatchet | None" = None
_worker: Any = None  # hatchet_sdk Worker（ Any：未装 SDK 时不引入类型依赖）
_worker_thread: threading.Thread | None = None


def is_configured() -> bool:
    """Hatchet 是否已配置。

    HATCHET_CLIENT_TOKEN 是 SDK 原生变量（无 LUMEN_ 前缀，compose 从 .env 原样注入、
    SDK 自行读取），直接查环境；LUMEN_HATCHET_CLIENT_TOKEN（settings 镜像项）可作覆盖。
    """
    return bool(settings.hatchet_client_token or os.environ.get("HATCHET_CLIENT_TOKEN"))


def _session_task(
    hatchet: "Hatchet",
    *,
    name: str,
    cron: str,
    timeout: timedelta,
    body: Callable[[Any], Awaitable[dict[str, Any]]],
) -> Any:
    """声明一个带专用引擎会话的 cron 任务（执行体注入，会话样板共用）。

    worker 跑在 SDK 独占事件循环（守护线程），与主应用引擎不同循环——
    SQLAlchemy/asyncpg 连接不可跨循环复用，故任务内自建专用引擎（NullPool，
    随任务 dispose）；http_client 本身感知循环切换，provider 网络层不受影响。
    expire_on_commit=False 与 app.db.SessionLocal 同口径。
    """
    from hatchet_sdk import Context, EmptyModel

    @hatchet.task(
        name=name,
        on_crons=[cron],
        execution_timeout=timeout,
        retries=1,  # 瞬时失败重试一轮；抓取轮有 runs 表/清理有日期标记，重复执行幂等
    )
    async def _task(input: EmptyModel, ctx: Context) -> dict[str, Any]:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.config import settings as app_settings

        logger.info("Hatchet cron 触发 %s", name)
        engine = create_async_engine(app_settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await body(db)
        finally:
            await engine.dispose()

    return _task


def _build_tasks(hatchet: "Hatchet") -> list[Any]:
    """注册两条论文域 cron workflow：每日抓取 + 每日 7 天滚动清理（P14）。"""
    from app.services import papers_crawl

    async def _crawl_body(db: Any) -> dict[str, Any]:
        added = await papers_crawl.run_daily_crawl(db, trigger="schedule")
        logger.info("papers-daily-crawl 轮次完成：added=%d", added)
        return {"added": added}

    async def _cleanup_body(db: Any) -> dict[str, Any]:
        result = await papers_crawl.run_daily_cleanup(db)
        logger.info("papers-daily-cleanup 完成：%s", result)
        return result

    crawl_task = _session_task(
        hatchet,
        name=CRAWL_TASK_NAME,
        cron=settings.papers_crawl_cron,
        timeout=timedelta(minutes=10),  # 多用户 × 多源 + 中译回填，给足余量
        body=_crawl_body,
    )
    cleanup_task = _session_task(
        hatchet,
        name=CLEANUP_TASK_NAME,
        cron=settings.papers_cleanup_cron,
        timeout=timedelta(minutes=5),  # 单表单次删除，余量充足
        body=_cleanup_body,
    )
    return [crawl_task, cleanup_task]


def start() -> bool:
    """lifespan 启动钩子：初始化 Hatchet client + 守护线程 worker。

    返回 True=已接线引擎；False=未配置/未装 SDK（降级，调用方无需处理）。
    """
    global _hatchet, _worker, _worker_thread
    if not is_configured():
        logger.info(
            "HATCHET_CLIENT_TOKEN 未配置，跳过 Hatchet 接线（定时抓取走 /internal/jobs）"
        )
        return False
    try:
        from hatchet_sdk import Hatchet
    except ImportError:
        logger.warning("hatchet-sdk 未安装，跳过 Hatchet 接线（pip 装依赖后重启生效）")
        return False

    _hatchet = Hatchet()
    tasks = _build_tasks(_hatchet)
    _worker = _hatchet.worker("lumencafe-papers", slots=1, workflows=tasks)
    _worker_thread = threading.Thread(
        target=_worker.start, name="hatchet-worker", daemon=True
    )
    _worker_thread.start()
    logger.info(
        "Hatchet worker 已启动（tasks=%s/%s crons=%s/%s）",
        CRAWL_TASK_NAME,
        CLEANUP_TASK_NAME,
        settings.papers_crawl_cron,
        settings.papers_cleanup_cron,
    )
    return True


def stop() -> None:
    """lifespan 退出钩子：通知 worker 优雅退出（等在途任务排空），随后随进程结束。"""
    global _hatchet, _worker, _worker_thread
    worker, _worker = _worker, None
    _hatchet = None
    _worker_thread = None
    if worker is None:
        return
    loop = getattr(worker, "_loop", None)  # SDK 1.x 私有：worker 自建的专属事件循环
    if loop is None or not loop.is_running():
        return
    try:
        future = asyncio.run_coroutine_threadsafe(worker.exit_gracefully(), loop)
        future.result(timeout=15)
        logger.info("Hatchet worker 已优雅退出")
    except Exception:  # noqa: BLE001 - 退出阶段不放大异常，daemon 线程兜底
        logger.warning("Hatchet worker 优雅退出超时/失败，随进程结束")
