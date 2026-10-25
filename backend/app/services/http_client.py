"""共享 httpx.AsyncClient 总机（步 2 工程三小件之一，架构设计-增量 v2 D10）。

- FastAPI lifespan 启动时创建、退出时关闭（main.py 接线），全进程唯一实例；
- llm_gateway / papers_crawl / 未来 MinerU、Unpaywall 等一切出网调用共用，
  复用 TCP/TLS 连接（原先每次调用新建 client，握手白做，见组件选型-v1 §7.1）；
- 超时与连接池参数在此显式声明、全项目统一；个别调用点仍可用 httpx 的
  per-request timeout= 覆盖（如 LLM 长流式 120s）。

单测/脚本等未走 lifespan 的上下文调用 get_http_client() 会惰性自建兜底，
并感知事件循环切换，避免跨循环复用连接池（pytest-asyncio 循环纪律）。
"""
import asyncio

import httpx

# 全项目统一出口参数（显式写明，不依赖 httpx 默认值）：
# - connect=10s 对齐原各调用点；读写/池等待 60s，慢上游给足余量；
# - 连接池上限 50 / 保活 20 / 保活 30s：2核4G 小机的保守量级，与 DB 侧纪律
#   （pool 5 + overflow 10 ≤ 15 < max_connections 20，见 docker-compose db）同理。
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
DEFAULT_LIMITS = httpx.Limits(
    max_connections=50, max_keepalive_connections=20, keepalive_expiry=30.0
)

_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def _new_client() -> tuple[httpx.AsyncClient, asyncio.AbstractEventLoop | None]:
    """按统一参数新建 client，并记录其所属事件循环。"""
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    return (
        httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, limits=DEFAULT_LIMITS),
        loop,
    )


def init_http_client() -> httpx.AsyncClient:
    """创建共享 client（lifespan 启动钩子调用；幂等，重复调用不重建）。"""
    global _client, _client_loop
    if _client is None or _client.is_closed:
        _client, _client_loop = _new_client()
    return _client


async def close_http_client() -> None:
    """关闭共享 client（lifespan 退出钩子调用；幂等）。"""
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
    _client_loop = None


def get_http_client() -> httpx.AsyncClient:
    """取共享 client；lifespan 未接线时惰性自建兜底（感知事件循环）。

    mock 链路不联网不受影响，但代码路径一致走总机（拍板：路径统一）。
    """
    global _client, _client_loop
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or _client.is_closed or _client_loop is not loop:
        _client, _client_loop = _new_client()
    return _client
