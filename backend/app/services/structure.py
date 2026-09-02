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

CN_NUM = r"[一二三四五六七八九十百零〇]+"
# 支持阿拉伯数字（第1章/第 3 章）+ 容忍数字与章字间空格
CN_OR_AR = r"(?:[一二三四五六七八九十百零〇]+|\d{1,3})"
RE_CH_LEVEL1 = re.compile(rf"^\s*[·•]?\s*第\s*{CN_OR_AR}\s*章\s+\S")
# 阿拉伯数字章标题（"1 概论"、"2 药物的纯度检查…"），短标题防误伤正文数字开头行；
# 数字后必须跟非数字（排除 "3 400～2 400(s, 宽)" 这类光谱数据行），且不含 ～/~
RE_CH_LEVEL1_AR = re.compile(r"^\s*\d{1,2}\s+[^\d\s～~].{0,20}$")
RE_LEVEL2_JIE = re.compile(rf"^\s*第\s*{CN_OR_AR}\s*节\s+\S")          # 第一节/第1节/第 2 节
RE_LEVEL2_DOT = re.compile(r"^\s*(\d+)\.(\d+)(\.\d+)?\s+\S")          # 2.1 / 2.1.3
RE_LEVEL2_CN = re.compile(rf"^\s*{CN_NUM}、\S")                       # 一、
RE_LEVEL3 = re.compile(rf"^\s*[（(]\s*{CN_OR_AR}\s*[）)]\s*\S")        # （一）/ (1) / （ 2 ）
RE_BOARD = re.compile(
    r"^\s*(思考与练习|习题|习题解答|上机训练题|内容提要|本章内容提要|参考答案|知识拓展|知识链接|"
    r"SPSS软件应用提要|附录|索引|参考文献|目录|目\s*录)\s*[一二三四五六七八九十\d]*\s*$"
)
# 目录行：章节编号 + 标题 + 页码（如 "第五章 大数定律与中心极限定理……129"）。
# P0-1 放宽：点线可有可无（MinerU OCR 对点线识别不稳），因此正则不再要求 `…`。
# 页码可能带括号："第一章 误差和分析数据处理…… (1)"（分析化学等教材目录格式）
# 数字章节目录行："1.1 药物质量的评价 …… (1)"（阿拉伯数字章/节教材）
RE_TOC_LINE = re.compile(
    rf"^\s*(?:第\s*{CN_OR_AR}\s*章|\d+(?:\.\d+)*)\s*\S.*(?:（\d+）|\(\d+\)|\d+)\s*$"
)
RE_TABLE_START = re.compile(r"<table")
RE_TABLE_END = re.compile(r"</table>")
RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
RE_HASH = re.compile(r"^#{1,6}\s*")

# 目录页码结尾（全角/半角括号页码或裸数字）
RE_TOC_PAGE_TAIL = re.compile(r"(?:[（(]\s*\d+\s*[）)]|\d+)\s*$")


def _is_toc_line(line: str) -> bool:
    """判断一行是否目录行。

    放宽版（2026-08-15，P0-1）：旧 RE_TOC_LINE 要求点线 `…`，MinerU OCR 对点线
    识别极不稳定（`.`/空格/缺失），导致目录行漏拦后被当章/节标题切进正文。

    新判据：
      1. 行首是章/节编号（第x章 / x.y / x.y.z）
      2. 行尾是页码（（1）/(1)/1）
      3. 标题短、不含图片/表格
    点线可有可无；旧 RE_TOC_LINE 命中仍直接认目录行（兼容）。
    """
    s = line.strip()
    if not s:
        return False
    if RE_TOC_LINE.match(s):
        return True
    if not re.match(rf"^(?:第\s*{CN_OR_AR}\s*章|\d+(?:\.\d+)*)\s*\S", s):
        return False
    if not RE_TOC_PAGE_TAIL.search(s):
        return False
    body = RE_TOC_PAGE_TAIL.sub("", s)
    if len(body) > 60:
        return False
    if RE_IMAGE.search(body) or RE_TABLE_START.search(body):
        return False
    return True


