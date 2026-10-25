"""render_service 单测（步 2 工程三小件：nh3 + markdown-it-py 统一渲染出口）。

本期只落函数不接线；安全断言以「恶意输入不得原样穿出」为准。
"""

from app.services.render_service import render_markdown, sanitize_html


def test_render_markdown_basic():
    html = render_markdown("# 标题\n\n正文 **加粗**")
    assert "<h1>标题</h1>" in html
    assert "<strong>加粗</strong>" in html


def test_render_markdown_gfm_table():
    html = render_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |")
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_render_markdown_strips_script_with_content():
    html = render_markdown("正文\n\n<script>alert(1)</script>")
    assert "<script>" not in html
    assert "alert(1)" not in html  # nh3 默认连内容一并清除（clean_content）


def test_render_markdown_strips_event_handler():
    html = render_markdown('<img src="https://example.test/a.png" onerror="alert(1)">')
    assert "onerror" not in html
    assert '<img src="https://example.test/a.png"' in html


def test_render_markdown_strips_dangerous_protocol():
    html = render_markdown('[点击](javascript:alert(1))')
    # 危险协议不生成 <a>（markdown-it 校验层拒收；字面文本原样转义显示，无害）
    assert "<a" not in html
    assert "点击" in html  # 链接文本保留


def test_render_markdown_keeps_safe_link():
    html = render_markdown("[官网](https://example.com)")
    assert 'href="https://example.com"' in html


def test_sanitize_html_strips_iframe():
    html = sanitize_html('<p>ok</p><iframe src="https://evil.example"></iframe>')
    assert "<iframe>" not in html
    assert "evil.example" not in html
    assert "<p>ok</p>" in html


def test_sanitize_html_strips_onclick():
    html = sanitize_html('<button onclick="steal()">b</button>')
    assert "onclick" not in html


def test_sanitize_html_keeps_basic_formatting():
    html = sanitize_html("<p>hi</p><strong>b</strong><em>i</em>")
    assert "<p>hi</p>" in html
    assert "<strong>b</strong>" in html
    assert "<em>i</em>" in html


def test_empty_input_returns_empty():
    assert render_markdown("") == ""
    assert sanitize_html("") == ""
