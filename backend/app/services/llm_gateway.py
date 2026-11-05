"""LLM 网关服务：对 OpenAI 兼容上游的统一出口。

- 纯函数式：调用方查库后传入 ClientCfg(base_url/api_key/model/vendor)，本模块不查库；
- vendor=mock 或 base_url 为空 → 本地假实现不联网（开发/测试走完整链路）：
  chat_once 返回记账 parse 的严格 JSON 草稿（mock 模式 AI 记一笔开箱可用），
  chat_stream 返回固定寒暄文案 + mock 思维流（双流回归测试可用）；
- 不传 temperature 等覆盖参数（架构设计 Q9）；增量 v1 例外：thinking_level（R1 白名单
  内唯一可开放调用参数），经 build_thinking_params(vendor, level) 表驱动映射为
  各家协议参数（DeepSeek thinking.type / OpenAI reasoning_effort / Qwen
  enable_thinking+thinking_budget / GLM·Kimi turn-level 两态，详见增量架构 §3.4）。

调用参数策略（Q9）：除 thinking_level 外一律用厂商默认；拉取模型入库的 meta 仅作展示。

网络层（步 2 工程三小件，D10）：真实调用一律走共享 httpx 总机
（app/services/http_client.py，lifespan 建/销毁）；chat_once 与
fetch_model_names 的瞬时错误（网络类/5xx/429）由 tenacity 重试收口
（app/services/retry.py，4xx 与鉴权错误不重试）。chat_stream 不做内联
重试：流式首帧之后不可重发（步 3 备用链兜底只管首 token 前）。

步 3 记账：chat_once/chat_stream 可选 usage_out 参数回填 token 计量
（非流式取响应 usage；流式发 stream_options.include_usage 从末帧取；
mock 记 0），费用快照固化在 meter_service。
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.services.http_client import get_http_client
from app.services.retry import external_retry

MOCK_STREAM_REPLY = (
    "你好呀，我是 mock 模型。现在是本地占位模式，"
    "在管理页配置真实 Provider 后，我就能正经聊天了。"
)

# mock 思维流：双流协议回归测试用（无思维流的模型自然不产出 reasoning 帧，R3）
MOCK_STREAM_REASONING = (
    "（mock 思考流）用户打了个招呼，我先理解意图——这像是在测试对话链路；"
    "然后组织回答：说明当前是本地占位模式，并提示如何接入真实模型。"
)

# mock 的 chat_once 返回 parse 严格 JSON 草稿（date 动态填今天）
_MOCK_PARSE_TEMPLATE = (
    '{{"amount": 1580, "type": "expense", "category_suggestion": "餐饮",'
    ' "note": "mock 解析占位", "date": "{today}", "confidence": 0.99}}'
)


class UpstreamError(Exception):
    """上游 LLM 调用失败（网络/超时/非 2xx），路由层转 502。"""


@dataclass(frozen=True)
class StreamChunk:
    """双流协议帧（R3）：delta=正文增量，reasoning_delta=思维增量，二者至多一非空。

    pi-runner 步 1 增补：tool_delta=OpenAI tool_calls 增量帧（delta.tool_calls 原样），
    finish=上游 finish_reason（末帧携带，原样透传）。"""

    delta: str = ""
    reasoning_delta: str = ""
    tool_delta: Any = None
    finish: str = ""


@dataclass(frozen=True)
class ClientCfg:
    """一次模型调用的客户端配置（真实 Key 只存在调用链内部，绝不回显）。"""

    base_url: str
    api_key: str
    model: str
    vendor: str = ""  # 增量 v1：厂商（thinking 参数映射用；空 = OpenAI 兼容兜底）

    @property
    def api_base(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def is_mock(self) -> bool:
        """mock 判定：模型名 mock 或无 base_url（占位渠道）。"""
        return self.model == "mock" or not self.base_url


# ── 思考档位厂商映射（增量架构 §3.4 映射表，纯函数表驱动）─────────
def build_thinking_params(vendor: str, level: str | None) -> dict[str, Any]:
    """把白名单档位值映射为各家 /chat/completions 协议参数；并入请求体顶层（R1）。

    - deepseek / glm / kimi：thinking.type 仅 enabled/disabled 两态（off→disabled）；
    - openai / custom（及其他 OpenAI 兼容系兜底）：reasoning_effort 原样透传；
    - qwen：off→enable_thinking=false；纯数字→+thinking_budget；其余→仅 enable；
    - mock / 空 level：{}（不产生任何参数）。
    """
    if not level:
        return {}
    v = (vendor or "").lower()
    if v == "mock":
        return {}
    if v in ("deepseek", "glm", "kimi"):
        return {"thinking": {"type": "disabled" if level == "off" else "enabled"}}
    if v == "qwen":
        if level == "off":
            return {"enable_thinking": False}
        if level.isdigit():
            return {"enable_thinking": True, "thinking_budget": int(level)}
        return {"enable_thinking": True}
    # openai / custom / 未知厂商：OpenAI 兼容系默认 reasoning_effort
    return {"reasoning_effort": level}


@external_retry()
async def _post_chat_completions(
    client: httpx.AsyncClient, cfg: ClientCfg, payload: dict[str, Any], timeout: httpx.Timeout
) -> httpx.Response:
    """非流式 /chat/completions 请求体；瞬时错误由 tenacity 重试（见模块 docstring）。"""
    resp = await client.post(
        f"{cfg.api_base}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


async def chat_once(
    cfg: ClientCfg,
    messages: list[dict[str, Any]],
    timeout: float = 30.0,
    usage_out: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    message_out: dict[str, Any] | None = None,
) -> str:
    """一次性（非流式）对话，返回完整文本。

    步 3 记账：传 usage_out（dict）时回填 {"input_tokens": x, "output_tokens": y}；
    mock 模式回填 0。费用不在此算（单价快照由 meter_service 记账时固化）。
    pi-runner 步 1 增补：tools/tool_choice 原样透传（OpenAI 兼容协议）；
    message_out 回填上游完整 message（含 tool_calls，网关非流式端点用）。
    """
    if cfg.is_mock:
        await asyncio.sleep(0.05)
        if usage_out is not None:
            usage_out.update({"input_tokens": 0, "output_tokens": 0})
        return _MOCK_PARSE_TEMPLATE.format(today=datetime.now().date().isoformat())

    payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    try:
        resp = await _post_chat_completions(
            get_http_client(), cfg, payload, httpx.Timeout(timeout, connect=10.0)
        )
        data = resp.json()
        if usage_out is not None:
            usage = data.get("usage") or {}
            usage_out.update(
                {
                    "input_tokens": int(usage.get("prompt_tokens") or 0),
                    "output_tokens": int(usage.get("completion_tokens") or 0),
                }
            )
        message = data["choices"][0]["message"]
        if message_out is not None:
            message_out.update(message)
        return str(message.get("content") or "").strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise UpstreamError(str(exc)[:300]) from exc


async def chat_stream(
    cfg: ClientCfg,
    messages: list[dict[str, Any]],
    thinking: str | None = None,
    timeout: float = 120.0,
    usage_out: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
) -> AsyncIterator[StreamChunk]:
    """SSE 流式对话，逐段 yield 双流帧（正文 delta / 思维 reasoning_delta）。

    步 3 记账：真实调用发 stream_options.include_usage，usage 从末帧取（OpenAI
    协议：usage 随最后一帧或不带 choices 的 usage 帧下发）；传 usage_out（dict）
    时回填 {"input_tokens": x, "output_tokens": y}。mock 模式回填 0。
    """
    if cfg.is_mock:
        # mock 也产出思维流，便于双流回归测试（P0-4 ② 语义不变）
        reasoning = MOCK_STREAM_REASONING
        for i in range(0, len(reasoning), 6):
            yield StreamChunk(reasoning_delta=reasoning[i : i + 6])
            await asyncio.sleep(0.01)
        reply = MOCK_STREAM_REPLY
        for i in range(0, len(reply), 4):
            yield StreamChunk(delta=reply[i : i + 4])
            await asyncio.sleep(0.01)
        if usage_out is not None:
            usage_out.update({"input_tokens": 0, "output_tokens": 0})
        return

    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    payload.update(build_thinking_params(cfg.vendor, thinking))
    try:
        client = get_http_client()
        async with client.stream(
            "POST",
            f"{cfg.api_base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                # 在流上下文内读错误体：退出上下文后流即关闭，异常处理器里读不到
                await resp.aread()
                raise UpstreamError(
                    f"HTTP {resp.status_code}: {resp.text[:300]} | req={json.dumps(payload, ensure_ascii=False)[:6000]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # 末帧 usage（include_usage）：可能随空 choices 的 usage 帧下发
                usage = chunk.get("usage")
                if usage_out is not None and usage:
                    usage_out.update(
                        {
                            "input_tokens": int(usage.get("prompt_tokens") or 0),
                            "output_tokens": int(usage.get("completion_tokens") or 0),
                        }
                    )
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                reasoning_content = delta.get("reasoning_content")
                tool_calls = delta.get("tool_calls")
                finish_reason = choices[0].get("finish_reason")
                # 双流透传：思维帧先于正文帧到达（DeepSeek R1 协议，R3）
                if reasoning_content:
                    yield StreamChunk(reasoning_delta=str(reasoning_content))
                if content:
                    yield StreamChunk(delta=str(content))
                # pi-runner 步 1 增补：tool_calls 增量与 finish_reason 原样透传
                if tool_calls:
                    yield StreamChunk(tool_delta=tool_calls)
                if finish_reason:
                    yield StreamChunk(finish=str(finish_reason))
    except httpx.HTTPError as exc:
        raise UpstreamError(str(exc)[:300]) from exc


async def chat_stream_passthrough(
    cfg: ClientCfg,
    messages: list[dict[str, Any]],
    *,
    thinking: str | None = None,
    timeout: float = 120.0,
    usage_out: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    extra: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """网关对外流式透传（pi-runner 步 1 增补）：上游 SSE 帧原样下发，仅过滤思维帧。

    与 chat_stream 的区别：不重序列化上游帧（chunk id、字段集合、帧顺序完全保真），
    消除重组引入的协议漂移——实测 Pi 客户端对重组后的 tool_calls 流会静默丢失
    工具状态（follow-up 请求缺 tool_calls/tool_call_id，上游 422）。
    仅按 N-增1 协议要求过滤「纯思维帧」（delta 只有 reasoning_content）。

    每帧 yield {"raw": 完整 SSE 行（含 data: 前缀与换行）, "finish": finish_reason 或 None}；
    上游 [DONE] 不透传（由调用方统一收尾）。usage 帧透传并回填 usage_out。
    """
    if cfg.is_mock:
        for delta, finish in (
            ({"content": MOCK_STREAM_REPLY}, None),
            ({}, "stop"),
        ):
            frame = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": cfg.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            yield {"raw": f"data: {json.dumps(frame, ensure_ascii=False)}\n\n", "finish": finish}
        if usage_out is not None:
            usage_out.update({"input_tokens": 0, "output_tokens": 0})
        return

    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    if extra:
        payload.update(extra)
    logging.getLogger(__name__).debug(
        "流式透传请求摘要：messages=%s tools=%s",
        [
            (m.get("role"), bool(m.get("tool_calls")), m.get("tool_call_id"))
            for m in messages
        ],
        len(tools or []),
    )
    payload.update(build_thinking_params(cfg.vendor, thinking))
    try:
        client = get_http_client()
        async with client.stream(
            "POST",
            f"{cfg.api_base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
        ) as resp:
            if resp.status_code >= 400:
                # 在流上下文内读错误体：退出上下文后流即关闭，异常处理器里读不到
                await resp.aread()
                raise UpstreamError(
                    f"HTTP {resp.status_code}: {resp.text[:300]} | req={json.dumps(payload, ensure_ascii=False)[:6000]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # usage 帧（无 choices）透传，同时回填计量
                usage = chunk.get("usage")
                if usage_out is not None and usage:
                    usage_out.update(
                        {
                            "input_tokens": int(usage.get("prompt_tokens") or 0),
                            "output_tokens": int(usage.get("completion_tokens") or 0),
                        }
                    )
                choices = chunk.get("choices") or []
                finish: str | None = None
                if choices:
                    delta = choices[0].get("delta") or {}
                    finish = choices[0].get("finish_reason")
                    # N-增1：纯思维帧不透出（同时含正文/工具调用的帧原样放行）
                    if delta.get("reasoning_content") and not (
                        delta.get("content") or delta.get("tool_calls")
                    ):
                        continue
                yield {"raw": f"data: {data}\n\n", "finish": finish}
    except httpx.HTTPError as exc:
        raise UpstreamError(str(exc)[:300]) from exc


@external_retry()
async def _get_models(client: httpx.AsyncClient, cfg: ClientCfg, timeout: httpx.Timeout) -> httpx.Response:
    """GET {base_url}/models；瞬时错误由 tenacity 重试（见模块 docstring）。"""
    resp = await client.get(
        f"{cfg.api_base}/models",
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp


async def fetch_model_names(cfg: ClientCfg, timeout: float = 15.0) -> list[str]:
    """调官方 GET {base_url}/models 拉取可用模型名（平铺）。"""
    try:
        resp = await _get_models(
            get_http_client(), cfg, httpx.Timeout(timeout, connect=10.0)
        )
        data = resp.json()
        return [str(item["id"]) for item in data.get("data", [])]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise UpstreamError(str(exc)[:300]) from exc
