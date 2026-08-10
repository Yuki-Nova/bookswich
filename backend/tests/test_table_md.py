"""表格质量门禁 + HTML→Markdown 转换测试（2026-08-10）。

覆盖：
- 6 道质量门禁（unbalanced/merged/impure/ragged/cols/rows/cell_too_long）
- 转换（<eq>→$、实体解码、竖线转义、基本结构、分隔行）
- 集成（_node_to_md 门禁分流）
"""
import re

from app.services.exporter import (
    format_table_md,
    format_html_table,
    _table_quality_gates,
    export_rebuilt,
)


# ── 门禁 ──────────────────────────────────────────────

def test_gate_unbalanced():
    """G1: <table 与 </table> 不配对 → 拒绝。"""
    html = "<table><tr><td>a</td><td>b</td></tr>正文没闭合"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason == "unbalanced"


def test_gate_merged():
    """G2: colspan/rowspan 合并单元格 → 拒绝。"""
    html = '<table><tr><td colspan="2">x</td><td>y</td></tr><tr><td>a</td><td>b</td><td>c</td></tr></table>'
    ok, reason = _table_quality_gates(html)
    assert not ok and reason == "merged"


def test_gate_impure():
    """G3: td 结构外有游离文本（正文混入）→ 拒绝。"""
    html = "<table><tr><td>a</td><td>b</td></tr>这是混入的正文长文本内容</table>"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason == "impure"


def test_gate_ragged():
    """G4: 行 td 数不一致 → 拒绝。"""
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason == "ragged"


def test_gate_cols_wide():
    """G5: 超过 8 列（数据列表/超宽表）→ 拒绝。"""
    html = "<table>" + "".join(f"<tr><td>{i}</td></tr>" for i in range(9)) + "</table>"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason.startswith("cols")


def test_gate_rows_long():
    """G5: 超过 20 行 → 拒绝。"""
    html = "<table>" + "".join(f"<tr><td>{i}</td><td>{i}</td></tr>" for i in range(21)) + "</table>"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason.startswith("rows")


def test_gate_cell_too_long():
    """G6: 单格超过 300 字符 → 拒绝。"""
    html = f"<table><tr><td>h</td><td>h2</td></tr><tr><td>{'x' * 350}</td><td>y</td></tr></table>"
    ok, reason = _table_quality_gates(html)
    assert not ok and reason == "cell_too_long"


def test_gate_clean_passes():
    """规整小表格通过全部门禁。"""
    html = (
        "<table><tr><td>试验者</td><td>次数n</td><td>频率</td></tr>"
        "<tr><td>Buffon</td><td>4040</td><td>0.5069</td></tr></table>"
    )
    ok, reason = _table_quality_gates(html)
    assert ok and reason == "ok"


# ── 转换 ──────────────────────────────────────────────

def test_convert_basic_structure():
    """基本表格 → Markdown（表头/分隔行/数据行）。"""
    html = (
        "<table><tr><td>试验者</td><td>次数n</td><td>频率</td></tr>"
        "<tr><td>Buffon</td><td>4040</td><td>0.5069</td></tr></table>"
    )
    md = format_table_md(html)
    lines = [l for l in md.split("\n") if l.strip()]
    assert lines[0] == "| 试验者 | 次数n | 频率 |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| Buffon | 4040 | 0.5069 |"
    # 前后空行分隔（防相邻表格合并渲染）
    assert md.startswith("\n") and md.endswith("\n")


def test_convert_eq_to_latex():
    """<eq> 标签 → $ 定界符。"""
    html = (
        "<table><tr><td>均值</td><td>公式</td></tr>"
        "<tr><td><eq>\\overline{x}</eq></td>"
        "<td><eq>\\overline{x} = \\frac{1}{n}\\sum_{i=1}^{n}x_i</eq></td></tr></table>"
    )
    md = format_table_md(html)
    assert "$\\overline{x}$" in md
    assert "$\\overline{x} = \\frac{1}{n}\\sum_{i=1}^{n}x_i$" in md


def test_convert_html_entity():
    """&lt;/&gt; 实体解码（防 LaTeX misplace &）。"""
    html = "<table><tr><td><eq>S_{k}&lt;0</eq></td><td>x</td></tr><tr><td>y</td><td>z</td></tr></table>"
    md = format_table_md(html)
    assert "$S_{k}<0$" in md
    assert "&lt;" not in md


def test_convert_pipe_escaping():
    """竖线转义：公式内 → \\vert，公式外 → \\|。"""
    html = (
        "<table><tr><td>条件概率</td><td><eq>P(A|B)</eq></td><td>P(A|B)</td></tr>"
        "<tr><td>a</td><td>b</td><td>c</td></tr></table>"
    )
    md = format_table_md(html)
    assert "$P(A\\vert B)$" in md          # 公式内 → \vert
    assert "P(A\\|B)" in md                 # 公式外 → \|
    assert "|B)" not in md.replace(r"\|", "")  # 无裸竖线


def test_convert_multiline_html():
    """拆行后的多行 HTML（format_html_table 产物）也能转换。"""
    html = format_html_table(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    )
    md = format_table_md(html)
    lines = [l for l in md.split("\n") if l.strip()]
    assert lines[0] == "| a | b |"


# ── 集成（真实导出）────────────────────────────────────

def test_full_export_gated_tables(rebuilt_full):
    """全书导出：门禁分流生效（有 Markdown 表格 + 有 HTML 保留）。"""
    lines = rebuilt_full.splitlines()
    md_rows = [l for l in lines if l.strip().startswith("|")]
    html_rows = [l for l in lines if l.strip().startswith("<table")]
    assert md_rows, "应至少有一个门禁通过的表格转成 Markdown"
    assert html_rows, "应至少有一个门禁拦截的表格保留 HTML"
    # 无超长行（Markdown 表格行 < 5000）
    assert max(len(l) for l in lines) <= 5000


def test_full_export_table_rows_consistent(rebuilt_full):
    """全书导出：所有 Markdown 表格块行列一致（无错乱）。"""
    lines = rebuilt_full.splitlines()

    def col_count(line):
        # 先移除转义竖线 \|（渲染为 | 不是列分隔符），再统计
        return len(line.replace(r"\|", "\x00").strip().strip("|").split("|"))

    blocks, cur = [], []
    for l in lines:
        if l.strip().startswith("|"):
            cur.append(l)
        else:
            if len(cur) >= 3:
                blocks.append(cur)
            cur = []
    if len(cur) >= 3:
        blocks.append(cur)
    for b in blocks:
        counts = {col_count(l) for l in b}
        assert len(counts) == 1, f"表格块列数不一致: {counts}, 块: {b[:2]}"
