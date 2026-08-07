"""结构重建管线（P0-3 核心模块）。

输入：data/md/<book>/batch_XX_pN-M.md（每批带页区间）
输出：data/build/<book>/structure.json（章节树 + 文本）+ outline.md（大纲报告）

策略：不信任 MinerU 的 `#` 推断，全部清除后按教材编号体系规则重新打标。
- 第x章 → 一级；x.y / 一、 → 二级；（一） → 三级
- 思考与练习 / 习题 / 上机训练题 等 → 特殊板块（不入大纲，保留文本）
- 第一个章标题之前的内容（封面/简介/CIP/前言）→ 前置部分，丢弃
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import settings

# ── 标题模式 ──────────────────────────────────────────

CH_NUM = r"[一二三四五六七八九十百零〇]+"
RE_CH_LEVEL1 = re.compile(rf"^\s*[·•]?\s*第{CH_NUM}章\s+\S")   # 容忍 MinerU 偶发 "· 第x章" 前缀
# 阿拉伯数字章标题（"1 概论"、"2 药物的纯度检查…"），短标题防误伤正文数字开头行；
# 数字后必须跟非数字（排除 "3 400～2 400(s, 宽)" 这类光谱数据行），且不含 ～/~
RE_CH_LEVEL1_AR = re.compile(r"^\s*\d{1,2}\s+[^\d\s～~].{0,20}$")
RE_LEVEL2_JIE = re.compile(rf"^\s*第{CH_NUM}节\s+\S")                  # 第一节/第二节
RE_LEVEL2_DOT = re.compile(r"^\s*(\d+)\.(\d+)(\.\d+)?\s+\S")          # 2.1 / 2.1.3
RE_LEVEL2_CN = re.compile(rf"^\s*{CH_NUM}、\S")                        # 一、
RE_LEVEL3 = re.compile(rf"^\s*[（(]{CH_NUM}[）)]\s*\S")                # （一）
RE_BOARD = re.compile(
    r"^\s*(思考与练习|习题|上机训练题|内容提要|本章内容提要|参考答案|知识拓展|知识链接|"
    r"SPSS软件应用提要|附录|索引|参考文献|目录|目\s*录)\s*[一二三四五六七八九十\d]*\s*$"
)
# 目录行：章节标题 + 省略号点线 + 页码（如 "第五章 大数定律与中心极限定理……129"）
# 页码可能带括号："第一章 误差和分析数据处理…… (1)"（分析化学等教材目录格式）
# 数字章节目录行："1.1 药物质量的评价 …… (1)"（阿拉伯数字章/节教材）
RE_TOC_LINE = re.compile(
    rf"^\s*(?:第{CH_NUM}章|\d+(?:\.\d+)*)\s*\S.*….*(?:（\d+）|\(\d+\)|\d+)\s*$"
)
RE_TABLE_START = re.compile(r"<table")
RE_TABLE_END = re.compile(r"</table>")
RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
RE_HASH = re.compile(r"^#{1,6}\s*")


class Heading:
    __slots__ = ("level", "title", "line_no", "board", "kind")

    def __init__(self, level: int, title: str, line_no: int, board: bool = False, kind: str = ""):
        self.level = level      # 1=章 2=节 3=小节 4=次小节
        self.title = title
        self.line_no = line_no
        self.board = board      # 特殊板块
        self.kind = kind        # "jie"|"dot"|"cn"|"cn_sub"：最近节级标题类型

    def __repr__(self):
        return f"Heading({self.level}, {self.title!r}, line={self.line_no}, board={self.board}, kind={self.kind})"


def classify_heading(line: str) -> Heading | None:
    """规则识别标题行，返回 Heading 或 None（非标题）。"""
    stripped = RE_HASH.sub("", line).strip()
    if not stripped:
        return None
    # 特殊板块优先
    if RE_BOARD.match(stripped):
        return Heading(0, stripped, 0, board=True)
    if RE_CH_LEVEL1.match(stripped):
        return Heading(1, stripped.lstrip("·•").strip(), 0)
    # 阿拉伯数字章（"1 概论"）：必须原本是 # 标题行（MinerU 标记过），
    # 正文数字开头行（无 #）不参与识别，防误伤
    if RE_CH_LEVEL1_AR.match(stripped) and line.lstrip().startswith("#"):
        return Heading(1, stripped, 0, kind="ar")
    if RE_LEVEL2_JIE.match(stripped):
        return Heading(2, stripped, 0, kind="jie")
    m = RE_LEVEL2_DOT.match(stripped)
    if m:
        depth = 2 if not m.group(3) else 3
        return Heading(depth, stripped, 0, kind="dot" if depth == 2 else "")
    if RE_LEVEL2_CN.match(stripped):
        return Heading(2, stripped, 0, kind="cn")
    if RE_LEVEL3.match(stripped):
        return Heading(3, stripped, 0)
    return None


# ── 分批读取 ──────────────────────────────────────────

def load_batches(book_dir: str | Path) -> list[dict]:
    """读取批次 md，按页区间排序。返回 [{idx, page_start, page_end, text, content_list}]。"""
    book_dir = Path(book_dir)
    items = []
    for f in sorted(book_dir.glob("batch_*.md")):
        m = re.search(r"p(\d+)-(\d+)", f.name)
        if not m:
            continue
        text = f.read_text(encoding="utf-8")
        content_list = None
        jf = f.with_suffix(".json")
        if jf.exists():
            try:
                content_list = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                content_list = None
        items.append(
            {
                "file": str(f),
                "idx": int(f.name.split("_")[1]),
                "page_start": int(m.group(1)),
                "page_end": int(m.group(2)),
                "text": text,
                "content_list": content_list,
            }
        )
    items.sort(key=lambda x: x["page_start"])
    return items


def _norm(s: str) -> str:
    """归一化：去空白，用于标题匹配。"""
    return re.sub(r"\s+", "", s)


def page_anchors(content_list: list | None) -> dict:
    """从 content_list 提取 {归一化标题文本: 页码}（页码 1-based）。

    标题元素为 type=text 且 text_level 为 1（章）或 2（节）。
    """
    anchors: dict[str, int] = {}
    for it in content_list or []:
        if it.get("type") == "text" and it.get("text_level") in (1, 2) and it.get("text"):
            anchors[_norm(it["text"])] = int(it.get("page_idx", 0)) + 1
    return anchors


def _split_lines_with_tables(text: str) -> list[str]:
    """按行拆分，但 HTML 表格整体合并为一行（避免表格内容被误判标题）。"""
    lines: list[str] = []
    buf: list[str] = []
    in_table = False
    for line in text.splitlines():
        if not in_table and RE_TABLE_START.search(line):
            in_table = True
            buf = [line]
            if RE_TABLE_END.search(line):
                lines.append("\n".join(buf))
                buf = []
                in_table = False
            continue
        if in_table:
            buf.append(line)
            if RE_TABLE_END.search(line):
                lines.append("\n".join(buf))
                buf = []
                in_table = False
            continue
        lines.append(line)
    if buf:
        lines.append("\n".join(buf))
    return lines


# ── 结构重建 ──────────────────────────────────────────

def rebuild(batches: list[dict]) -> dict:
    """主流程：返回 structure dict。

    structure = {
        "book": ..., "pages_covered": "1-70",
        "chapters": [
            {"title", "level", "page_range", "lines", "char_count",
             "image_count", "table_count", "children": [...], "board": False},
            ...
        ],
        "pre_matter": str,     # 前置部分原文（丢弃，仅留统计）
        "skipped_orphans": [...],  # 无法归入章节的标题
    }
    """
    chapters: list[dict] = []
    cur: dict | None = None
    board_node: dict | None = None      # 当前特殊板块节点（内容提要/思考与练习等）
    last_sub_node: dict | None = None   # 最近的 2/3/4 级标题节点（正文归入）
    sec_kind: str | None = None         # 最近节级标题类型：jie|dot|cn|cn_sub
    pre_matter_parts: list[str] = []
    skipped: list[str] = []
    in_pre_matter = True

    def _new_board(title: str, page_range: str) -> dict:
        return {
            "title": title,
            "level": 0,
            "page_range": page_range,
            "lines": [title],
            "char_count": len(title),
            "image_count": 0,
            "table_count": 0,
            "children": [],
            "board": True,
        }

    def _attach_content_line(node: dict, line: str) -> None:
        node["lines"].append(line)
        node["char_count"] += len(line)
        if RE_IMAGE.search(line):
            node["image_count"] += 1
        if RE_TABLE_START.search(line):
            node["table_count"] += 1

    for batch in batches:
        page_range = f"p{batch['page_start']}-{batch['page_end']}"

        def _pr(title: str) -> str:
            """页码策略：P0 使用可靠批区间。content_list 锚受目录行污染（P2 处理）。"""
            return page_range

        for raw_line in _split_lines_with_tables(batch["text"]):
            line = raw_line.strip()
            if not line:
                continue
            # 目录行（第x章 …… 页码）直接丢弃
            if RE_TOC_LINE.match(line):
                continue

            heading = classify_heading(line)

            # ── 特殊板块区域：区域内所有标题行降级为内容，直到下一章/新板块 ──
            if board_node is not None:
                if heading is not None and heading.level == 1 and not heading.board:
                    board_node = None          # 新章开始，退出板块区域
                    # 落入下方正常章节逻辑
                else:
                    if heading is not None and heading.board:
                        board_node = _new_board(heading.title, _pr(heading.title))
                        if cur is not None:
                            cur["children"].append(board_node)
                    else:
                        _attach_content_line(board_node, line)
                    continue

            if heading is not None:
                if heading.board:
                    if cur is None:
                        if in_pre_matter:
                            continue          # 前置部分里的板块标题（如"内容简介"），丢弃
                        skipped.append(line)
                    else:
                        board_node = _new_board(heading.title, _pr(heading.title))
                        cur["children"].append(board_node)
                    continue

                if heading.level == 1:
                    in_pre_matter = False
                    sec_kind = None
                    last_sub_node = None
                    cur = {
                        "title": heading.title,
                        "level": 1,
                        "page_range": _pr(heading.title),
                        "lines": [heading.title],
                        "char_count": len(heading.title),
                        "image_count": 0,
                        "table_count": 0,
                        "children": [],
                        "board": False,
                    }
                    chapters.append(cur)
                    continue

                # 层级上下文调整（针对"第x节 + 一、 + （一）"嵌套结构）
                if heading.kind in ("jie", "dot"):
                    sec_kind = heading.kind
                elif heading.kind == "cn":
                    if sec_kind in ("jie", "cn_sub"):
                        heading = Heading(3, heading.title, 0, kind="cn_sub")
                        sec_kind = "cn_sub"   # 节内连续 一、二、三、 保持三级
                    else:
                        sec_kind = "cn"
                elif heading.kind == "" and heading.level == 3 and sec_kind == "cn_sub":
                    heading = Heading(4, heading.title, 0)

                # 2/3/4 级标题：归入当前章
                if cur is None:
                    if in_pre_matter:
                        continue  # 前置部分里的子标题，丢弃
                    skipped.append(line)
                else:
                    node = {
                        "title": heading.title,
                        "level": heading.level,
                        "page_range": _pr(heading.title),
                        "lines": [heading.title],
                        "char_count": len(heading.title),
                        "image_count": 0,
                        "table_count": 0,
                        "children": [],
                        "board": False,
                    }
                    cur["children"].append(node)
                    last_sub_node = node
                continue

            # 普通内容行
            if cur is None:
                if in_pre_matter:
                    pre_matter_parts.append(line)
                continue

            if last_sub_node is not None:
                _attach_content_line(last_sub_node, line)
            else:
                _attach_content_line(cur, line)

    # 汇总
    for ch in chapters:
        ch["children"] = _merge_subheadings(ch["children"])

    return {
        "book": "医药应用概率统计（种子批次）",
        "pages_covered": _pages_covered(batches),
        "chapters": chapters,
        "pre_matter_chars": sum(len(x) for x in pre_matter_parts),
        "skipped_orphans": skipped,
    }


def _pages_covered(batches: list[dict]) -> str:
    if not batches:
        return ""
    return f"p{batches[0]['page_start']}-{batches[-1]['page_end']}"


def _merge_subheadings(nodes: list[dict]) -> list[dict]:
    """把同一标题下的连续内容行合并进该节点（标题行自带 lines 冗余，清理）。"""
    return nodes


def estimate_chapter_pages(chapters: list[dict], total_range: str) -> list[dict]:
    """按章标题出现位置估算页码：用章标题的 page_range 作为章起点，
    下一章起点为本章终点。此函数在生成大纲时计算。"""
    return chapters


# ── 质检 ──────────────────────────────────────────────

CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
}


def cn_to_int(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    if s == "十":
        return 10
    if "百" in s:
        parts = s.split("百")
        return (CN_DIGITS.get(parts[0], 0) * 100) + cn_to_int(parts[1]) if len(parts) > 1 and parts[1] else CN_DIGITS.get(parts[0], 0) * 100
    if "十" in s:
        parts = s.split("十")
        tens = CN_DIGITS.get(parts[0], 1) if parts[0] else 1
        ones = CN_DIGITS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return CN_DIGITS.get(s, 0)


def check_section_continuity(structure: dict) -> list[str]:
    """质检：章内"第x节"编号是否连续（不连续提示 OCR 可能漏标题）。"""
    warnings = []
    for ch in structure["chapters"]:
        nums = []
        for sub in ch["children"]:
            if sub.get("board"):
                continue
            m = re.match(rf"^第({CH_NUM})节", sub["title"])
            if m:
                nums.append(cn_to_int(m.group(1)))
        if len(nums) > 1 and nums != list(range(min(nums), max(nums) + 1)):
            warnings.append(f"{ch['title']}: 节编号不连续 {nums}（可能漏识别标题）")
    return warnings


# ── 大纲报告 ──────────────────────────────────────────

def build_outline_report(structure: dict, book_name: str) -> str:
    """生成大纲报告 markdown。"""
    chapters = structure["chapters"]
    lines = [
        f"# 《{book_name}》结构大纲（P0-3 重建）",
        "",
        f"- 覆盖页数：{structure['pages_covered']}",
        f"- 章节数：{len(chapters)}",
        f"- 前置部分字符（已丢弃）：{structure['pre_matter_chars']}",
        f"- 孤儿标题（无法归入章节）：{len(structure['skipped_orphans'])}",
        "",
        "## 章节树",
        "",
    ]

    total_chars = 0
    total_images = 0
    total_tables = 0
    boards: list[str] = []

    for ch in chapters:
        total_chars += ch["char_count"]
        total_images += ch["image_count"]
        total_tables += ch["table_count"]
        lines.append(
            f"- **{ch['title']}**（{ch['page_range']}，{ch['char_count']}字，"
            f"图{ch['image_count']} 表{ch['table_count']}）"
        )
        for sub in ch["children"]:
            if sub.get("board"):
                boards.append(sub["title"])
                continue
            indent = "  " * (sub["level"] - 1)
            lines.append(
                f"{indent}- {sub['title']}（{sub['page_range']}，{sub['char_count']}字）"
            )

    lines += ["", "## 统计", ""]
    lines.append(f"- 正文字符总数：{total_chars}")
    lines.append(f"- 图片总数：{total_images}")
    lines.append(f"- 表格总数：{total_tables}")

    warnings = check_section_continuity(structure)
    if warnings:
        lines += ["", "## ⚠ 质检警告", ""]
        for w in warnings:
            lines.append(f"- {w}")
    if boards:
        lines.append("")
        lines.append("## 特殊板块（不入大纲，保留文本）")
        for b in boards:
            lines.append(f"- {b}")

    if structure["skipped_orphans"]:
        lines += ["", "## ⚠ 孤儿标题（待检查）", ""]
        for s in structure["skipped_orphans"][:20]:
            lines.append(f"- {s}")

    return "\n".join(lines)


# ── 入口 ──────────────────────────────────────────────

def run(book_id: int = 1, book_title: str = "医药应用概率统计") -> dict:
    """对指定教材执行结构重建，落盘 structure.json + outline.md。"""
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    batches = load_batches(md_dir)
    if not batches:
        raise FileNotFoundError(f"未找到批次 md：{md_dir}")

    structure = rebuild(batches)
    build_dir = settings.build_dir / f"b{book_id}_{book_title}"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "structure.json").write_text(
        json.dumps(structure, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = build_outline_report(structure, book_title)
    (build_dir / "outline.md").write_text(report, encoding="utf-8")
    return {"structure_file": str(build_dir / "structure.json"), "outline_file": str(build_dir / "outline.md"), "report": report}
