"""LLM 供应商实现与选择逻辑。

渠道来源两级：
1. llm_providers 表（管理页维护，运行时热生效）——get_llm(feature) 优先使用；
2. 环境变量 ISLAND_LLM_PROVIDER + Key（首次启动会种子进表，未配置表时兜底）。

未配置时抛 LLMNotConfiguredError，路由层捕获后返回 503 友好文案。
"""
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from sqlalchemy import func, select

from ..config import settings
from ..db import SessionLocal
from ..models import LLMProvider, UserSetting
from .base import BaseLLM, LLMNotConfiguredError, build_explain_messages, build_translate_messages

logger = logging.getLogger("island.llm")

# 厂家模板：添加渠道时的默认 base_url / model（均可再改）
VENDOR_TEMPLATES = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "openai": {"base_url": "", "model": ""},
    "mock": {"base_url": "", "model": "mock"},
}

# 用途 → llm_routing 设置里的 key；chat 兜底名
FEATURES = ("chat", "explain", "translate")
ROUTING_SETTING_KEY = "llm_routing"
SPACE_USER = "space"


async def _openai_stream(api_base: str, key: str, model: str, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """OpenAI 兼容接口的 SSE 流式对话（DeepSeek / Kimi 等通用）。

    注意：不发送 temperature 等可选参数——部分严格端点（如 Kimi for Coding）
    对不支持的参数直接 400。
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        async with client.stream(
            "POST",
            f"{api_base}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


class OpenAICompatibleLLM(BaseLLM):
    """任意 OpenAI 兼容渠道（DeepSeek / Kimi / 自建网关等）。"""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        if not base_url or not api_key:
            raise LLMNotConfiguredError("渠道缺少 base_url 或 api_key")
        super().__init__(model=model)
        self.api_base = base_url.rstrip("/")
        self._key = api_key

    async def _chat(self, messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                f"{self.api_base}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data["choices"][0]["message"]["content"]).strip()

    async def explain(self, title: str, abstract: str) -> str:
        return await self._chat(build_explain_messages(title, abstract))

    async def translate_abstract(self, title: str, abstract: str) -> str:
        return await self._chat(build_translate_messages(title, abstract))

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        async for delta in _openai_stream(self.api_base, self._key, self.model, messages):
            yield delta


class MockLLM(BaseLLM):
    """本地开发用：不联网，流式返回固定文案，体验完整链路。"""

    def __init__(self) -> None:
        super().__init__(model="mock")

    async def explain(self, title: str, abstract: str) -> str:
        return "（mock 解读）这是本地开发占位文案：配置 ISLAND_LLM_PROVIDER=deepseek/kimi 并填入 Key 后，这里会生成真实的四段式中文解读。"

    async def translate_abstract(self, title: str, abstract: str) -> str:
        return f"标题：{title}\n\n（mock 中文摘要）配置真实 LLM 后，这里会输出通顺的中文译文。"

    async def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        reply = "你好呀，我是小岛chat。现在是本地 mock 模式，配置真实模型后我就能正经聊天了。"
        for ch in reply:
            yield ch
            await asyncio.sleep(0.02)


def build_llm(vendor: str, base_url: str, api_key: str, model: str) -> BaseLLM:
    """按厂家类型构造实例。"""
    if vendor == "mock":
        return MockLLM()
    return OpenAICompatibleLLM(base_url, api_key, model or VENDOR_TEMPLATES.get(vendor, {}).get("model", ""))


async def _routing_map(db) -> dict[str, int]:
    row = (
        await db.execute(
            select(UserSetting).where(
                UserSetting.user_id == SPACE_USER,
                UserSetting.scope == "space",
                UserSetting.key == ROUTING_SETTING_KEY,
            )
        )
    ).scalar_one_or_none()
    if row and isinstance(row.value, dict):
        return {k: int(v) for k, v in row.value.items() if str(k) in FEATURES and v is not None}
    return {}


async def get_llm(feature: str = "chat") -> BaseLLM:
    """按用途取 LLM：DB 渠道（llm_providers + llm_routing）优先，env 兜底。

    路由未绑定或绑定的渠道已停用/删除时，回落到第一个启用的渠道；
    表里没有任何启用渠道时退回环境变量配置。
    """
    try:
        async with SessionLocal() as db:
            routing = await _routing_map(db)
            provider: LLMProvider | None = None
            pid = routing.get(feature)
            if pid is not None:
                provider = (
                    await db.execute(select(LLMProvider).where(LLMProvider.id == pid))
                ).scalar_one_or_none()
            if provider is None or not provider.enabled:
                provider = (
                    await db.execute(
                        select(LLMProvider)
                        .where(LLMProvider.enabled.is_(True))
                        .order_by(LLMProvider.id.asc())
                    )
                ).scalars().first()
            if provider is not None:
                return build_llm(provider.vendor, provider.base_url, provider.api_key, provider.model)
    except LLMNotConfiguredError:
        raise
    except Exception:
        logger.exception("读取 LLM 渠道失败，退回环境变量配置")

    # ---- 环境变量兜底（与旧行为一致）----
    provider = (settings.llm_provider or "").strip().lower()
    if provider == "mock":
        return MockLLM()
    if provider == "deepseek" and settings.deepseek_key:
        return OpenAICompatibleLLM(
            VENDOR_TEMPLATES["deepseek"]["base_url"], settings.deepseek_key,
            VENDOR_TEMPLATES["deepseek"]["model"],
        )
    if provider == "kimi" and settings.kimi_key:
        return OpenAICompatibleLLM(
            VENDOR_TEMPLATES["kimi"]["base_url"], settings.kimi_key,
            VENDOR_TEMPLATES["kimi"]["model"],
        )
    raise LLMNotConfiguredError(f"未配置 LLM 供应商：{settings.llm_provider!r}")


async def ensure_llm_seed() -> None:
    """首次启动：env 配置非空而 llm_providers 为空时，种子一条渠道。"""
    provider = (settings.llm_provider or "").strip().lower()
    key = ""
    if provider == "deepseek":
        key = settings.deepseek_key or ""
    elif provider == "kimi":
        key = settings.kimi_key or ""
    elif provider != "mock":
        return
    async with SessionLocal() as db:
        count = (
            await db.execute(select(func.count(LLMProvider.id)))
        ).scalar_one()
        if count > 0:
            return
        tpl = VENDOR_TEMPLATES.get(provider, {})
        db.add(LLMProvider(
            name=f"{provider}（env 导入）",
            vendor=provider,
            base_url=tpl.get("base_url", ""),
            api_key=key,
            model=tpl.get("model", ""),
            enabled=True,
        ))
        await db.commit()
        logger.info("已从环境变量导入 LLM 渠道：%s", provider)


async def test_provider(provider: LLMProvider) -> dict[str, Any]:
    """测试渠道连通性：发一个最小请求，返回 {ok, latency_ms, error}。"""
    start = time.time()
    try:
        llm = build_llm(provider.vendor, provider.base_url, provider.api_key, provider.model)
        if isinstance(llm, MockLLM):
            return {"ok": True, "latency_ms": 0, "error": ""}
        reply = await llm._chat([{"role": "user", "content": "ping，回复 pong 即可"}])
        return {"ok": bool(reply), "latency_ms": int((time.time() - start) * 1000), "error": ""}
    except Exception as exc:
        return {"ok": False, "latency_ms": int((time.time() - start) * 1000), "error": str(exc)[:300]}
