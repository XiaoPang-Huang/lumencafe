"""SkillHub 平台代理契约（架构设计-增量 v1 §3.6，Q7 降级：Mock 先行）。

- SkillHubProvider 协议冻结为 search/get 两方法 + SkillItem/SkillDetail 两结构；
- 本期交付 MockSkillHubProvider（内置演示 skill 集，prompt ≤4KB）；
- 真实 API 就绪后仅需替换 get_provider() 返回的实现类（集成点唯一，路由与表结构不变）。

真实 API 集成点（平台侧答复后在此实现）：
    class HttpSkillHubProvider:
        def __init__(self, base_url: str, api_key: str): ...
        async def search(...) -> 调 GET  {base_url}/api/v1/skills?q=&page=&page_size=
        async def get(...)     -> 调 GET  {base_url}/api/v1/skills/{id}（含 prompt 包）
    并在 get_provider() 中读 settings.skillhub_base_url 非空则实例化该类。
"""
from typing import NamedTuple, Protocol


class SkillItem(NamedTuple):
    skillhub_id: str
    name: str
    icon: str
    description: str


class SkillDetail(NamedTuple):
    skillhub_id: str
    name: str
    icon: str
    description: str
    prompt: str  # ≤4KB（N-增5），服务端存储、用户不可改写


class SkillHubProvider(Protocol):
    """SkillHub 平台只读契约：列表搜索 + 按 id 拉取 skill 包。"""

    async def search(self, q: str, page: int, page_size: int) -> tuple[list[SkillItem], int]:
        """返回 (当前页条目, 总数)。"""
        ...

    async def get(self, skillhub_id: str) -> SkillDetail | None:
        """按平台 ID 拉取 skill 包；不存在返回 None。"""
        ...


class MockSkillHubProvider:
    """本期交付：内置 5 个演示 skill（契约先行，Mock 可替换）。

    每个 skill 的 prompt 为预设片段（安装时整体存入 user_skills.prompt，
    在 POST /chat 组装 system 时注入；用户不可改写）。
    """

    def __init__(self) -> None:
        self._items: list[SkillDetail] = [
            SkillDetail(
                skillhub_id="mock-translation-polish",
                name="翻译润色",
                icon="spark",
                description="中英互译与表达润色，让回复更地道准确",
                prompt=(
                    "【技能：翻译润色】当用户要求翻译或润色文字时：先给出准确译文/润色结果，"
                    "必要时附一句简要说明（如措辞取舍）。保持原文语气与格式，专名不翻译。"
                ),
            ),
            SkillDetail(
                skillhub_id="mock-code-review",
                name="代码审查",
                icon="doc",
                description="审阅代码片段，指出 bug、隐患与可读性问题",
                prompt=(
                    "【技能：代码审查】当用户贴出代码时：按「问题清单 → 修改建议 → 重写片段」"
                    "结构回答；问题按严重程度排序，注明行号；不重写与问题无关的代码。"
                ),
            ),
            SkillDetail(
                skillhub_id="mock-weekly-report",
                name="周报助手",
                icon="chart",
                description="把零散事项整理成结构清晰的周报",
                prompt=(
                    "【技能：周报助手】当用户要求写周报/总结时：按「本周完成 / 数据亮点 / "
                    "问题与风险 / 下周计划」四段输出；事项可合并归类，不虚构数据。"
                ),
            ),
            SkillDetail(
                skillhub_id="mock-sql-helper",
                name="SQL 助手",
                icon="gear",
                description="生成与优化 SQL，解释执行计划",
                prompt=(
                    "【技能：SQL 助手】当用户询问数据库/SQL 时：先确认表结构假设再给出 SQL；"
                    "附简短说明与索引建议；方言不明时默认 PostgreSQL 并注明。"
                ),
            ),
            SkillDetail(
                skillhub_id="mock-meeting-notes",
                name="会议纪要",
                icon="book",
                description="把会议记录整理为结论、待办与责任人清单",
                prompt=(
                    "【技能：会议纪要】当用户提供会议内容时：输出「结论 / 待办（含责任人）/ "
                    "待定问题」三部分；待办用可勾选的清单格式，信息缺失处标注「待确认」。"
                ),
            ),
        ]

    async def search(self, q: str, page: int, page_size: int) -> tuple[list[SkillItem], int]:
        q = (q or "").strip().lower()
        matched = [
            item
            for item in self._items
            if not q
            or q in item.name.lower()
            or q in item.description.lower()
            or q in item.skillhub_id.lower()
        ]
        start = (page - 1) * page_size
        page_items = [
            SkillItem(
                skillhub_id=i.skillhub_id,
                name=i.name,
                icon=i.icon,
                description=i.description,
            )
            for i in matched[start : start + page_size]
        ]
        return page_items, len(matched)

    async def get(self, skillhub_id: str) -> SkillDetail | None:
        for item in self._items:
            if item.skillhub_id == skillhub_id:
                return item
        return None


def get_provider() -> SkillHubProvider:
    """工厂：当前恒返回 Mock；settings.skillhub_base_url 非空则实例化真实实现（预留）。"""
    # if settings.skillhub_base_url:
    #     return HttpSkillHubProvider(settings.skillhub_base_url, settings.skillhub_api_key)
    return MockSkillHubProvider()
