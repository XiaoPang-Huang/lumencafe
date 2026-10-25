"""tenacity 重试策略收口（步 2 工程三小件之一，架构设计-增量 v2 D10）。

- 只重试瞬时错误：httpx 网络类异常（连接失败/读写超时/池等待等）与
  HTTP 5xx、429（限流）；
- 4xx（除 429）与鉴权错误（401/403）永不重试——请求本身有问题，重试无意义；
- 指数退避 + 最小间隔 0.5s（对齐 NCBI ≤3 req/s 的 polite 纪律），最多 3 次尝试。

外部调用点（NCBI esearch/efetch、LLM chat_once/fetch_model_names）用
external_retry() 装饰；重试耗尽后 reraise 原异常，由调用方既有兜底处理
（papers_crawl 记日志跳过、网关转 UpstreamError → 路由层 502）。
"""
from collections.abc import Callable
from typing import Any, TypeVar

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

F = TypeVar("F", bound=Callable[..., Any])

# 默认：最多 3 次尝试（即重试 2 次），退避 0.5s → 1s → 2s（封顶 8s）
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_WAIT = 0.5
DEFAULT_MAX_WAIT = 8.0


def is_transient_http_error(exc: BaseException) -> bool:
    """瞬时错误判定：网络类异常与 5xx/429 可重试；4xx 其他与鉴权不重试。"""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    # 网络/超时/协议类（ConnectError、TimeoutException、ProtocolError、
    # NetworkError、TooManyRedirects 等）一律视为瞬时
    return isinstance(exc, httpx.HTTPError)


def external_retry(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    min_wait: float = DEFAULT_MIN_WAIT,
    max_wait: float = DEFAULT_MAX_WAIT,
) -> Callable[[F], F]:
    """外部 HTTP 调用重试装饰器工厂（tenacity.retry 的本项目预设）。"""
    decorator: Callable[[F], F] = retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception(is_transient_http_error),
    )
    return decorator
