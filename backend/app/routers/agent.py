"""Pi Agent 接口（开发计划-pi-runner-v1 步 5）。

主体是编排者：创建 pi_runs 行 → 推 Hatchet 事件（未接线回落进程内后台任务）
→ pi-runner 沙箱执行 → 结果产物经 storage 入库。SSE 事件流只作代理透传，
不在主体复制 pi-runner 的内存事件缓冲。
"""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_permission
from app.models.pi import PiRun
from app.models.user import User
from app.schemas.pi import PiRunCreate, PiRunCreated, PiRunOut
from app.services import pi_client, pi_runner, pipeline

router = APIRouter(prefix="/agent", tags=["agent"])


async def _agent_reader(user: User = Depends(require_permission("app:agent"))) -> User:
    return user


def _out(run: PiRun) -> PiRunOut:
    return PiRunOut(
        run_id=run.run_id,
        status=run.status,
        task=run.task,
        error=run.error,
        progress=run.progress or {},
        artifacts=run.artifacts or [],
        result_key=run.result_key,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _get_run(db: AsyncSession, user: User, run_id: str) -> PiRun:
    run = (
        await db.execute(
            select(PiRun).where(PiRun.run_id == run_id, PiRun.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return run


@router.post("/runs", response_model=PiRunCreated, status_code=202)
async def create_run(
    body: PiRunCreate,
    background: BackgroundTasks,
    user: User = Depends(_agent_reader),
    db: AsyncSession = Depends(get_db),
):
    """创建 Agent 任务：先落库占坑，再异步派发（响应不等沙箱执行完成）。"""
    run = PiRun(
        run_id=uuid.uuid4().hex,
        user_id=user.id,
        task=body.task.strip(),
        status="pending",
        progress={"pi_status": "pending"},
    )
    db.add(run)
    await db.commit()
    if not pipeline.push_pi_run(run.run_id, user.id):
        background.add_task(pi_runner.execute_run_task, run.run_id)
    return PiRunCreated(run_id=run.run_id, status=run.status)


@router.get("/runs", response_model=list[PiRunOut])
async def list_runs(
    user: User = Depends(_agent_reader),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    limit = min(max(limit, 1), 100)
    rows = (
        await db.execute(
            select(PiRun)
            .where(PiRun.user_id == user.id)
            .order_by(PiRun.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=PiRunOut)
async def get_run(
    run_id: str,
    user: User = Depends(_agent_reader),
    db: AsyncSession = Depends(get_db),
):
    return _out(await _get_run(db, user, run_id))


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    user: User = Depends(_agent_reader),
    db: AsyncSession = Depends(get_db),
):
    """代理 pi-runner SSE；所有权校验在建立流之前完成。"""
    await _get_run(db, user, run_id)
    return StreamingResponse(
        pi_client.iter_events(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/abort")
async def abort_run(
    run_id: str,
    user: User = Depends(_agent_reader),
    db: AsyncSession = Depends(get_db),
):
    run = await _get_run(db, user, run_id)
    try:
        result = await pi_client.abort_run(run_id)
    except pi_client.PiRunnerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    run.status = "aborted"
    run.finished_at = run.finished_at or datetime.now(UTC)
    await db.commit()
    return {"run_id": run_id, "status": result.get("status", "aborted")}
