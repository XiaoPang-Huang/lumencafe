"""系统状态响应模型（底座步 5：工作台状态灯数据源）。"""
from datetime import datetime

from pydantic import BaseModel


class BackupState(BaseModel):
    """备份最近一次运行状态（backup 容器写 backup_state 卷 last_run.json）。

    succeeded=False 时 error 为失败原因摘要；成功时为 None。
    """

    succeeded: bool
    at: datetime
    error: str | None = None


class StatusOut(BaseModel):
    """GET /api/status 响应：api 进程 / db 探活 / backup 状态 / 版本。"""

    api: bool
    db: bool
    backup: BackupState | None
    version: str
