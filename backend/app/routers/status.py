"""系统状态接口（底座步 5）：工作台状态灯数据源。

GET /status（Caddy 剥 /api 前缀，外部路径 /api/status）：
- api：本进程能返回此响应即 true；
- db：真实探活 SELECT 1（失败返回 false 且接口仍 200——状态灯变红比 503 更有用，
  也让前端能区分「API 挂」与「DB 挂」）；
- backup：读 backup_state 卷 last_run.json（未挂载/不存在/解析失败 = null，
  前端显示「未配置」灰灯）；
- 鉴权：沿用 JWT，登录用户可见（不要求 admin，与拍板一致）。
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.status import BackupState, StatusOut

router = APIRouter(prefix="/status", tags=["status"])

_BACKUP_STATE_FILE = "last_run.json"


def _read_backup_state() -> BackupState | None:
    """读 backup_state 卷的 last_run.json；任何异常按「未配置」处理（返回 None）。"""
    state_dir = settings.backup_state_dir.strip()
    if not state_dir:
        return None
    try:
        raw = json.loads(
            (Path(state_dir) / _BACKUP_STATE_FILE).read_text(encoding="utf-8")
        )
        return BackupState.model_validate(raw)
    except (OSError, ValueError, TypeError):
        return None


@router.get("", response_model=StatusOut)
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusOut:
    """系统状态总览：api/db/backup/version（工作台状态灯真实数据源）。"""
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db_ok = False
    return StatusOut(
        api=True,
        db=db_ok,
        backup=_read_backup_state(),
        version=settings.app_version,
    )
