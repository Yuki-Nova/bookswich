"""A4: 导出物专项回归扫描规则边界测试。

覆盖规则（backend/app/services/verify_export.py）：
- unexpected_img_tag / unexpected_del_tag：表格外残影报错，表格内（约定 #1
  零改动）不误报
- blank_run：3+ 连续空行报错，2 个空行不报
- math_unclosed：奇数 $ 定界符报错（表格内跳过、$$ 块级不误报）
- table_touch：</table> 后无空行紧贴正文/标题报错（A1 同类问题）
- missing_image：图片引用但文件不存在（需 img_dir）
- md_table_ragged：Markdown 表格块列数不一致
- html_table_ragged：HTML 表格 tr 行 td 数不一致（warning 级，不阻断）
- 允许项：HTML 表格内 &amp;/rowspan/<eq>/<img> 不误报
"""
import pytest

from app.services.verify_export import scan_export


def rules(issues):
    return {x["rule"] for x in issues}


# ── img / del 残影标签 ──────────────────────────────

def test_img_tag_outside_table_reported():
    issues = scan_export("正文 <img src='images/a.jpg'> 内容")
    assert "unexpected_img_tag" in rules(issues)


def test_img_inside_html_table_not_reported():
    md = "<table>\n<tr><td><img src='images/a.jpg'></td></tr>\n</table>"
    assert "unexpected_img_tag" not in rules(scan_export(md))


def test_del_tag_outside_table_reported():
    issues = scan_export("文字<del>幻觉删除</del>")
    assert "unexpected_del_tag" in rules(issues)


def test_del_inside_html_table_not_reported():
    md = "<table>\n<tr><td><del>x</del></td></tr>\n</table>"
    assert "unexpected_del_tag" not in rules(scan_export(md))


# ── 空行折叠 ────────────────────────────────────────

def test_blank_run_reported():
    issues = scan_export("a\n\n\n\nb")
    assert "blank_run" in rules(issues)


def test_two_blank_lines_ok():
    assert "blank_run" not in rules(scan_export("a\n\nb"))


# ── 公式定界符 ──────────────────────────────────────

def test_math_unclosed_reported():
    issues = scan_export("公式 $x$ 和 $y 不闭合")
    assert "math_unclosed" in rules(issues)


def test_math_closed_ok():
    assert "math_unclosed" not in rules(scan_export("公式 $x$ 与 $y$"))


def test_math_in_html_table_skipped():
    md = "<table>\n<tr><td>$x 奇数</td></tr>\n</table>"
    assert "math_unclosed" not in rules(scan_export(md))


def test_block_math_double_dollar_ok():
    assert "math_unclosed" not in rules(scan_export("$$\n\\int f(x) dx\n$$"))


# ── 表格与标题/正文边界（A1 回归）───────────────────

def test_table_touch_heading_reported():
    issues = scan_export("</table>\n## 下一节")
    assert "table_touch" in rules(issues)


def test_table_touch_text_reported():
    issues = scan_export("<table>\n<tr><td>a</td></tr>\n</table>\n注：表格说明")
    assert "table_touch" in rules(issues)


def test_table_blank_line_separated_ok():
    md = "<table>\n<tr><td>a</td></tr>\n</table>\n\n## 下一节"
    assert "table_touch" not in rules(scan_export(md))


def test_blank_run_across_table_not_reported():
    """表格前 2 空行 + 表格内 + 表后 1 空行：空行计数跨界归零，不误报。"""
    md = "正文\n\n\n<table>\n<tr><td>a</td></tr>\n</table>\n\n附表说明"
    assert "blank_run" not in rules(scan_export(md))


# ── 图片引用完整性 ──────────────────────────────────

def test_missing_image_reported(tmp_path):
    issues = scan_export("![](images/missing.jpg)", img_dir=tmp_path)
    assert "missing_image" in rules(issues)


def test_existing_image_ok(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.jpg").write_bytes(b"x")
    issues = scan_export("![](images/a.jpg)", img_dir=tmp_path)
    assert "missing_image" not in rules(issues)


def test_img_tag_missing_image_reported(tmp_path):
    issues = scan_export("<img src='images/missing.jpg'>", img_dir=tmp_path)
    assert "missing_image" in rules(issues)


# ── 行列一致性 ──────────────────────────────────────

def test_md_table_ragged_reported():
    md = "| a | b |\n| --- | --- |\n| c |\n"
    assert "md_table_ragged" in rules(scan_export(md))


def test_md_table_consistent_ok():
    md = "| a | b |\n| --- | --- |\n| c | d |\n"
    assert "md_table_ragged" not in rules(scan_export(md))


def test_html_table_ragged_warning():
    md = ("<table>\n<tr><td>a</td><td>b</td></tr>\n"
          "<tr><td>c</td></tr>\n</table>")
    issues = scan_export(md)
    assert "html_table_ragged" in rules(issues)
    assert all(x["severity"] == "warning" for x in issues if x["rule"] == "html_table_ragged")


# ── 允许项不误报 ────────────────────────────────────

def test_html_table_entities_and_attrs_ok():
    """表格内允许保留的实体/属性不产生任何 issue（td 数须一致防误报）。"""
    md = (
        "<table>\n"
        "<tr><td colspan='2'>&amp;合并</td><td><eq>\\frac{a}{b}</eq></td><td>c</td></tr>\n"
        "<tr><td rowspan='2'>x</td><td>y</td><td>$a &lt; b$</td></tr>\n"
        "</table>\n\n正文"
    )
    assert scan_export(md) == []