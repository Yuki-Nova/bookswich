"""解析质检与对比服务（2026-08-11）：/api/books/{id}/compare 数据源。

第一步（质检报告）：结构统计 / 表格门禁原因分布 / 图片缺失清单 / 质检警告，
全部从现有产物（structure.json + 批次 md）计算，零新存储。

第二步（按章对比）：raw（MinerU 原始）vs rebuilt（结构重建后）行级 diff，
Python difflib 生成，前端只渲染（eq 块合并为计数，del/add 逐行）。
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

from ..config import settings
from .exporter import (
    IMG_RE,
    TABLE_GATE_MAX_CELL_CHARS,
    _img_rel,
    _table_quality_gates,
    export_rebuilt,
)
from .structure import check_section_continuity, load_batches

RE_PAGE_RANGE = re.compile(r"p(\d+)-(\d+)")

# A2 疑似公式特征（2026-08-18）：成对 $ 定界符 / <eq> 标签 / LaTeX 反斜杠命令
_RE_MATH_DOLLAR = re.compile(r"(?<!\\)\$")
_RE_MATH_LATEX_CMD = re.compile(r"\\[a-zA-Z]{2,}")


def _is_math_table(table_html: str) -> bool:
    """疑似公式表判定（保守：任一特征命中即计入，不把疑似当确定公式）。

    - `<eq>` 标签（本地 MinerU 管道形态，云 API 为防御性 no-op）
    - 成对 `$...$`（2+ 个未转义 $；单个 $ 如书名号/货币不算）
    - LaTeX 反斜杠命令（\\frac / \\sum / \\overline 等）
    """
    if "<eq>" in table_html.lower():
        return True
    if len(_RE_MATH_DOLLAR.findall(table_html)) >= 2:
        return True
    return bool(_RE_MATH_LATEX_CMD.search(table_html))


def _iter_nodes(chapters: list[dict]):
    """深度遍历章节树节点（章 + 其 children，含特殊板块）。"""
    for ch in chapters:
        yield ch
        for sub in ch.get("children", []):
            yield from _iter_nodes([sub])


def _max_cell_len(table_html: str) -> int:
    """td 单元格内容最大长度（与门禁 G6 同口径）。"""
    return max(
        (
            len(c)
            for r in re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
            for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        ),
        default=0,
    )


def _table_stats(lines: list[str]) -> dict:
    """统计节点 lines 中的表格：转换数 / 保留数 / 门禁原因分布 + 公式维度（A2）。

    math 子对象记录疑似公式表的面貌：
      total/converted/kept      - 疑似公式表总数及去向
      kept_reasons              - 被门禁拦截的公式表白名单外原因分布
      kept_merged               - 其中含 rowspan/colspan（Markdown 无合并语义，不可转）
      kept_cell_too_long        - 其中单格超长（G6 拦截）
    """
    converted = kept = 0
    reasons: dict[str, int] = {}
    math = {
        "total": 0,
        "converted": 0,
        "kept": 0,
        "kept_reasons": {},
        "kept_merged": 0,
        "kept_cell_too_long": 0,
    }
    for line in lines:
        s = line.strip()
        if not s.startswith("<table"):
            continue
        ok, reason = _table_quality_gates(s)
        is_math = _is_math_table(s)
        if is_math:
            math["total"] += 1
        if ok:
            converted += 1
            if is_math:
                math["converted"] += 1
        else:
            kept += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            if is_math:
                math["kept"] += 1
                math["kept_reasons"][reason] = math["kept_reasons"].get(reason, 0) + 1
                lower = s.lower()
                if "rowspan" in lower or "colspan" in lower:
                    math["kept_merged"] += 1
                if _max_cell_len(s) > TABLE_GATE_MAX_CELL_CHARS:
                    math["kept_cell_too_long"] += 1
    return {
        "converted": converted,
        "kept": kept,
        "reasons": reasons,
        "math": math,
    }


def _image_stats(lines: list[str], md_dir: Path) -> dict:
    """统计 lines 中的图片引用与缺失文件（缺的给出相对路径清单）。"""
    referenced = 0
    missing: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for m in IMG_RE.finditer(line):
            referenced += 1
            rel = _img_rel(m)
            if rel in seen:
                continue
            seen.add(rel)
            if not (md_dir / rel).exists():
                missing.append(rel)
    return {"referenced": referenced, "missing": missing}


def build_compare_report(book_id: int, book_title: str) -> dict:
    """生成解析质检报告。structure.json 缺失时抛 FileNotFoundError。"""
    build_dir = settings.build_dir / f"b{book_id}_{book_title}"
    structure_file = build_dir / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])

    md_dir = settings.md_dir / f"b{book_id}_{book_title}"

    ch_rows: list[dict] = []
    tables_total = {
        "converted": 0,
        "kept": 0,
        "reasons": {},
        "math": {
            "total": 0,
            "converted": 0,
            "kept": 0,
            "kept_reasons": {},
            "kept_merged": 0,
            "kept_cell_too_long": 0,
        },
    }
    images_total = {"referenced": 0, "missing": []}
    rebuilt_chars = 0
    for i, ch in enumerate(chapters, 1):
        nodes = list(_iter_nodes([ch]))
        lines: list[str] = []
        ch_chars = 0
        for n in nodes:
            lines.extend(n.get("lines") or [])
            ch_chars += int(n.get("char_count", 0))
        ts = _table_stats(lines)
        im = _image_stats(lines, md_dir)
        rebuilt_chars += ch_chars

        tables_total["converted"] += ts["converted"]
        tables_total["kept"] += ts["kept"]
        for k, v in ts["reasons"].items():
            tables_total["reasons"][k] = tables_total["reasons"].get(k, 0) + v
        m_total, m = tables_total["math"], ts["math"]
        for k in ("total", "converted", "kept", "kept_merged", "kept_cell_too_long"):
            m_total[k] += m[k]
        for k, v in m["kept_reasons"].items():
            m_total["kept_reasons"][k] = m_total["kept_reasons"].get(k, 0) + v
        images_total["referenced"] += im["referenced"]
        for rel in im["missing"]:
            if rel not in images_total["missing"]:
                images_total["missing"].append(rel)

        ch_rows.append(
            {
                "no": i,
                "title": ch.get("title", ""),
                "page_range": ch.get("page_range", ""),
                "char_count": ch_chars,   # 章 + 子节合计
                "image_count": sum(int(n.get("image_count", 0)) for n in nodes),
                "tables": ts,
            }
        )

    # raw 体积（全部批次合并）
    raw_chars = sum(len(b["text"]) for b in load_batches(md_dir))

    return {
        "book": book_title,
        "pages_covered": structure.get("pages_covered", ""),
        "chapter_count": len(chapters),
        "chapters": ch_rows,
        "tables": tables_total,
        "images": images_total,
        "warnings": check_section_continuity(structure),
        "orphans": structure.get("skipped_orphans", []),
        "pre_matter_chars": int(structure.get("pre_matter_chars", 0)),
        "raw_chars": raw_chars,
        "rebuilt_chars": rebuilt_chars,
    }


def _chapter_raw_text(book_id: int, book_title: str, page_range: str) -> str:
    """按章的批区间取 raw 对照文本（粗对齐：章的 page_range 是批级区间）。

    取与章页区间相交的批次合并，作为 rebuilt 的原始对照。
    """
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    m = RE_PAGE_RANGE.match(page_range or "")
    if not m:
        return ""
    lo, hi = int(m.group(1)), int(m.group(2))
    parts: list[str] = []
    for b in load_batches(md_dir):
        if b["page_start"] <= hi and b["page_end"] >= lo:
            parts.append(b["text"])
    return "\n".join(parts)


def build_chapter_diff(book_id: int, book_title: str, chapter_no: int) -> dict:
    """按章 raw vs rebuilt 行级 diff。

    返回 {chapter, title, page_range, raw_lines, rebuilt_lines, diff}；
    diff 元素：{t:"eq", n}（连续相同行合并计数）/ {t:"del", a} / {t:"add", b}。
    """
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])
    if chapter_no < 1 or chapter_no > len(chapters):
        raise ValueError(f"chapter 超出范围（1-{len(chapters)}）")
    ch = chapters[chapter_no - 1]

    rebuilt = export_rebuilt(book_id, book_title, chapter=chapter_no)
    raw = _chapter_raw_text(book_id, book_title, ch.get("page_range", ""))

    a = raw.splitlines()
    b = rebuilt.splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diff: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            diff.append({"t": "eq", "n": i2 - i1})
        elif tag == "delete":
            for i in range(i1, i2):
                diff.append({"t": "del", "a": a[i]})
        elif tag == "insert":
            for j in range(j1, j2):
                diff.append({"t": "add", "b": b[j]})
        elif tag == "replace":
            for i in range(i1, i2):
                diff.append({"t": "del", "a": a[i]})
            for j in range(j1, j2):
                diff.append({"t": "add", "b": b[j]})

    return {
        "book": book_title,
        "chapter": chapter_no,
        "title": ch.get("title", ""),
        "page_range": ch.get("page_range", ""),
        "raw_lines": len(a),
        "rebuilt_lines": len(b),
        "diff": diff,
    }


def _chapter_raw_text_v2(book_id: int, book_title: str, ch: dict, chapters: list[dict], chapter_no: int) -> str:
    """P0-4 按章 raw 对照：用下一章起始页切边界，减少相邻章内容混入。

    仍是批次级切分（批为 25 页粒度），但边界取 [本章起始页, 下一章起始页)。
    """
    page_range = ch.get("page_range", "")
    m = RE_PAGE_RANGE.match(page_range or "")
    if not m:
        return ""
    lo = int(m.group(1))
    next_lo = None
    if chapter_no < len(chapters):
        m2 = RE_PAGE_RANGE.match(chapters[chapter_no].get("page_range", ""))
        if m2:
            next_lo = int(m2.group(1))
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    parts: list[str] = []
    for b in load_batches(md_dir):
        if b["page_end"] < lo:
            continue
        if next_lo is not None and b["page_start"] >= next_lo:
            continue
        parts.append(b["text"])
    return "\n".join(parts)


def _diff_lines(a: list[str], b: list[str]) -> list[dict]:
    """P0-4 行级 diff：先哈希切掉共同前后缀，只对变化区域跑 SequenceMatcher。"""
    import hashlib

    def _hashes(lines: list[str]) -> list[str]:
        return [hashlib.md5(l.encode("utf-8")).hexdigest() for l in lines]

    ha, hb = _hashes(a), _hashes(b)
    pre = 0
    while pre < min(len(ha), len(hb)) and ha[pre] == hb[pre]:
        pre += 1
    suf = 0
    while suf < min(len(ha) - pre, len(hb) - pre) and ha[len(ha) - 1 - suf] == hb[len(hb) - 1 - suf]:
        suf += 1

    diff: list[dict] = []
    if pre:
        diff.append({"t": "eq", "n": pre})
    mid_a = a[pre:len(a) - suf] if suf else a[pre:]
    mid_b = b[pre:len(b) - suf] if suf else b[pre:]
    sm = difflib.SequenceMatcher(a=mid_a, b=mid_b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            if i2 - i1 > 0:
                diff.append({"t": "eq", "n": i2 - i1})
        elif tag == "delete":
            for i in range(i1, i2):
                diff.append({"t": "del", "a": mid_a[i]})
        elif tag == "insert":
            for j in range(j1, j2):
                diff.append({"t": "add", "b": mid_b[j]})
        elif tag == "replace":
            for i in range(i1, i2):
                diff.append({"t": "del", "a": mid_a[i]})
            for j in range(j1, j2):
                diff.append({"t": "add", "b": mid_b[j]})
    if suf:
        diff.append({"t": "eq", "n": suf})
    return diff


def _diff_cache_path(book_id: int, book_title: str, chapter_no: int) -> Path:
    return settings.build_dir / f"b{book_id}_{book_title}" / f"chapter_diff_{chapter_no}.json"


def build_chapter_diff_v2(book_id: int, book_title: str, chapter_no: int) -> dict:
    """P0-4 按章 raw vs rebuilt 行级 diff（v2：精切边界 + 哈希加速 + 落盘缓存）。

    返回 {chapter, title, page_range, raw_lines, rebuilt_lines, diff}；
    diff 元素：{t:"eq", n}（连续相同行合并计数）/ {t:"del", a} / {t:"add", b}。
    """
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])
    if chapter_no < 1 or chapter_no > len(chapters):
        raise ValueError(f"chapter 超出范围（1-{len(chapters)}）")
    ch = chapters[chapter_no - 1]

    rebuilt = export_rebuilt(book_id, book_title, chapter=chapter_no)
    raw = _chapter_raw_text_v2(book_id, book_title, ch, chapters, chapter_no)
    a = raw.splitlines()
    b = rebuilt.splitlines()

    cache_path = _diff_cache_path(book_id, book_title, chapter_no)
    structure_mtime = int(structure_file.stat().st_mtime)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                cached.get("structure_mtime") == structure_mtime
                and cached.get("raw_lines") == len(a)
                and cached.get("rebuilt_lines") == len(b)
            ):
                diff = cached.get("diff", [])
                return {
                    "book": book_title,
                    "chapter": chapter_no,
                    "title": ch.get("title", ""),
                    "page_range": ch.get("page_range", ""),
                    "raw_lines": len(a),
                    "rebuilt_lines": len(b),
                    "diff": diff,
                    "cached": True,
                }
        except Exception:
            pass

    diff = _diff_lines(a, b)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "structure_mtime": structure_mtime,
                    "raw_lines": len(a),
                    "rebuilt_lines": len(b),
                    "diff": diff,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass

    return {
        "book": book_title,
        "chapter": chapter_no,
        "title": ch.get("title", ""),
        "page_range": ch.get("page_range", ""),
        "raw_lines": len(a),
        "rebuilt_lines": len(b),
        "diff": diff,
        "cached": False,
    }


def chapter_markdown(book_id: int, book_title: str, chapter_no: int) -> dict:
    """按章 rebuilt markdown 原文（并排预览右栏数据源）。

    返回 {chapter, title, page_range, markdown}；markdown 为 export_rebuilt
    单章产物（标题按层级打标，表格/公式保持导出口径）。
    """
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])
    if chapter_no < 1 or chapter_no > len(chapters):
        raise ValueError(f"chapter 超出范围（1-{len(chapters)}）")
    ch = chapters[chapter_no - 1]
    md = export_rebuilt(book_id, book_title, chapter=chapter_no)
    return {
        "book": book_title,
        "chapter": chapter_no,
        "title": ch.get("title", ""),
        "page_range": ch.get("page_range", ""),
        "markdown": md,
    }
