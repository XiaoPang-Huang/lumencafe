"""熔断器（架构设计-增量 v2 B1/D2，语义抄 Portkey；参数见 Part C Q2 拍板）。

状态机（状态存 model_circuit_states 表，重启不丢）：
- closed：正常参与路由；
- 连挂 FAILURE_THRESHOLD 次 → open（摘出旋转，路由跳过该模型），
  next_probe_at = 触发时刻 + COOLDOWN_SECONDS（冷却 60s）；
- 冷却到点后，下一个命中该模型的请求即探针（half-open）：成功 → closed
  （计数清零，自动切回）；失败 → 重新 open，next_probe_at = 失败时刻 +
  PROBE_INTERVAL_SECONDS（每 30s 探测一次）。

先简单后精细：单行 upsert + 单写者假设（请求级会话内串行），不做分布式锁。
时间一律走 utcnow()（可注入，测试用冻结时钟驱动冷却/探测周期）。
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm import ModelCircuitState

# Q2 拍板参数
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60
PROBE_INTERVAL_SECONDS = 30

STATE_CLOSED = "closed"
STATE_OPEN = "open"


def utcnow() -> datetime:
    """当前 UTC 时刻（测试可 monkeypatch 以驱动冷却/探测周期）。"""
    return datetime.now(UTC)


async def _get_state(db: AsyncSession, model_id: int) -> ModelCircuitState | None:
    return (
        await db.execute(
            select(ModelCircuitState).where(ModelCircuitState.model_id == model_id)
        )
    ).scalar_one_or_none()


async def is_available(db: AsyncSession, model_id: int, now: datetime | None = None) -> bool:
    """该模型当前是否可参与路由：closed，或 open 但已到探测时点。"""
    row = await _get_state(db, model_id)
    if row is None or row.state != STATE_OPEN:
        return True
    moment = now or utcnow()
    return row.next_probe_at is not None and moment >= row.next_probe_at


async def on_success(db: AsyncSession, model_id: int) -> None:
    """调用成功：熔断恢复（closed + 计数清零），并落库。"""
    row = await _get_state(db, model_id)
    if row is None:
        row = ModelCircuitState(model_id=model_id, state=STATE_CLOSED, consecutive_failures=0)
        db.add(row)
    row.state = STATE_CLOSED
    row.consecutive_failures = 0
    row.opened_at = None
    row.next_probe_at = None
    await db.commit()


async def on_failure(db: AsyncSession, model_id: int, now: datetime | None = None) -> bool:
    """调用失败：计数 +1；触发摘出或探测失败重开。返回本次是否处于 open。

    - closed 且计数达阈值 → open，冷却 COOLDOWN_SECONDS；
    - open（探测失败）→ 保持 open，进入 PROBE_INTERVAL_SECONDS 探测间隔。
    """
    moment = now or utcnow()
    row = await _get_state(db, model_id)
    if row is None:
        row = ModelCircuitState(model_id=model_id, state=STATE_CLOSED, consecutive_failures=0)
        db.add(row)
    row.consecutive_failures += 1
    if row.state == STATE_OPEN:
        # 探测失败：重新冷却，每 30s 允许再探一次
        row.next_probe_at = moment + timedelta(seconds=PROBE_INTERVAL_SECONDS)
    elif row.consecutive_failures >= FAILURE_THRESHOLD:
        row.state = STATE_OPEN
        row.opened_at = moment
        row.next_probe_at = moment + timedelta(seconds=COOLDOWN_SECONDS)
    await db.commit()
    return row.state == STATE_OPEN


async def reset(db: AsyncSession, model_id: int) -> None:
    """管理面手动恢复：清熔断状态（不计数历史）。"""
    row = await _get_state(db, model_id)
    if row is not None:
        row.state = STATE_CLOSED
        row.consecutive_failures = 0
        row.opened_at = None
        row.next_probe_at = None
        await db.commit()
