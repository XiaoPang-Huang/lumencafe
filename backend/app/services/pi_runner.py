"""Pi Agent 任务执行与产物入库（开发计划-pi-runner-v1 步 5）。

编排留主体：路由创建 pi_runs 行并推 Hatchet 事件；本模块负责调用 pi-runner
三端点、轮询终态、把 /output/<run_id>/ 下产物校验后经 storage（app=pi）落库。
引擎未接线时由路由回落 asyncio 后台任务执行同一函数。
"""
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models.pi import PiRun
from app.services import pi_client
from app.services.storage import get_storage

_STORAGE_APP = "pi"
_TERMINAL = {"completed", "failed", "aborted"}


def output_dir(run_id: str) -> Path:
    """pi-output 卷内本次 run 的目录（api 只读挂载）。"""
    return Path(settings.pi_runner_output_dir) / run_id


async def execute_run(db: AsyncSession, run_id: str) -> dict[str, Any]:
    """执行一条已落库的 pi_runs 记录；成功/失败都写终态，异常不外抛给 Hatchet。"""
    run = (
        await db.execute(select(PiRun).where(PiRun.run_id == run_id))
    ).scalar_one_or_none()
    if run is None or run.status in _TERMINAL:
        return {"run_id": run_id, "status": run.status if run else "missing"}

    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.progress = {"pi_status": "starting"}
    run.error = None
    await db.commit()

    try:
        task_prompt = (
            f"{run.task}\n\n"
            f"[系统] run_id={run.run_id}。所有产物必须写入 /output/{run.run_id}/；"
            "最终中文摘要写入 result.md，下载得到的文件保留原文件名。"
        )
        await pi_client.start_run(run.run_id, task_prompt)
        final = await pi_client.wait_for_terminal(run.run_id)
        pi_status = str(final.get("status") or "failed")
        run.progress = {
            "pi_status": pi_status,
            "events": final.get("events") or 0,
            "startedAt": final.get("startedAt"),
            "finishedAt": final.get("finishedAt"),
        }
        if pi_status == "completed":
            artifacts, result_key = await persist_outputs(db, run.run_id)
            run.artifacts = artifacts
            run.result_key = result_key
            if result_key is None:
                raise pi_client.PiRunnerError("pi-runner 未生成 result.md")
            run.status = "completed"
        elif pi_status == "aborted":
            run.status = "aborted"
        else:
            run.status = "failed"
            run.error = str(final.get("error") or "pi-runner 执行失败")
    except Exception as exc:  # noqa: BLE001 - 任务终态必须落库，不让异常逃逸
        run.status = "failed"
        run.error = str(exc)
        if run.progress is None:
            run.progress = {}
        run.progress["exception"] = exc.__class__.__name__
    run.finished_at = datetime.now(UTC)
    await db.commit()
    return {"run_id": run.run_id, "status": run.status, "error": run.error}


async def execute_run_task(run_id: str) -> dict[str, Any]:
    """进程内后台执行入口（Hatchet 未接线时的回落路径）。"""
    async with SessionLocal() as db:
        return await execute_run(db, run_id)


async def persist_outputs(db: AsyncSession, run_id: str) -> tuple[list[str], str | None]:
    """把 /output/<run_id>/ 的产物存入对象存储，返回 (artifact_keys, result_key)。

    events.jsonl 只是排障流水，体量可达数 MB~数十 MB，不入对象存储；result.md
    与 PDF 等产物按原文件名保存在 pi/runs/<run_id>/ 下。
    """
    src = output_dir(run_id)
    if not src.is_dir():
        raise pi_client.PiRunnerError(f"pi-runner 输出目录不存在：{src}")

    storage = await get_storage(db)
    artifacts: list[str] = []
    result_key: str | None = None
    for path in sorted(src.iterdir()):
        if not path.is_file() or path.name == "events.jsonl":
            continue
        data = path.read_bytes()
        key = f"runs/{run_id}/{path.name}"
        await storage.put(_STORAGE_APP, key, data)
        artifacts.append(key)
        if path.name == "result.md":
            result_key = key
    return artifacts, result_key