def _strip_toc_page_no(line: str) -> str:
    """去目录行尾部页码与点线，返回标题部分。"""
    body = RE_TOC_PAGE_TAIL.sub("", line.strip())
    body = re.sub(r"[….]{2,}\s*$", "", body).strip()
    return body


def _extract_toc_title(line: str) -> str | None:
    """从目录行提取章节标题文本（去编号、去页码）。"""
    body = _strip_toc_page_no(line)
    if not body:
        return None
    m = re.match(rf"^第\s*{CN_OR_AR}\s*章\s+(.+)$", body)
    if m:
        return m.group(1).strip()
    m = re.match(r"^\d+(?:\.\d+)*\s+(.+)$", body)
    if m:
        return m.group(1).strip()
    return None


def _toc_line_ratios(batches: list[dict]) -> dict[int, float]:
    """返回每批目录行占比 {batch_idx: ratio}，用于目录页整页降权。"""
    ratios: dict[int, float] = {}
    for batch in batches:
        lines = _split_lines_with_tables(batch["text"])
        if not lines:
            ratios[int(batch["idx"])] = 0.0
            continue
        toc_n = sum(1 for l in lines if _is_toc_line(l.strip()))
        ratios[int(batch["idx"])] = toc_n / len(lines)
    return ratios


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

def _norm_title(t: str) -> str:
    """标题归一化：去公式定界符/空格，统一破折号与全角符号，用于目录 vs 正文标题匹配。"""
    t = re.sub(r"[$\\]", "", t)          # 去 $ 和反斜杠（LaTeX 公式）
    t = t.replace(" ", "").replace("\u3000", "")
    t = t.replace("—", "-").replace("－", "-").replace("—", "-")
    t = t.replace("：", ":").replace("；", ";").replace("，", ",")
    t = t.replace("（", "(").replace("）", ")").replace("“", '"').replace("”", '"')
    return t


def _norm_title_relaxed(t: str) -> str:
    """标题宽松归一化（2026-09-02）：_norm_title 基础上把中文「一」归一为 -。

    用于 board 区域内 ar 章标题的重复检测——书末习题解答区按章分组的标题
    与入库章标题存在 OCR 变体（「紫外—可见」→「紫外一可见」），精确比对
    会漏网产生伪章（回归 b16 药物分析化学）。
    """
    return _norm_title(t).replace("一", "-")


def _extract_toc_titles(batches: list[dict]) -> set[str]:
    """从目录页提取章节标题集合（去编号、去页码），用于 hash 兜底过滤。

    目录行格式：'第十二章 宏观经济的基本指标及其衡量 …… 363'
    提取出的标题如 '宏观经济的基本指标及其衡量'。找不到目录页时返回空集。
    """
    titles: set[str] = set()
    in_toc = False
    for batch in batches:
        for raw_line in _split_lines_with_tables(batch["text"]):
            line = raw_line.strip()
            if not line:
                continue
            # 进入目录区：'## 目录' 或 '目 录'
            if not in_toc and (line == "目录" or line == "目 录" or line.lstrip("#").strip() == "目录"):
                in_toc = True
                continue
            if not in_toc:
                continue
            m = re.match(rf"^第\s*{CN_OR_AR}\s*章\s+(.+?)\s*[…….]+\s*(?:（?\d+）?)?\s*$", line)
            if m:
                t = m.group(1).strip()
                # 去掉尾部多余标点/页码残留
                t = re.sub(r"\s*[.…]\s*$", "", t).strip()
                if t:
                    titles.add(_norm_title(t))
    return titles


def _extract_toc_titles_v2(batches: list[dict]) -> set[str]:
    """P0-1 目录标题提取 v2：基于 _is_toc_line 放宽版目录行判断。

    不再依赖 '目录' 标题行进入目录区，也不要求点线；只要求
    「章/节编号开头 + 页码结尾 + 标题短」。旧版对 OCR 点线识别
    不稳定导致目录标题白名单为空，进而 hash 兜底失效。
    """
    titles: set[str] = set()
    for batch in batches:
        for raw_line in _split_lines_with_tables(batch["text"]):
            line = raw_line.strip()
            if not line or not _is_toc_line(line):
                continue
            t = _extract_toc_title(line)
            if t:
                titles.add(_norm_title(t))
    return titles


