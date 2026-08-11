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
from .exporter import IMG_RE, _table_quality_gates, export_rebuilt
from .structure import check_section_continuity, load_batches

RE_PAGE_RANGE = re.compile(r"p(\d+)-(\d+)")


def _iter_nodes(chapters: list[dict]):
    """深度遍历章节树节点（章 + 其 children，含特殊板块）。"""
    for ch in chapters:
        yield ch
        yield from ch.get("children", [])


def _table_stats(lines: list[str]) -> dict:
    """统计节点 lines 中的表格：转换数 / 保留数 / 门禁原因分布。"""
    converted = kept = 0
    reasons: dict[str, int] = {}
    for line in lines:
        s = line.strip()
        if not s.startswith("<table"):
            continue
        ok, reason = _table_quality_gates(s)
        if ok:
            converted += 1
        else:
            kept += 1
            reasons[reason] = reasons.get(reason, 0) + 1
    return {"converted": converted, "kept": kept, "reasons": reasons}


def _image_stats(lines: list[str], md_dir: Path) -> dict:
    """统计 lines 中的图片引用与缺失文件（缺的给出相对路径清单）。"""
    referenced = 0
    missing: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for m in IMG_RE.finditer(line):
            referenced += 1
            rel = m.group(1)
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
    tables_total = {"converted": 0, "kept": 0, "reasons": {}}
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
                "image_count": int(ch.get("image_count", 0)),
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
