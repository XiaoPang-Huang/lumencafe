"""pi-runner HTTP 客户端（开发计划-pi-runner-v1 步 5）。

主体只面对 pi-runner 的三个端点：POST /api/runs、GET /api/runs/:id/events、
POST /api/runs/:id/abort；本模块负责错误归一化与 SSE 透传。结果文件不经过
HTTP，由 api 只读挂载 pi-output 卷后校验入库。
"""
import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings
from app.services.http_client import get_http_client


class PiRunnerError(RuntimeError):
    """pi-runner 不可用或返回错误（路由层转 502）。"""


# 主体先推 Hatchet 事件再代理 SSE；worker 首次调用 pi-runner 前，事件端点可能短暂 404。
EVENT_START_RETRY_DELAY = 1.0
EVENT_START_TIMEOUT = 30.0


def _url(path: str) -> str:
    return f"{settings.pi_runner_url.rstrip('/')}{path}"


def _detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] or f"HTTP {resp.status_code}"
    if isinstance(data, dict) and data.get("error"):
        return str(data["error"])
    return f"HTTP {resp.status_code}"


async def _request(method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        resp = await get_http_client().request(method, _url(path), json=json)
    except httpx.HTTPError as exc:
        raise PiRunnerError(f"无法连接 pi-runner：{exc}") from exc
    if resp.status_code >= 400:
        raise PiRunnerError(_detail(resp))
    try:
        data: dict[str, Any] = resp.json()
    except ValueError as exc:
        raise PiRunnerError("pi-runner 返回非 JSON 响应") from exc
    return data


async def start_run(run_id: str, task: str) -> dict[str, Any]:
    return await _request("POST", "/api/runs", json={"run_id": run_id, "task": task})


async def get_run(run_id: str) -> dict[str, Any]:
    return await _request("GET", f"/api/runs/{run_id}")


async def abort_run(run_id: str) -> dict[str, Any]:
    return await _request("POST", f"/api/runs/{run_id}/abort")


async def iter_events(run_id: str) -> AsyncIterator[bytes]:
    """透传 pi-runner SSE 原始字节；run 尚未创建时短重试，连接失败抛 PiRunnerError。"""
    client = get_http_client()
    started = time.monotonic()
    while True:
        try:
            async with client.stream(
                "GET",
                _url(f"/api/runs/{run_id}/events"),
                timeout=httpx.Timeout(60.0, connect=10.0),
            ) as resp:
                if resp.status_code == 404 and time.monotonic() - started < EVENT_START_TIMEOUT:
                    await asyncio.sleep(EVENT_START_RETRY_DELAY)
                    continue
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise PiRunnerError(body[:200] or f"HTTP {resp.status_code}")
                async for chunk in resp.aiter_raw():
                    yield chunk
                return
        except httpx.HTTPError as exc:
            raise PiRunnerError(f"无法连接 pi-runner：{exc}") from exc


async def wait_for_terminal(run_id: str, *, timeout_seconds: int | None = None) -> dict[str, Any]:
    """轮询 pi-runner 状态直到 completed/failed/aborted（开发计划步 5 落盘前确认）。"""
    import asyncio

    deadline_seconds = timeout_seconds or settings.pi_runner_timeout_seconds
    waited = 0.0
    delay = 2.0
    while True:
        data = await get_run(run_id)
        status = str(data.get("status") or "")
        if status in {"completed", "failed", "aborted"}:
            return data
        if waited >= deadline_seconds:
            raise PiRunnerError(f"等待 pi-runner 完成超时（{deadline_seconds:.0f}s）")
        await asyncio.sleep(delay)
        waited += delay