def extract_toc_entries(batches: list[dict]) -> list[dict]:
    """P0-5 从目录页提取章节条目 [{no, title, page|None}]。

    目录区域判据：出现 「目录/目 录」 锚点行之后连续的无 # 「第x章」行；
    遇到带 # 的章标题（正文开始）即停止。页码 OCR 常丢失（容忍 None，
    有则记录用于章节页码锚定）。目录提取失败返回 []（调用方回退原逻辑）。
    """
    entries: list[dict] = []
    in_toc = False
    for batch in batches:
        for raw_line in _split_lines_with_tables(batch["text"]):
            s = raw_line.strip()
            if not s:
                continue
            if not in_toc:
                if s in ("目录", "目 录", "目　录") or s.lstrip("#").strip() == "目录":
                    in_toc = True
                continue
            # 正文首章（带 # 的 第x章）→ 目录区域结束，不再收集
            if s.lstrip().startswith("#") and re.match(
                rf"^#+\s*第\s*{CN_OR_AR}\s*章", s.lstrip()
            ):
                return entries
            m = re.match(rf"^第\s*({CN_OR_AR})\s*[章篇]\s*(.*)$", s)
            if not m:
                continue
            no = cn_to_int(m.group(1))
            rest = m.group(2).strip()
            page = None
            pm = re.search(r"(?:[（(]?\s*(\d+)\s*[）)]?|\.{2,}\s*(\d+))\s*$", rest)
            if pm:
                page = int(pm.group(1) or pm.group(2))
                rest = rest[: pm.start()].strip()
            rest = re.sub(r"[….·\-—\s]+$", "", rest).strip()
            if rest:
                entries.append({"no": no, "title": rest, "page": page})
    return entries


def _detect_chapter_style(batches: list[dict]) -> tuple[str, set[str]]:
    """判断章标题风格：'numbered'（第x章）/ 'hash'（MinerU # 标题，无编号教材）。

    统计全书 '第x章' 标题数与 '#' 标题数：编号标题 >0 用编号规则；
    编号为 0 且 # 标题 >=3 时回退用 # 标题兜底（如《西方经济学 宏观部分》正文章标题无编号）。
    返回 (风格, 目录页章节标题集合) —— hash 风格时用集合过滤伪章标题。
    """
    numbered = 0
    hashed = 0
    for batch in batches:
        for raw_line in _split_lines_with_tables(batch["text"]):
            line = raw_line.strip()
            if RE_TOC_LINE.match(line):
                continue
            stripped = RE_HASH.sub("", line).strip()
            if not stripped:
                continue
            if RE_CH_LEVEL1.match(stripped):
                numbered += 1
            elif line.lstrip().startswith("#") and RE_BOARD.match(stripped) is None:
                hashed += 1
    toc = _extract_toc_titles_v2(batches)
    if numbered > 0:
        return "numbered", toc
    if hashed >= 3:
        return "hash", toc
    return "numbered", toc



def _heading_in_toc(title: str, toc_titles: set[str]) -> bool:
    """判断标题是否命中目录白名单（去编号后归一化匹配）。"""
    if not toc_titles:
        return False
    if _norm_title(title) in toc_titles:
        return True
    body = re.sub(rf"^第\s*{CN_OR_AR}\s*[章节]\s*", "", title)
    body = re.sub(r"^\d+(?:\.\d+)*\s*", "", body)
    body = re.sub(rf"^{CN_NUM}、\s*", "", body)
    body = re.sub(rf"^[（(]\s*{CN_OR_AR}\s*[）)]\s*", "", body)
    return _norm_title(body) in toc_titles


