"""导出物专项回归扫描（A4，2026-08-18）。

对导出后的 Markdown 做静态规则扫描，输出机器可读的 issue 列表
（rule / severity / line / message），供：
- 单元测试覆盖规则边界（tests/test_verify_export.py）
- CLI 扫描真实教材导出物（scripts/verify_export.py）
- 后续 D2 vault 体检复用

核心原则：只报「导出链路应保证却违反」的问题；HTML 表格保留路径
（CLAUDE.md 约定 #1：表格内容零改动）内部的 <img>/<del>/实体/属性
一律不误报——表格外出现残影才报。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .exporter import IMG_RE, _img_rel

ERROR = "error"
WARNING = "warning"

# 未转义的 $（\$ 是文字美元，不参与定界符配对）
_MATH_DOLLAR_RE = re.compile(r"(?<!\\)\$")
_TD_RE = re.compile(r"<td\b")
_MD_TABLE_LINE_RE = re.compile(r"^\s*\|")


def scan_export(
    md_text: str,
    img_dir: str | Path | None = None,
) -> list[dict]:
    """扫描导出 markdown，返回 issue 列表。

    img_dir: 导出物同级 images/ 目录；缺省时 missing_image 规则跳过
    （无法判断文件是否存在）。
    """
    issues: list[dict] = []
    img_exists: Callable[[str], bool] | None = None
    if img_dir is not None:
        d = Path(img_dir)
        img_exists = lambda rel: (d / rel).exists()

    def _issue(rule: str, severity: str, line: int, message: str) -> None:
        issues.append(
            {"rule": rule, "severity": severity, "line": line, "message": message}
        )

    lines = md_text.split("\n")
    in_table = False
    prev_line = ""  # 上一行 strip 后内容（检测 </table> 后无空行紧贴）
    blank_run = 0   # 连续空行计数
    tr_cells: list[tuple[int, int]] = []  # HTML 表格内 (行号, 该 tr 行 td 数)
    md_block: list[tuple[int, str]] = []  # 连续 | 开头行 (行号, 原始行)

    def _flush_md_block() -> None:
        if len(md_block) < 3:
            return

        def col_count(line: str) -> int:
            # 先移除转义竖线 \|（渲染为 |，不是列分隔符）
            return len(line.replace(r"\|", "\x00").strip().strip("|").split("|"))

        counts = {col_count(l) for _, l in md_block}
        if len(counts) != 1:
            _issue(
                "md_table_ragged",
                ERROR,
                md_block[0][0],
                f"Markdown 表格块列数不一致: {sorted(counts)}",
            )

    for i, raw in enumerate(lines, 1):
        s = raw.strip()

        # ── HTML 表格块（约定 #1：内容零改动，整块跳过外部规则）────
        if s.startswith("<table"):
            in_table = True
            tr_cells = []
            blank_run = 0  # 表格是非空内容：空行计数跨表格块归零（防跨界误报）
        if in_table:
            if "<tr" in s:
                tr_cells.append((i, len(_TD_RE.findall(s))))
            if "</table>" in s:
                in_table = False
                # </table> 行也更新 prev_line：其后的正文/标题行才能被
                # table_touch 规则捕获（无空行紧贴 = HTML 块吞内容）
                prev_line = s
                if len({n for _, n in tr_cells}) > 1:
                    _issue(
                        "html_table_ragged",
                        WARNING,
                        tr_cells[0][0],
                        "HTML 表格各 tr 行 td 数不一致（保留表格仅提示，不自动改）",
                    )
            continue

        # ── 空行折叠 ──────────────────────────────
        if not s:
            blank_run += 1
            if blank_run == 3:
                _issue("blank_run", ERROR, i, "连续 3+ 空行（应被导出折叠）")
        else:
            blank_run = 0

        # ── </table> 后无空行紧贴正文/标题（A1 同类问题）────
        # 上一行以 </table> 结尾且当前行非空 → HTML 块延续吞内容
        if prev_line.startswith("</table") and s:
            _issue(
                "table_touch",
                ERROR,
                i,
                "</table> 后无空行紧贴内容，会被 HTML 块吞掉/渲染错位",
            )

        # ── 非预期残影标签 ─────────────────────────
        if re.search(r"<img\b", s, re.I):
            _issue("unexpected_img_tag", ERROR, i, "表格外残留 <img>（应归一化为 ![]()）")
        if re.search(r"</?del\b", s, re.I):
            _issue("unexpected_del_tag", ERROR, i, "表格外残留 <del>（应已删除）")

        # ── 公式定界符配对 ─────────────────────────
        if len(_MATH_DOLLAR_RE.findall(s)) % 2 == 1:
            _issue("math_unclosed", ERROR, i, "$ 定界符数量为奇数，公式未闭合")

        # ── 图片引用完整性 ─────────────────────────
        for m in IMG_RE.finditer(s):
            rel = _img_rel(m)
            if img_exists is not None and not img_exists(rel):
                _issue("missing_image", ERROR, i, f"图片引用但文件不存在: {rel}")

        # ── Markdown 表格块行列一致 ────────────────
        if _MD_TABLE_LINE_RE.match(s):
            md_block.append((i, s))
        else:
            _flush_md_block()
            md_block = []

        prev_line = s

    _flush_md_block()
    return issues