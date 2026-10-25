"""tenacity 重试收口 + 共享 httpx 总机单测（步 2 工程三小件）。

覆盖拍板验收点：瞬时错误（网络类/5xx/429）重试生效；4xx 与鉴权错误不重试；
mock 链路不联网不受影响但代码路径一致走总机。
"""

import httpx

from app.services import llm_gateway
from app.services.http_client import get_http_client
from app.services.retry import is_transient_http_error


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    return httpx.HTTPStatusError("boom", request=req, response=httpx.Response(code, request=req))


def test_transient_judgement_status_codes():
    # 5xx / 429 可重试
    for code in (500, 502, 503, 429):
        assert is_transient_http_error(_status_error(code)), code
    # 4xx（除 429）与鉴权错误不重试
    for code in (400, 401, 403, 404, 422):
        assert not is_transient_http_error(_status_error(code)), code


def test_transient_judgement_network_errors():
    assert is_transient_http_error(httpx.ConnectError("conn"))
    assert is_transient_http_error(httpx.ReadTimeout("read"))
    assert is_transient_http_error(httpx.ConnectTimeout("ct"))
    # 非 httpx 异常不参与重试判定
    assert not is_transient_http_error(ValueError("json"))
    assert not is_transient_http_error(KeyError("k"))


def test_shared_client_singleton():
    assert get_http_client() is get_http_client()


async def test_chat_once_retries_transient(monkeypatch):
    """monkeypatch 造一次 503：tenacity 应重试并成功（第 2 次调用）。"""
    calls = {"n": 0}

    async def flaky_post(self: httpx.AsyncClient, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(503)
        req = httpx.Request("POST", url)
        return httpx.Response(
            200, request=req, json={"choices": [{"message": {"content": " 好的 "}}]}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", flaky_post)
    cfg = llm_gateway.ClientCfg(base_url="https://api.test/v1", api_key="k", model="m")
    result = await llm_gateway.chat_once(cfg, [{"role": "user", "content": "hi"}])
    assert result == "好的"
    assert calls["n"] == 2  # 第一次 503 被重试


async def test_chat_once_no_retry_on_auth_error(monkeypatch):
    """401 鉴权错误：不重试，直接 UpstreamError。"""
    calls = {"n": 0}

    async def failing_post(self: httpx.AsyncClient, url, **kwargs):
        calls["n"] += 1
        raise _status_error(401)

    monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)
    cfg = llm_gateway.ClientCfg(base_url="https://api.test/v1", api_key="k", model="m")
    try:
        await llm_gateway.chat_once(cfg, [{"role": "user", "content": "hi"}])
        raised = False
    except llm_gateway.UpstreamError:
        raised = True
    assert raised, "401 应转 UpstreamError"
    assert calls["n"] == 1  # 4xx 不重试