def _should_accept_heading(heading: Heading | None, line: str, toc_titles: set[str]) -> bool:
    """P0-2 评分制二次过滤：对 classify_heading 结果做收紧。

    章级：第x章 / 第x节格式本身可信，直接接受；hash 兜底章必须命中目录白名单。
    一、（kind=cn）与（一）（level 3 括号标题）必须有行首 # 或目录白名单命中，
    否则视为正文编号行，不参与结构树。
    """
    if heading is None or heading.board:
        return True
    has_hash = line.lstrip().startswith("#")
    if heading.level == 1:
        if heading.kind == "hash":
            return _heading_in_toc(heading.title, toc_titles)
        return True
    if heading.kind in ("jie", "dot"):
        return True
    if heading.kind == "cn":
        return has_hash or _heading_in_toc(heading.title, toc_titles)
    if heading.kind == "" and heading.level == 3 and RE_LEVEL3.match(heading.title):
        return has_hash or _heading_in_toc(heading.title, toc_titles)
    return True


def rebuild_v2(batches: list[dict], book_title: str = "") -> dict:
    """P0-2 真树化重建：嵌套 children + 标题评分制 + 目录页整页降权。

    与 v1 的差异：
      1. 对 `一、` / `（一）` 标题做二次过滤（行首 # 或目录白名单）；
      2. 用标题栈构建真正的嵌套树（节 → 小节 → 次小节）；
      3. 层级跳变自动补锚并记 warning；
      4. 目录页批次（目录行占比 >50%）整批跳过（P0-1）。
    """
    chapters: list[dict] = []
    chapter_titles_seen: set[str] = set()  # 已入库章标题（宽松归一化），board 区域重复 ar 章降级用
    cur: dict | None = None
    stack: list[dict] = []              # 当前路径节点，stack[-1] 为正文归属叶子
    board_node: dict | None = None
    sec_kind: str | None = None
    pre_matter_parts: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []
    in_pre_matter = True
    style, toc_titles = _detect_chapter_style(batches)
    toc_ratios = _toc_line_ratios(batches)
    # P0-5 目录驱动：numbered 风格且目录可用（>=3 条目）时启用白名单+顺序锚定
    toc_entries = extract_toc_entries(batches)
    toc_active = style == "numbered" and len(toc_entries) >= 3
    toc_ptr = 0
    in_toc_region = False

    def _toc_match(title: str) -> tuple[bool, int | None]:
        """目录白名单 + 顺序匹配，返回 (是否命中, 目录页码或 None)。

        命中但无页码（OCR 丢页码）返回 (True, None)——必须与「未命中」区分，
        否则页码缺失的目录条目会把真章误判为伪章。
        顺序推进（toc_ptr）：允许跳号（某章 OCR 漏识别），但乱序/重复/白名单外
        的「第x章」一律拒绝——正文引用的法规条文、目录残渣都过不了这关。
        """
        nonlocal toc_ptr
        m = re.match(rf"^第\s*({CN_OR_AR})\s*章\s*(.*)$", title)
        if not m:
            return False, None
        no = cn_to_int(m.group(1))
        body = _norm_title(m.group(2).strip())
        for k in range(toc_ptr, len(toc_entries)):
            e = toc_entries[k]
            if e["no"] == no and body and _norm_title(e["title"]) == body:
                toc_ptr = k + 1
                return True, e.get("page")
        return False, None

    def _new_node(title: str, level: int, page_range: str, board: bool = False) -> dict:
        return {
            "title": title,
            "level": level,
            "page_range": page_range,
            "lines": [title],
            "char_count": len(title),
            "image_count": 0,
            "table_count": 0,
            "children": [],
            "board": board,
        }

    def _attach_content(node: dict, line: str) -> None:
        node["lines"].append(line)
        node["char_count"] += len(line)
        if RE_IMAGE.search(line):
            node["image_count"] += 1
        if RE_TABLE_START.search(line):
            node["table_count"] += 1

    def _attach_sub_node(ch: dict, node: dict) -> None:
        """把子标题挂到最近的低层级节点，返回时 stack 指向新叶子。"""
        nonlocal warnings
        parent = ch
        while stack:
            last = stack[-1]
            if int(last.get("level", 1)) < int(node["level"]):
                parent = last
                break
            stack.pop()
        if int(node["level"]) - int(parent.get("level", 1)) > 1:
            warnings.append(
                f"{node['title']}: 层级跳变（{parent.get('level')} -> {node['level']}）"
            )
        parent.setdefault("children", []).append(node)
        stack.append(node)

    for batch in batches:
        # P0-1：目录页整页降权
        if toc_ratios.get(batch["idx"], 0.0) > 0.5:
            continue
        page_range = f"p{batch['page_start']}-{batch['page_end']}"

        for raw_line in _split_lines_with_tables(batch["text"]):
            line = raw_line.strip()
            if not line:
                continue
            if _is_toc_line(line):
                continue
            # P0-5 目录区域：目录锚点后到正文首章的目录行整段跳过
            # （目录行页码被 OCR 丢失时 _is_toc_line 失效，靠区域定位兜底；
            #   仅 numbered 风格启用，hash 风格回退原逻辑）
            if toc_active:
                if not in_toc_region:
                    if line in ("目录", "目 录", "目　录") or line.lstrip("#").strip() == "目录":
                        in_toc_region = True
                        continue
                else:
                    stripped_r = RE_HASH.sub("", line).strip()
                    if line.lstrip().startswith("#") and (
                        RE_CH_LEVEL1.match(stripped_r) or RE_CH_LEVEL1_AR.match(stripped_r)
                    ):
                        in_toc_region = False  # 正文首章：退出目录区域，正常处理本行
                    else:
                        continue

            heading = classify_heading(line)

            # hash 兜底：无编号教材的 MinerU # 一级标题当章标题
            if heading is None and style == "hash":
                stripped = RE_HASH.sub("", line).strip()
                if (
                    line.lstrip().startswith("#")
                    and stripped
                    and RE_BOARD.match(stripped) is None
                    and not _is_toc_line(line)
                    and not RE_CH_LEVEL1_AR.match(stripped)
                    and not RE_LEVEL2_JIE.match(stripped)
                    and toc_titles
                    and _norm_title(stripped) in toc_titles
                ):
                    heading = Heading(1, stripped.lstrip("#").strip(), 0, kind="hash")

            # hash 风格统一过滤：章标题必须在目录白名单内
            # （kind="ar" 阿拉伯数字章豁免：toc_titles 是去编号标题，带编号
            #   直接比对必失败会误杀真章——回归 b16 药物分析化学，2026-09-02）
            if (
                style == "hash"
                and heading is not None
                and heading.level == 1
                and toc_titles
                and heading.kind != "ar"
            ):
                h_title = _norm_title(heading.title.lstrip("·•").strip())
                if h_title not in toc_titles:
                    heading = None

            # 特殊板块区域：区域内标题行降级为内容，直到新章
            # （2026-09-02：ar 数字章标题若已是入库章——书末习题解答区按章
            #   分组的重复标题——不退出区域而是降级；首次出现的 ar 真章仍退出
            #   ——回归 b16 药物分析化学 batch_18 习题解答区）
            if board_node is not None:
                if (
                    heading is not None
                    and heading.level == 1
                    and not heading.board
                    and (
                        heading.kind != "ar"
                        or _norm_title_relaxed(heading.title) not in chapter_titles_seen
                    )
                ):
                    board_node = None
                else:
                    if heading is not None and heading.board:
                        board_node = _new_node(heading.title, 0, page_range, board=True)
                        if cur is not None:
                            cur["children"].append(board_node)
                            stack = [cur, board_node]
                    else:
                        _attach_content(board_node, line)
                    continue

            if heading is not None:
                if heading.board:
                    if cur is None:
                        if in_pre_matter:
                            continue
                        skipped.append(line)
                    else:
                        board_node = _new_node(heading.title, 0, page_range, board=True)
                        cur["children"].append(board_node)
                        stack = [cur, board_node]
                    continue

                # P0-2 评分制过滤：不达标的候选标题当正文处理
                if not _should_accept_heading(heading, line, toc_titles):
                    heading = None
                else:
                    # 层级上下文调整（第x节 + 一、 → 一、降为 3 级）
                    if heading.kind in ("jie", "dot"):
                        sec_kind = heading.kind
                    elif heading.kind == "cn":
                        if sec_kind in ("jie", "cn_sub"):
                            heading = Heading(3, heading.title, 0, kind="cn_sub")
                            sec_kind = "cn_sub"
                        else:
                            sec_kind = "cn"
                    elif heading.kind == "" and heading.level == 3 and sec_kind == "cn_sub":
                        heading = Heading(4, heading.title, 0)

                    if heading.level == 1:
                        toc_ok, toc_page = (
                            _toc_match(heading.title) if toc_active else (True, None)
                        )
                        if toc_active and not toc_ok:
                            # 目录漏录补锚：正文真「第x章」标题（MinerU 标记过、标题长度合理、
                            # 章号序进、非「条文引用」形态）→ 补锚入库。
                            # 回归：b17 民法学目录 OCR 把「第二章 人格权法」识别成
                            # 「第二节 人格权法」→ 白名单缺章 → 真章被当伪章吞掉（2026-09-02）。
                            # 防误伤：伪章（正文引用的法规条文）常带引号或「共 N 条」，
                            # 且章号不序进（如 第一章 总则 出现在第一章真章之后），三层条件拦截。
                            # 注：补锚成功后 toc_ok=True，须与正常命中共用下方入库代码——
                            # 不能用 if/else 结构（分支内改 toc_ok 无法让控制流回跳 else）。
                            m_ch = re.match(rf"^第\s*({CN_OR_AR})\s*章\s*(.*)$", heading.title)
                            if m_ch:
                                _body = m_ch.group(2).strip()
                                _prev_no = 0
                                for _c in chapters:
                                    _cm = re.match(rf"^第\s*({CN_OR_AR})\s*章", _c["title"])
                                    if _cm:
                                        _prev_no = max(_prev_no, cn_to_int(_cm.group(1)))
                                if (
                                    line.lstrip().startswith("#")
                                    and 2 <= len(_body) <= 30
                                    and cn_to_int(m_ch.group(1)) > _prev_no
                                    and not re.search(r'[“”"]', _body)
                                    and not re.search(r"共\s*\d+\s*条", _body)
                                ):
                                    toc_ok = True
                                    toc_page = None
                                    warnings.append(f"目录漏录，正文补锚：{heading.title}")
                            if not toc_ok:
                                # 伪章（正文引用的条文、目录残渣）：标题行降级为内容
                                if cur is not None:
                                    _attach_content(stack[-1] if stack else cur, line)
                                elif not in_pre_matter:
                                    skipped.append(line)
                                continue
                        in_pre_matter = False
                        sec_kind = None
                        pr = f"p{toc_page}" if toc_page else page_range
                        cur = _new_node(heading.title, 1, pr)
                        chapters.append(cur)
                        chapter_titles_seen.add(_norm_title_relaxed(heading.title))
                        stack = [cur]
                        continue
                    else:
                        if cur is None:
                            if in_pre_matter:
                                continue
                            skipped.append(line)
                        else:
                            node = _new_node(heading.title, heading.level, page_range)
                            _attach_sub_node(cur, node)
                    continue

            # 普通内容行
            if cur is None:
                if in_pre_matter:
                    pre_matter_parts.append(line)
                continue
            if board_node is not None and stack and stack[-1].get("board"):
                _attach_content(stack[-1], line)
            elif stack:
                _attach_content(stack[-1], line)
            else:
                _attach_content(cur, line)

    return {
        "book": book_title,
        "pages_covered": _pages_covered(batches),
        "chapters": chapters,
        "pre_matter_chars": sum(len(x) for x in pre_matter_parts),
        "skipped_orphans": skipped,
        "warnings": warnings,
    }

