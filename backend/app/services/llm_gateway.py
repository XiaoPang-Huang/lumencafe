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
"""
import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

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
    """双流协议帧（R3）：delta=正文增量，reasoning_delta=思维增量，二者至多一非空。"""

    delta: str = ""
    reasoning_delta: str = ""


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


async def chat_once(
    cfg: ClientCfg, messages: list[dict[str, Any]], timeout: float = 30.0
) -> str:
    """一次性（非流式）对话，返回完整文本。"""
    if cfg.is_mock:
        await asyncio.sleep(0.05)
        return _MOCK_PARSE_TEMPLATE.format(today=datetime.now().date().isoformat())

    payload: dict[str, Any] = {"model": cfg.model, "messages": messages}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0)
        ) as client:
            resp = await client.post(
                f"{cfg.api_base}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"]).strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise UpstreamError(str(exc)[:300]) from exc


async def chat_stream(
    cfg: ClientCfg,
    messages: list[dict[str, Any]],
    thinking: str | None = None,
    timeout: float = 120.0,
) -> AsyncIterator[StreamChunk]:
    """SSE 流式对话，逐段 yield 双流帧（正文 delta / 思维 reasoning_delta）。"""
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
        return

    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "stream": True,
    }
    payload.update(build_thinking_params(cfg.vendor, thinking))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0)
        ) as client, client.stream(
            "POST",
            f"{cfg.api_base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content")
                    reasoning_content = delta.get("reasoning_content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                # 双流透传：思维帧先于正文帧到达（DeepSeek R1 协议，R3）
                if reasoning_content:
                    yield StreamChunk(reasoning_delta=str(reasoning_content))
                if content:
                    yield StreamChunk(delta=str(content))
    except httpx.HTTPError as exc:
        raise UpstreamError(str(exc)[:300]) from exc


async def fetch_model_names(cfg: ClientCfg, timeout: float = 15.0) -> list[str]:
    """调官方 GET {base_url}/models 拉取可用模型名（平铺）。"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0)
        ) as client:
            resp = await client.get(
                f"{cfg.api_base}/models",
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [str(item["id"]) for item in data.get("data", [])]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise UpstreamError(str(exc)[:300]) from exc
