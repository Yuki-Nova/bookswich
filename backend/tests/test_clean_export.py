"""深度清洗与图片引用兼容测试（2026-08-16 借鉴 mineru-tianshu 的导出清洗逻辑）。

借鉴点：
- A. 深度清洗：HTML 双层反转义 / 删 <del> 幻觉标签 / 连续空行折叠
  （跳过 Tianshu 的整段重复去重与 ~ 替换——数学教材公式风险大于收益）
- B. 图片引用兼容：<img src="images/x.jpg"> 归一化为 Markdown 语法，
  打包/统计链路 IMG_RE 兼容两种写法
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.exporter import (
    IMG_RE,
    _img_rel,
    _node_to_md,
    clean_markdown,
    normalize_html_images,
)


# ── A. 深度清洗 ─────────────────────────────────────────


def test_clean_markdown_double_unescape():
    """双重 HTML 反转义：&amp;lt; → <（MinerU 常见双层转义）。"""
    assert clean_markdown("a &amp;lt; b &amp;gt; c &amp;amp; d") == "a < b > c & d"


def test_clean_markdown_del_tags_removed():
    """模型幻觉 <del> 标签删除，内容保留。"""
    assert clean_markdown("x<del>y</del>z") == "xyz"


def test_clean_markdown_collapses_blank_lines():
    """3+ 连续空行折叠为 1 个空行。"""
    assert clean_markdown("a\n\n\n\n\nb") == "a\n\nb"


def test_clean_markdown_applies_to_math_too():
    """公式内 HTML 实体同样被反转义（实体属排版层转义，公式文本应解码）。"""
    s = "公式 $P(a &amp; b) = 1$\n\n\n\n结束"
    assert clean_markdown(s) == "公式 $P(a & b) = 1$\n\n结束"


def test_clean_markdown_handles_single_escape():
    """单层转义（&gt;）也能被修（暴力替换残留）。"""
    assert clean_markdown("a &gt; b") == "a > b"


def test_clean_markdown_empty_and_none_content():
    """空输入安全。"""
    assert clean_markdown("") == ""
    assert clean_markdown(None) == ""


# ── B. HTML <img> 归一化 ────────────────────────────────


def test_normalize_html_img_to_markdown():
    """<img src="images/x.jpg"> → Markdown 图片语法（Obsidian 友好）。"""
    assert normalize_html_images('<img src="images/a.jpg">') == "![](images/a.jpg)"


def test_normalize_html_img_single_quote():
    """单引号 src 同样归一化。"""
    assert normalize_html_images("<img src='images/b.png'>") == "![](images/b.png)"


def test_normalize_html_img_keeps_remote_urls():
    """外部 URL 图片不动（非本地 images/ 引用，不归一到打包链路）。"""
    s = '<img src="https://example.com/x.png">'
    assert normalize_html_images(s) == s


def test_normalize_html_img_keeps_markdown():
    """Markdown 图片语法原样保留。"""
    s = "![图](images/a.jpg)"
    assert normalize_html_images(s) == s


# ── IMG_RE 兼容两种写法（打包/统计链路）────────────────


def test_img_re_matches_html_src():
    """IMG_RE 能抓到 HTML 标签里的 images/ 相对路径。"""
    m = IMG_RE.search('<img src="images/a.jpg">')
    assert m and _img_rel(m) == "images/a.jpg"


def test_img_re_still_matches_markdown():
    """IMG_RE 旧能力不回归：Markdown 语法仍能抓。"""
    m = IMG_RE.search("![](images/a.jpg)")
    assert m and _img_rel(m) == "images/a.jpg"


# ── 节点导出集成 ────────────────────────────────────────


def test_node_to_md_normalizes_html_img():
    """node lines 含 HTML 图片引用时，导出文本统一为 Markdown 语法。"""
    node = {
        "title": "1.1 节",
        "level": 2,
        "lines": ["1.1 节", "正文", '<img src="images/f1.png">'],
    }
    out = _node_to_md(node)
    assert "![](images/f1.png)" in out
    assert "<img" not in out


def test_node_to_md_table_line_untouched():
    """表格行不被深度清洗改动（CLAUDE.md 约定 #1：表格内容零改动）。"""
    node = {
        "title": "1.1 节",
        "level": 2,
        "lines": [
            "1.1 节",
            "正文",
            "<table><tr><td>a &amp; b</td></tr></table>",
        ],
    }
    out = _node_to_md(node)
    assert "<table>" in out
    assert "a &amp; b" in out, "表格内实体不清洗（保持原样）"


def test_node_to_md_collapses_blank_lines():
    """节点级输出折叠 3+ 连续空行（clean_markdown 逐行调用无跨行上下文，
    折叠必须在节点 join 后生效）。"""
    node = {
        "title": "1.1 节",
        "level": 2,
        "lines": ["1.1 节", "正文A", "", "", "", "正文B"],
    }
    out = _node_to_md(node)
    assert "\n\n\n" not in out, "不应出现 3+ 连续空行"
    assert "正文A\n\n正文B" in out


def test_format_table_md_unescapes_cells():
    """Markdown 表格单元格实体解码：P(B)&gt;0 → P(B)>0。

    门禁通过转 Markdown 的表格，普通单元格文本同样要解码实体
    （此前只对 <eq> 内容解码，纯文本单元格残留 &gt;/&lt; 会渲染成字面文本）。
    """
    from app.services.exporter import format_table_md

    tbl = (
        "<table><tr><td>条件</td><td>P(B)&gt;0</td></tr>"
        "<tr><td>值</td><td>a &amp; b</td></tr></table>"
    )
    out = format_table_md(tbl)
    assert "P(B)>0" in out
    assert "&gt;" not in out
    assert "a & b" in out
    assert "&amp;" not in out


def test_format_table_md_normalizes_adjacent_math():
    """表格内并列公式定界符净化：$...$  $...$ → $...$ $...$（Typora 识别）。

    MinerU 用 `$  $`（结束$ + 双空格 + 开始$）连接相邻公式，Typora 不识别
    第二个公式的前导空格定界符 → 表格内并列公式第二个渲染失败。
    format_table_md 需先压平公式间双空格，再对单元格做定界符净化。
    """
    from app.services.exporter import format_table_md

    tbl = (
        "<table><tr><td>条件</td><td> $P(AB)=P(A)P(B)$  $A_1,A_2$ 相互独立</td></tr>"
        "<tr><td>值</td><td>均值 $ \\overline{x} $ </td></tr></table>"
    )
    out = format_table_md(tbl)
    # 公式间双空格压成单空格（两个独立公式，Typora 可识别）
    assert "$P(AB)=P(A)P(B)$ $A_1,A_2$" in out
    # 单公式内侧空格净化
    assert "均值 $\\overline{x}$" in out
    assert "$ \\overline{x} $" not in out