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

第三条 workflow（论文域增强③ P16）：papers-parse，事件触发（非 cron）——
「收藏并解析」按钮 → API 置 pending → push_parse_event 推事件到引擎异步执行
（下载 OA → 存 COS → MinerU 解析 → 状态机 done/failed）。引擎未接线/推送失败
回落进程内同步执行（与 crawl-now 同一哲学：用户点按钮不承担引擎可用性）。

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
PARSE_TASK_NAME = "papers-parse"

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


def _event_task(
    hatchet: "Hatchet",
    *,
    name: str,
    timeout: timedelta,
    body: Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]],
) -> Any:
    """声明一个事件触发的任务（on_events，输入为事件 payload 字典）。

    与 _session_task 同样的问题：worker 在 SDK 独占事件循环，任务内自建专用引擎
    （NullPool，随任务 dispose）。输入模型用 pydantic BaseModel（SDK 1.x 校验），
    字段全带缺省——payload 缺键不炸，由执行体兜底判空。
    """
    from hatchet_sdk import Context
    from pydantic import BaseModel

    class ParseInput(BaseModel):
        paper_id: int = 0
        user_id: int = 0

    @hatchet.task(
        name=name,
        on_events=[name],
        execution_timeout=timeout,
        retries=1,  # 瞬时失败重试一轮；解析管线自身幂等（done 直返/failed 记状态）
    )
    async def _task(input: ParseInput, ctx: Context) -> dict[str, Any]:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.config import settings as app_settings

        logger.info("Hatchet 事件触发 %s：paper_id=%s", name, input.paper_id)
        engine = create_async_engine(app_settings.database_url, poolclass=NullPool)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as db:
                return await body(db, input.model_dump())
        finally:
            await engine.dispose()

    return _task


def _build_tasks(hatchet: "Hatchet") -> list[Any]:
    """注册论文域 workflow：每日抓取 cron + 每日清理 cron（P14）+ 解析事件（P16）。"""
    from app.services import paper_parse, papers_crawl

    async def _crawl_body(db: Any) -> dict[str, Any]:
        added = await papers_crawl.run_daily_crawl(db, trigger="schedule")
        logger.info("papers-daily-crawl 轮次完成：added=%d", added)
        return {"added": added}

    async def _cleanup_body(db: Any) -> dict[str, Any]:
        result = await papers_crawl.run_daily_cleanup(db)
        logger.info("papers-daily-cleanup 完成：%s", result)
        return result

    async def _parse_body(db: Any, payload: dict[str, Any]) -> dict[str, Any]:
        result = await paper_parse.run_parse_pipeline(
            db, int(payload.get("paper_id") or 0), int(payload.get("user_id") or 0)
        )
        logger.info("papers-parse 完成：%s", result)
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
    parse_task = _event_task(
        hatchet,
        name=PARSE_TASK_NAME,
        timeout=timedelta(minutes=15),  # 下载 + 排队 + MinerU 解析 + 拆存，给足余量
        body=_parse_body,
    )
    return [crawl_task, cleanup_task, parse_task]


def push_parse_event(paper_id: int, user_id: int) -> bool:
    """API 进程内推 Hatchet 事件触发 papers-parse；未接线/推送失败返回 False。

    调用方（papers 路由）拿到 False 即回落进程内同步执行——用户点「收藏并解析」
    要的是结果可达，不承担引擎可用性（与 crawl-now 不走引擎同一拍板逻辑）。
    """
    hatchet = _hatchet
    if hatchet is None:
        return False
    try:
        hatchet.event.push(PARSE_TASK_NAME, {"paper_id": paper_id, "user_id": user_id})
        return True
    except Exception:
        logger.exception(
            "Hatchet 事件推送失败（papers-parse 转进程内执行）：paper_id=%s", paper_id
        )
        return False


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
    _worker = _hatchet.worker("lumencafe-papers", slots=2, workflows=tasks)
    _worker_thread = threading.Thread(
        target=_worker.start, name="hatchet-worker", daemon=True
    )
    _worker_thread.start()
    logger.info(
        "Hatchet worker 已启动（tasks=%s/%s/%s crons=%s/%s）",
        CRAWL_TASK_NAME,
        CLEANUP_TASK_NAME,
        PARSE_TASK_NAME,
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
