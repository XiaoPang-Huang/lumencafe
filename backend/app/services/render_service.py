"""统一渲染出口（步 2 工程三小件之一：nh3 + markdown-it-py，架构设计-增量 v2 D10）。

两段式：markdown-it-py 渲染 Markdown（允许内嵌 HTML 原样通过）→ nh3 消毒
（XSS 清洗，安全边界在 nh3）。chat 消息 / 论文预览 / 笔记等一切
「Markdown → HTML」出口将来共用本模块，禁止绕过消毒直接出 HTML。

本期只落函数不接线（拍板：随真前端启用时再接到各出口）。将来启用点：
- chat 路由的渲染出口 / 管理端消息预览（app/routers/chat.py）；
- papers 路由的摘要、笔记 HTML 预览（app/routers/papers.py）；
- 未来笔记类应用的富文本出口。

组件选型：nh3（MIT，Rust ammonia 绑定，Mozilla 白名单派系）、
markdown-it-py（MIT，CommonMark + GFM 扩展），见组件选型-v1 §7.1。
"""
import nh3
from markdown_it import MarkdownIt

# commonmark 基底 + GFM 扩展（表格/删除线/链接识别）；html=True 让内嵌 HTML
# 进入渲染产物，消毒统一交由 nh3（两段式，不在渲染层做安全决策）。
_MD = (
    MarkdownIt("commonmark")
    .enable("table")
    .enable("strikethrough")
    .enable("linkify")
)
_MD.options["html"] = True


def render_markdown(text: str) -> str:
    """Markdown → 消毒后 HTML（统一安全出口；未消毒 HTML 一律不得进前端）。"""
    if not text:
        return ""
    return nh3.clean(_MD.render(text))


def sanitize_html(html: str) -> str:
    """对已是 HTML 的文本消毒（非 Markdown 来源的富文本出口用）。"""
    if not html:
        return ""
    return nh3.clean(html)