def rebuild(batches: list[dict], book_title: str = "") -> dict:
    """主流程：返回 structure dict。

    book_title 仅作元数据记录（如「医药应用概率统计」），导出时书名以参数为准。
    
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
    style, toc_titles = _detect_chapter_style(batches)
    toc_ratios = _toc_line_ratios(batches)

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
        # P0-1：目录页整页降权（目录行占比 >50% 的批次只参与目录提取，不参与标题识别）
        if toc_ratios.get(batch["idx"], 0.0) > 0.5:
            continue
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

            # ── 兜底：无编号教材（第x章识别数=0），MinerU # 一级标题当章标题 ──
            if heading is None and style == "hash":
                stripped = RE_HASH.sub("", line).strip()
                if (
                    line.lstrip().startswith("#")
                    and stripped
                    and RE_BOARD.match(stripped) is None
                    and not RE_TOC_LINE.match(line)
                    and not RE_CH_LEVEL1_AR.match(stripped)
                    and not RE_LEVEL2_JIE.match(stripped)
                    # 目录页清单过滤：只有目录里出现过的标题才当章（防封面/序言/小节误判）
                    and toc_titles
                    and _norm_title(stripped) in toc_titles
                ):
                    heading = Heading(1, stripped.lstrip("#").strip(), 0, kind="hash")

            # ── hash 风格统一过滤：阿拉伯数字章（如 "21 世纪经济学系列教材"）也在 toc 清单内才当章 ──
            if style == "hash" and heading is not None and heading.level == 1 and toc_titles:
                h_title = _norm_title(heading.title.lstrip("·•").strip())
                if h_title not in toc_titles:
                    heading = None  # 非目录页列出的标题（封面丛书名/孤立编号行）不当章

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
    return {
        "book": book_title,
        "pages_covered": _pages_covered(batches),
        "chapters": chapters,
        "pre_matter_chars": sum(len(x) for x in pre_matter_parts),
        "skipped_orphans": skipped,
    }


def _pages_covered(batches: list[dict]) -> str:
    if not batches:
        return ""
    return f"p{batches[0]['page_start']}-{batches[-1]['page_end']}"


# ── 质检 ──────────────────────────────────────────────

CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
}


def cn_to_int(s: str) -> int:
    s = s.strip()
    if not s:
        return 0
    # 阿拉伯数字直接转
    if s.isdigit():
        return int(s)
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
            m = re.match(rf"^第\s*({CN_OR_AR})\s*节", sub["title"])
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


def build_outline_report_v2(structure: dict, book_name: str) -> str:
    """P0-2 大纲报告 v2：递归渲染嵌套章节树 + 合并层级跳变警告。"""
    chapters = structure["chapters"]
    lines = [
        f"# 《{book_name}》结构大纲（P0-2 真树化重建）",
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

    def walk(nodes: list[dict], depth: int) -> None:
        nonlocal total_chars, total_images, total_tables
        for n in nodes:
            if n.get("board"):
                boards.append(n["title"])
                continue
            total_chars += int(n.get("char_count", 0))
            total_images += int(n.get("image_count", 0))
            total_tables += int(n.get("table_count", 0))
            if depth == 0:
                lines.append(
                    f"- **{n['title']}**（{n.get('page_range', '')}，"
                    f"{n.get('char_count', 0)}字，图{n.get('image_count', 0)} "
                    f"表{n.get('table_count', 0)}）"
                )
            else:
                indent = "  " * depth
                lines.append(
                    f"{indent}- {n['title']}（{n.get('page_range', '')}，"
                    f"{n.get('char_count', 0)}字）"
                )
            walk(n.get("children") or [], depth + 1)

    walk(chapters, 0)

    lines += ["", "## 统计", ""]
    lines.append(f"- 正文字符总数：{total_chars}")
    lines.append(f"- 图片总数：{total_images}")
    lines.append(f"- 表格总数：{total_tables}")

    warnings = list(structure.get("warnings", []))
    warnings += check_section_continuity(structure)
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

def run(book_id: int, book_title: str) -> dict:
    """对指定教材执行结构重建，落盘 structure.json + outline.md。"""
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    batches = load_batches(md_dir)
    if not batches:
        raise FileNotFoundError(f"未找到批次 md：{md_dir}")

    structure = rebuild_v2(batches, book_title=book_title)
    build_dir = settings.build_dir / f"b{book_id}_{book_title}"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "structure.json").write_text(
        json.dumps(structure, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = build_outline_report_v2(structure, book_title)
    (build_dir / "outline.md").write_text(report, encoding="utf-8")
    return {"structure_file": str(build_dir / "structure.json"), "outline_file": str(build_dir / "outline.md"), "report": report}
