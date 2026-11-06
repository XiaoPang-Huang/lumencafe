"""请求/响应模型：Pi Agent 任务（开发计划-pi-runner-v1 步 5）。"""
import datetime as dt

from pydantic import BaseModel, Field


class PiRunCreate(BaseModel):
    task: str = Field(min_length=1, max_length=8000)


class PiRunOut(BaseModel):
    run_id: str
    status: str
    task: str
    error: str | None = None
    progress: dict = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    result_key: str | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


class PiRunCreated(BaseModel):
    run_id: str
    status: str
