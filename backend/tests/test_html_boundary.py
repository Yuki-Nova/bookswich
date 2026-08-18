"""A1: HTML 表格与 Markdown 标题/正文边界回归测试。

背景（2026-08-18 已确认问题）：_node_to_md 的表格保留路径
（format_html_table）只做 `><` 排版换行，输出不带前后空行 →
表格行紧贴正文行时，CommonMark 的 HTML 块（以 <table 开头的
类型 6 块）会延续到第一个空行，把 </table> 后的正文行/下一行
标题吞进 HTML 块，Obsidian/Typora 不识别。

修复：HTML 保留路径输出与 format_table_md 对称，前后各补一个 \n；
节点级 join 后的 \n{3,} 折叠只压 3+ 连续空行，不吞边界空行。
"""
from app.services.exporter import _node_to_md

# 带 rowspan 的表格——门禁 G2 拦截，恰好走 HTML 保留路径
BAD_TABLE = (
    '<table><tr><td rowspan="2">合并</td><td>a</td></tr>'
    "<tr><td>b</td></tr></table>"
)


def _node(title="第一章", lines=None, children=None, level=1):
    return {
        "title": title,
        "level": level,
        "lines": lines or [title],
        "children": children or [],
        "board": False,
    }


def test_html_table_preceded_by_text():
    """表格前紧贴正文行 → 导出后表格前有空行。"""
    node = _node(lines=["第一章", "表 2-1 试验数据如下", BAD_TABLE])
    md = _node_to_md(node)
    assert "\n表 2-1 试验数据如下\n\n<table" in md


def test_html_table_followed_by_text():
    """表格后紧贴正文行 → 正文前有空行（防正文被 HTML 块吞掉）。"""
    node = _node(lines=["第一章", BAD_TABLE, "注：数据来自教材实验"])
    md = _node_to_md(node)
    assert "</table>\n\n注：数据来自教材实验" in md


def test_html_table_followed_by_heading():
    """表格后紧跟子标题 → 表格与标题之间有空行（Obsidian 识别标题）。"""
    node = _node(
        lines=["第一章", BAD_TABLE],
        children=[_node(title="第二节", lines=["第二节", "内容"], level=2)],
    )
    md = _node_to_md(node)
    assert "</table>\n\n## 第二节" in md


def test_html_table_bytes_unchanged():
    """保留路径不改表格内容：去排版换行后与原始 HTML 一致。"""
    node = _node(lines=["第一章", BAD_TABLE])
    md = _node_to_md(node)
    assert BAD_TABLE in md.replace("\n", "")


def test_html_table_boundary_not_over_collapsed():
    """\n{3,} 折叠不吞边界：表格与标题之间恰好 1 个空行（不粘连也不变 2 个）。"""
    node = _node(
        lines=["第一章", BAD_TABLE],
        children=[_node(title="第二节", lines=["第二节", "内容"], level=2)],
    )
    md = _node_to_md(node)
    assert "\n</table>\n\n## 第二节\n" in md
    assert "\n</table>\n\n\n## 第二节" not in md