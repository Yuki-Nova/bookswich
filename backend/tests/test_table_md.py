"""HTML table → Markdown table 转换测试（表格内公式渲染）。

验证（2026-08-09）：
- <eq>...</eq> → $...$（含 HTML 实体解码 &lt;/&gt;）
- 基本表格结构转换
- colspan 复制平铺
"""
from app.services.exporter import format_table_md


def test_eq_to_latex():
    """<eq> 标签转 $ 定界符。"""
    html = (
        "<table><tr><td>名称</td><td>公式</td></tr>"
        "<tr><td>均值<eq>\\overline{x}</eq></td>"
        "<td><eq>\\overline{x} = \\frac{1}{n}\\sum_{i=1}^{n}x_i</eq></td></tr></table>"
    )
    md = format_table_md(html)
    assert "$\\overline{x}$" in md
    assert "$\\overline{x} = \\frac{1}{n}\\sum_{i=1}^{n}x_i$" in md


def test_html_entity_unescape():
    """&lt;/&gt; 实体解码，避免 LaTeX misplace &。"""
    html = "<table><tr><td><eq>S_{k}&lt;0</eq></td><td><eq>S_{k}&gt;0</eq></td></tr></table>"
    md = format_table_md(html)
    assert "$S_{k}<0$" in md
    assert "$S_{k}>0$" in md
    assert "&lt;" not in md
    assert "&gt;" not in md


def test_basic_table_structure():
    """基本表格 → Markdown 表格（含分隔行）。"""
    html = (
        "<table><tr><td>试验者</td><td>次数n</td><td>频率</td></tr>"
        "<tr><td>Buffon</td><td>4040</td><td>0.5069</td></tr></table>"
    )
    md = format_table_md(html)
    lines = md.split("\n")
    assert lines[0] == "| 试验者 | 次数n | 频率 |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| Buffon | 4040 | 0.5069 |"


def test_colspan_duplicate():
    """colspan=2 展开补空列，列对齐。"""
    html = (
        "<table><tr><td colspan=\"2\">定性数据</td><td>定量数据</td></tr>"
        "<tr><td>定类</td><td>定序</td><td>数值</td></tr></table>"
    )
    md = format_table_md(html)
    lines = md.split("\n")
    # colspan=2 → 内容 + 空列
    assert lines[0] == "| 定性数据 |  | 定量数据 |"
    assert lines[1] == "| --- | --- | --- |"
    # 数据行 3 列对齐
    assert lines[2] == "| 定类 | 定序 | 数值 |"


def test_rowspan_expand():
    """rowspan=2 后续行对应列补空单元格。"""
    html = (
        "<table><tr><td rowspan=\"2\">合并</td><td>a</td><td>b</td></tr>"
        "<tr><td>c</td><td>d</td></tr></table>"
    )
    md = format_table_md(html)
    lines = md.split("\n")
    assert lines[0] == "| 合并 | a | b |"
    # 第二行：合并列补空
    assert lines[2] == "|  | c | d |"


def test_nested_html_in_eq():
    """<eq> 内嵌套 <sup> 等标签保留（LaTeX 渲染前不剥标签）。"""
    html = "<table><tr><td><eq>x^{2}</eq></td></tr></table>"
    md = format_table_md(html)
    assert "$x^{2}$" in md


def test_condition_probability_pipe_escaped():
    """条件概率 P(A|B) 的竖线转义：公式内 → \\vert，防切断表格列。"""
    html = (
        "<table><tr><td>条件概率公式</td>"
        "<td><eq>P(A|B)=\\frac{P(AB)}{P(B)}</eq></td></tr></table>"
    )
    md = format_table_md(html)
    # 公式内 | → \vert（LaTeX 数学模式语义正确）
    assert "$P(A\\vert B)=\\frac{P(AB)}{P(B)}$" in md
    assert "|B)" not in md  # 裸 | 不得残留
