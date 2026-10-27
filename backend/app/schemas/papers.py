"""请求/响应模型：文献（PRD §4.8，批次 2）。"""
import datetime as dt

from pydantic import BaseModel, Field


class PaperOut(BaseModel):
    id: int
    pmid: str
    title: str
    abstract: str
    abstract_zh: str  # 空串 = 未译
    journal: str
    authors: list[str]
    pub_date: dt.date | None
    tags: list[str]
    keywords: list[str]
    created_at: dt.datetime
    saved: bool = False  # 当前用户是否已收藏


class PaperDetailOut(PaperOut):
    note: str = ""  # 本人笔记（无则空串）
    explanation: str | None = None  # 全局 AI 解读缓存（无则 null）
    explanation_model: str = ""


class SaveResponse(BaseModel):
    saved: bool


class NoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class ExplainResponse(BaseModel):
    content: str
    model: str
    cached: bool  # true = 命中缓存


# ── 步 A：数据源清单 + AI 生成订阅关键词 ──────────────────
class SourceOut(BaseModel):
    key: str  # 源 key（subscribe_sources 存储值）
    name: str  # 展示名（勾选框用）


class SuggestKeywordsRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)  # 大白话研究方向描述


class SuggestKeywordsResponse(BaseModel):
    keywords: list[str]  # 8-12 个中英检索关键词（AI 生成，用户勾选确认后自行入库）
