"""LLM 网关服务：对 OpenAI 兼容上游的统一出口。

- 纯函数式：调用方查库后传入 ClientCfg(base_url/api_key/model)，本模块不查库；
- vendor=mock 或 base_url 为空 → 本地假实现不联网（开发/测试走完整链路）：
  chat_once 返回记账 parse 的严格 JSON 草稿（mock 模式 AI 记一笔开箱可用），
  chat_stream 返回固定寒暄文案；
- 不传 temperature 等覆盖参数（架构设计 Q9：部分严格端点对不支持的参数直接 400）。

调用参数策略（Q9）：一律用厂商默认；拉取模型入库的 meta 仅作展示。
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

# mock 的 chat_once 返回 parse 严格 JSON 草稿（date 动态填今天）
_MOCK_PARSE_TEMPLATE = (
    '{{"amount": 1580, "type": "expense", "category_suggestion": "餐饮",'
    ' "note": "mock 解析占位", "date": "{today}", "confidence": 0.99}}'
)


class UpstreamError(Exception):
    """上游 LLM 调用失败（网络/超时/非 2xx），路由层转 502。"""


@dataclass(frozen=True)
class ClientCfg:
    """一次模型调用的客户端配置（真实 Key 只存在调用链内部，绝不回显）。"""

    base_url: str
    api_key: str
    model: str

    @property
    def api_base(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def is_mock(self) -> bool:
        """mock 判定：模型名 mock 或无 base_url（占位渠道）。"""
        return self.model == "mock" or not self.base_url


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
    cfg: ClientCfg, messages: list[dict[str, Any]], timeout: float = 120.0
) -> AsyncIterator[str]:
    """SSE 流式对话，逐段 yield delta 文本。"""
    if cfg.is_mock:
        reply = MOCK_STREAM_REPLY
        for i in range(0, len(reply), 4):
            yield reply[i : i + 4]
            await asyncio.sleep(0.01)
        return

    payload: dict[str, Any] = {"model": cfg.model, "messages": messages, "stream": True}
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
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta
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
