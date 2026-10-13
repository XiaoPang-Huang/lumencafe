"""LLM 抽象基类与公共定义。

所有供应商实现统一的三个异步接口：
- explain(title, abstract) -> str：文献中文四段式解读（一次性返回）
- translate_abstract(title, abstract) -> str：文献标题+摘要的中译文（一次性返回）
- chat_stream(messages) -> AsyncIterator[str]：小岛chat 对话（SSE 流式逐段产出）

未配置 provider / API Key 时抛 LLMNotConfiguredError，由路由层转成 503 友好文案。
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMNotConfiguredError(Exception):
    """LLM 未配置（供应商未选择或缺少 API Key）。"""


class BaseLLM(ABC):
    """LLM 供应商实现的基类。"""

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    async def explain(self, title: str, abstract: str) -> str:
        """根据标题+摘要生成中文四段式解读（研究背景/核心发现/临床意义/局限与注意）。"""

    @abstractmethod
    async def translate_abstract(self, title: str, abstract: str) -> str:
        """把英文标题+摘要翻译成中文（标题一行 + 摘要译文），不添加原文没有的内容。"""

    @abstractmethod
    def chat_stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """流式对话：messages 为 OpenAI 兼容格式（含 system），逐段产出回复文本。"""


# 解读提示词：四段式，中文、简短，面向非专业读者也能看懂
EXPLAIN_PROMPT = (
    "你是一位温柔耐心的科研助手。请阅读下面的医学文献标题和摘要，"
    "用中文写一段简明解读，严格分四段，每段以小标题开头：\n"
    "【研究背景】这项研究想解决什么问题（2~3 句话）；\n"
    "【核心发现】主要结果是什么（2~3 句话）；\n"
    "【临床意义】对医生和患者可能有什么帮助（2~3 句话）；\n"
    "【局限与注意】有哪些需要注意的局限（1~2 句话）。\n"
    "语言平实易懂，没有医学背景的普通读者也能看懂，不要堆砌术语。"
)


def build_explain_messages(title: str, abstract: str) -> list[dict[str, str]]:
    """构造解读请求的 messages（OpenAI 兼容格式）。"""
    user_content = f"标题：{title}\n\n摘要：{abstract or '（无摘要）'}"
    return [
        {"role": "system", "content": EXPLAIN_PROMPT},
        {"role": "user", "content": user_content},
    ]


# 翻译提示词：忠实通顺、不加戏、直接给译文
TRANSLATE_PROMPT = (
    "你是医学文献翻译助手。请把用户给出的英文文献标题和摘要翻译成通顺的中文。"
    "要求：忠实原意、术语准确、保留关键数据；不要添加原文没有的内容；"
    "不要任何解释、前言或后缀，直接输出译文。"
    "格式：第一行「标题：<中文标题>」，空一行，然后是摘要的中文译文。"
)


def build_translate_messages(title: str, abstract: str) -> list[dict[str, str]]:
    user_content = f"标题：{title}\n\n摘要：{abstract}"
    return [
        {"role": "system", "content": TRANSLATE_PROMPT},
        {"role": "user", "content": user_content},
    ]


# 小岛chat 系统提示词：普通 AI 聊天伙伴，轻松直接
CHAT_SYSTEM_PROMPT = (
    "你是「小岛chat」，一个轻松的 AI 聊天伙伴。你友好、自然，像朋友一样聊天。"
    "回答简短（一般不超过 150 字）、口语化，不用列表体，不说教。"
    "什么话题都可以聊：日常琐事、学习科研、情绪心情、脑洞问题。"
    "不懂就直说不懂；涉及疾病诊断、用药等医疗问题，提醒对方咨询医生，不给出医疗建议。"
)
