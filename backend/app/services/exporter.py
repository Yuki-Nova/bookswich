"""Markdown 导出服务：rebuilt（结构重建后）/ raw（MinerU 原始合并）。

v4 策略（用户决策）：
- **表格不做任何内容判断与转换**：MinerU 的 HTML 表格原样保留（<table> 语义/内容/属性
  零改动）。仅做纯排版换行（标签间插入换行符），避免 CodeMirror 超长单行导致
  Typora 内存爆炸——HTML 解析忽略换行，渲染结果与单行完全一致。
- **公式定界符规范化**：MinerU 输出的 `$ ... $` / `$$ ... $$` 内侧常带空格
  （如 `$ P ( X = k ) $`），Typora 不识别带空格的定界符 → 导出时去掉定界符
  内侧首尾空格（`$P(X=k)$`），公式内容本身零改动。

2026-08-16 借鉴 mineru-tianshu 的输出清洗：
- 正文深度清洗（HTML 实体反转义 / <del> 幻觉标签 / 空行折叠）——表格行除外
- <img> 标签图片引用归一化为 Markdown 语法，打包/统计链路 IMG_RE 兼容两种写法
"""
from __future__ import annotations

import html
import io
import json
import re
import zipfile
from pathlib import Path

from ..config import settings
from . import oss_images
from .structure import load_batches

MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
# 图片引用：兼容 Markdown 语法 ![](images/..) 与 HTML 标签 <img src="images/..">
# （2026-08-16 借鉴 mineru-tianshu 的输出规范化：MinerU 偶尔输出 <img> 形式，
#   导出前归一化为 Markdown 语法，打包/统计链路全部经 _img_rel 取路径）
IMG_RE = re.compile(
    r"!\[[^\]]*\]\((images/[^)\s]+)\)|"
    r"<img\s+[^>]*src=[\"'](images/[^\"']+)[\"'][^>]*>",
    re.I,
)


def _img_rel(m: re.Match) -> str:
    """从 IMG_RE 匹配结果取图片相对路径（两种语法共用）。"""
    return m.group(1) if m.group(1) is not None else m.group(2)


# 外部图片 URL（http/https）：归一化时跳过，不归入本地打包链路
_REMOTE_URL_RE = re.compile(r"https?://", re.I)
# <del> 幻觉标签（MinerU 模型偶尔在文本里输出）
_DEL_TAG_RE = re.compile(r"</?del>", re.I)


def clean_markdown(text: str) -> str:
    """深度清洗 MinerU 输出文本（借鉴 mineru-tianshu _clean_markdown 的安全子集）。

    - 双重 HTML 反转义（&amp;gt; → >）+ 暴力替换残留 &gt;/&lt;/&amp;
      （MinerU 输出正文里常带未解码实体，Typora/Obsidian 渲染成字面文本）
    - 删除 <del> 幻觉标签（内容保留）
    - 3+ 连续空行折叠为 1 个空行

    刻意不做（数学教材风险大于收益）：
    - 整段重复去重 (\\\\S+)(\\\\s+)\\\\1 —— 可能误伤公式内合法重复 token
    - ~ → 空格、\\\\mathrm{} 剥离 —— LaTeX 数学模式有语义
    - 表格内容绝不处理（CLAUDE.md 约定 #1，调用方保证不传入表格行）
    """
    if not text:
        return ""
    text = html.unescape(text)
    text = html.unescape(text)
    text = (
        text.replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )
    text = _DEL_TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def normalize_html_images(text: str) -> str:
    """把 <img src="images/xxx"> 归一化为 Markdown 图片语法。

    仅处理本地 images/ 相对引用；外部 URL（http/https）不动。
    归一化后 IMG_RE 打包/统计链路无需感知两种语法。
    """
    def _to_md(m: re.Match) -> str:
        src = m.group(2)  # group(1) 是引号，group(2) 才是 src 路径
        if _REMOTE_URL_RE.match(src):
            return m.group(0)
        return f"![]({src})"

    return re.sub(
        r'<img\b[^>]*?\bsrc=(["\'])(.*?)\1[^>]*>',
        _to_md,
        text,
        flags=re.I,
    )


def normalize_math(text: str) -> str:
    """规范化公式定界符（公式内容不变）。

    - 块级 `$$...$$`：保持 $$ 独占行的多行格式（Typora 标准块级公式）
    - 行内 `$ ... $`：去定界符内侧首尾空格（`$ P(X=k) $` → `$P(X=k)$`），
      Typora 不识别 `$` 后带空格的行内公式
    - `\\(` / `\\)`：MinerU 有时在公式里混入 LaTeX 定界符
      （如 `P(a\\( \\int...`），MathJax/KaTeX 在数学模式下不认 → 转普通括号
    交替分支单次替换：先匹配 $$ 块级，避免 $$ 的 $ 被行内规则二次配对。
    """
    def fix(m: re.Match) -> str:
        if m.group(1) is not None:
            return "$$\n" + m.group(1).strip() + "\n$$"
        return "$" + m.group(2).strip() + "$"

    text = MATH_RE.sub(fix, text)
    text = text.replace(r"\(", "(").replace(r"\)", ")")
    return text


def format_html_table(table_html: str) -> str:
    """HTML 表格纯排版换行：标签间插入换行符。

    不修改任何表格内容/属性/结构（HTML 解析忽略换行），仅消除超长单行。
    """
    return table_html.replace("><", ">\n<")


def format_table_md(table_html: str) -> str:
    """HTML table → Markdown table（表格内公式可渲染）。

    仅对通过 `_table_quality_gates` 的规整表格调用：
    1. `<eq>...</eq>` → `$...$`（html.unescape 解码 `&lt;`/`&gt;` 实体，
       否则 LaTeX 把 `&` 当列分隔符报 misplace &）
    2. 单元格竖线转义：公式内 `|` → `\vert `（LaTeX 数学模式语义正确），
       公式外 `|` → `\\|`（Markdown 转义）——否则条件概率 P(A|B) 切断表格列
    3. `<tr>/<td>` → `| cell | cell |` + `| --- |` 分隔行；
       单元格文本同时做 HTML 实体解码（补齐 <eq> 之外的 &gt;/&lt;/&amp; 残留）
    """
    import html as html_mod
    import re

    # 1. <eq>...</eq> → $...$（含 HTML 实体解码）
    def _eq_to_latex(m: re.Match) -> str:
        return f"${html_mod.unescape(m.group(1))}$"

    table_html = re.sub(r"<eq>(.*?)</eq>", _eq_to_latex, table_html, flags=re.S)

    # 2. 单元格竖线转义（公式内 \vert，公式外 \|）
    def _escape_pipes(text: str) -> str:
        parts = re.split(r"(\$[^$]*\$)", text)
        out: list[str] = []
        for part in parts:
            if part.startswith("$") and part.endswith("$") and len(part) > 2:
                # \vert 后带空格分隔控制序列名（\vertB 会解析失败）
                out.append(part.replace("|", r"\vert "))
            else:
                out.append(part.replace("|", r"\|"))
        return "".join(out)

    # 3. 行/单元格 → Markdown（单元格文本：实体解码 → 公式间双空格压平 →
    #    定界符净化 → 竖线转义）
    rows = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    md_rows: list[str] = []
    for row in rows:
        cells = [
            _escape_pipes(
                normalize_math(
                    re.sub(r"\$\s{2,}\$", "$ $", html_mod.unescape(c.strip().replace("\n", " ")))
                )
            )
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        ]
        if cells:
            md_rows.append("| " + " | ".join(cells) + " |")
    if len(md_rows) >= 2:
        ncols = md_rows[0].count("|") - 1
        md_rows.insert(1, "| " + " | ".join(["---"] * ncols) + " |")
    # 前后加空行：Markdown 表格需要空行与上下文分隔，
    # 否则相邻表格会被渲染器当成同一个表格（列数错乱）
    return "\n" + "\n".join(md_rows) + "\n"


# ── 表格质量门禁（2026-08-10 用户拍板：能转的必是规整表格）──────────

TABLE_GATE_MIN_COLS = 2        # 最小列数（1 列不是表格）
TABLE_GATE_MAX_COLS = 8        # 最大列数（防数据列表/超宽表）
TABLE_GATE_MIN_ROWS = 2        # 最小行数（单行不是表格）
TABLE_GATE_MAX_ROWS = 20       # 最大行数
TABLE_GATE_MAX_CELL_CHARS = 300  # 单格字符上限（防单格长文本爆炸）


def _table_quality_gates(table_html: str) -> tuple[bool, str]:
    """6 道质量门禁：全过才允许转 Markdown，否则保留 HTML。

    返回 (通过?, 原因)。原因用于统计/日志：
      unbalanced  - <table 与 </table> 不配对（防未闭合吞内容）
      merged      - 含 colspan/rowspan 合并单元格（Markdown 无合并语义）
      impure      - 表格结构外有游离文本（防正文长字符串混入）
      ragged      - 行 td 数不一致
      cols/rows   - 超出 2~8 列 / 2~20 行（数据列表、超宽表）
      cell_too_long - 单格超过 300 字符
    """
    import re

    # G1 闭合配对
    if table_html.count("<table") != table_html.count("</table>"):
        return False, "unbalanced"
    # G2 无合并单元格
    if re.search(r"colspan|rowspan", table_html, re.I):
        return False, "merged"
    # G3 结构纯净：挖掉 td 内容后无游离文本（正文混入检测）
    without_cells = re.sub(r"<td[^>]*>.*?</td>", "", table_html, flags=re.S)
    leftover = re.sub(r"<[^>]+>", "", without_cells).strip()
    if leftover:
        return False, "impure"
    # G4 行列规整
    rows = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    if not rows:
        return False, "empty"
    counts = {len(re.findall(r"<td", r)) for r in rows}
    if len(counts) != 1:
        return False, "ragged"
    # G5 尺寸
    ncols = list(counts)[0]
    if not (TABLE_GATE_MIN_COLS <= ncols <= TABLE_GATE_MAX_COLS):
        return False, f"cols={ncols}"
    if not (TABLE_GATE_MIN_ROWS <= len(rows) <= TABLE_GATE_MAX_ROWS):
        return False, f"rows={len(rows)}"
    # G6 单格长度
    for r in rows:
        for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S):
            if len(c) > TABLE_GATE_MAX_CELL_CHARS:
                return False, "cell_too_long"
    return True, "ok"


def _node_to_md(node: dict) -> str:
    """章节树节点 → markdown（表格原样保留 + 公式规范化 + 深度清洗）。"""
    parts: list[str] = []
    if node.get("board"):
        parts.append(f"\n## [板块] {node['title']}\n")
    else:
        level = max(1, int(node.get("level", 1)))
        parts.append(f"\n{'#' * min(level, 6)} {node['title']}\n")
    body = node.get("lines") or []
    if len(body) > 1:
        for line in body[1:]:
            stripped = line.strip()
            if stripped.startswith("<table"):
                # 表格：6 道质量门禁通过 → 转 Markdown（公式可渲染）；
                # 未通过 → 保留 HTML 原样（格式永远正确）
                # 表格内容不参与深度清洗（CLAUDE.md 约定 #1）
                ok, reason = _table_quality_gates(stripped)
                if ok:
                    parts.append(format_table_md(stripped))
                else:
                    formatted = format_html_table(stripped)
                    parts.append("\n".join(normalize_math(l) for l in formatted.splitlines()))
            else:
                # 非表格行：图片引用归一化 → 公式规范化 → 深度清洗
                parts.append(clean_markdown(normalize_math(normalize_html_images(line))))
    for sub in node.get("children") or []:
        parts.append(_node_to_md(sub))
    # 空行折叠放在节点级 join 后：clean_markdown 逐行调用无跨行上下文，
    # 行间 3+ 连续空行只能在这里统一压平
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts))


def export_rebuilt(book_id: int, book_title: str, chapter: int | None = None) -> str:
    """从 structure.json 生成结构重建后的完整 markdown。

    标题按层级打标（# 章 / ## 节 / ### 小节），前置部分已过滤，
    表格保留 MinerU 原样（纯排版换行），公式定界符规范化。
    chapter 指定时只导出第 N 章（从 1 开始）。
    """
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}（先执行解析与重建）")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])

    if chapter is not None:
        if chapter < 1 or chapter > len(chapters):
            raise ValueError(f"chapter 超出范围（1-{len(chapters)}）")
        chapters = [chapters[chapter - 1]]
        pages = chapters[0].get("page_range", "?")
        parts = [f"# 《{book_title}》 · 第{chapter}章", "", f"> 结构重建导出（{pages}）", ""]
    else:
        pages = structure.get("pages_covered", "?")
        parts = [f"# 《{book_title}》", "", f"> 由 bookswich 结构重建生成（覆盖 {pages}）", ""]

    for ch in chapters:
        parts.append(_node_to_md(ch))
    # 头部与首章拼接处可能产生 3+ 空行，统一折叠
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts))


def chapter_titles(book_id: int, book_title: str) -> list[str]:
    """返回章节标题列表（按结构重建产物）。"""
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    return [ch["title"] for ch in structure.get("chapters", [])]


def export_raw(book_id: int, book_title: str) -> str:
    """原始 MinerU 批次合并：按页序拼接，批次间加页码注释。"""
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    batches = load_batches(md_dir)
    if not batches:
        raise FileNotFoundError(f"未找到解析批次：{md_dir}")
    parts = [f"# 《{book_title}》（MinerU 原始输出）", ""]
    for b in batches:
        parts.append(f"\n<!-- batch {b['idx']}: p{b['page_start']}-{b['page_end']} -->\n")
        parts.append(b["text"])
    return "\n".join(parts)


def _sanitize_filename(name: str) -> str:
    """Windows 文件名安全化：去掉非法字符（<>:"/\\|?* 与首尾空白点）。"""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")


def _to_oss_links(
    md_text: str,
    uploader: oss_images.OssImageUploader,
    book_folder: str,
    src_md_dir: Path,
) -> str:
    """把 md 里的 images/ 相对引用上传 OSS 并替换为公网 URL。

    key 规则：<书名>/images/<name>（图片名是 MinerU hash，跨章天然唯一；
    整本与按章两种导出共用同一 key 空间，重复导出幂等跳过）。
    """
    seen: set[str] = set()
    items: list[tuple[str, Path]] = []
    rel_to_key: dict[str, str] = {}
    for m in IMG_RE.finditer(md_text):
        rel = _img_rel(m)
        if rel in seen:
            continue
        seen.add(rel)
        src = src_md_dir / rel
        if src.exists():
            key = f"{book_folder}/{rel}"
            items.append((key, src))
            rel_to_key[rel] = key
    mapping = uploader.upload_many(items)
    for rel, key in rel_to_key.items():
        md_text = md_text.replace(f"({rel})", f"({mapping[key]})")
    return md_text


def _merge_raw_batches(book_id: int, book_title: str) -> str:
    """合并全部批次原始 md（带批次页注释），用于无章节兜底导出。"""
    md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    batches = load_batches(md_dir)
    if not batches:
        raise FileNotFoundError(f"未找到解析批次：{md_dir}")
    parts: list[str] = []
    for b in batches:
        parts.append(f"\n<!-- batch {b['idx']}: p{b['page_start']}-{b['page_end']} -->\n")
        parts.append(b["text"])
    return "\n".join(parts)


def _fallback_full_chapter(book_id: int, book_title: str, pages_covered: str) -> dict:
    """无章节兜底章节：整本一个「全文」章节，正文 = 原始批次合并。"""
    full = _merge_raw_batches(book_id, book_title)
    return {
        "title": "全文",
        "level": 1,
        "page_range": pages_covered or "全本",
        "lines": ["全文"] + full.splitlines(),
        "char_count": len(full),
        "image_count": 0,
        "table_count": 0,
        "children": [],
        "board": False,
    }


def export_obsidian_zip(book_id: int, book_title: str, image_mode: str = "local") -> bytes:
    """Obsidian 版导出：按章拆分 + MOC 总览 + 各章独立 images/（或 OSS 外链）。

    zip 内部结构（性能友好：每章 30~80KB 秒开，图片按章分摊）：
        <书名>/
        ├── 00_总览.md            MOC：各章 [[链接]] 导航
        ├── 01_<章名>/<章名>.md + images/（local 模式：本章引用的图）
        ├── 02_<章名>/...
        └── ...

    无章节兜底（2026-08-11，论文/单篇资料等无章节教材）：structure.json 缺失或
    chapters 为空时整本合并为一个「全文」章节，不再报错拒绝导入。

    image_mode:
      - "local"（默认）：图片打包进 zip（旧行为，解压即 Obsidian/Typora 可读）
      - "oss"：图片上传 OSS，md 引用改公网 URL，zip 只含文本（vault 纯文本化）
    """
    if image_mode not in ("local", "oss"):
        raise ValueError("image_mode 必须是 local / oss")
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    chapters: list[dict] = []
    pages_covered = ""
    if structure_file.exists():
        structure = json.loads(structure_file.read_text(encoding="utf-8"))
        chapters = structure.get("chapters", [])
        pages_covered = structure.get("pages_covered", "")
    if not chapters:
        chapters = [_fallback_full_chapter(book_id, book_title, pages_covered)]

    src_md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    book_folder = _sanitize_filename(book_title)
    uploader = oss_images.OssImageUploader() if image_mode == "oss" else None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        toc = [f"# 《{book_title}》", "", f"> 由 bookswich 生成 · {len(chapters)} 章",
               "", "## 章节导航", ""]
        for i, ch in enumerate(chapters, 1):
            ch_title = ch["title"]
            folder = f"{i:02d}_{_sanitize_filename(ch_title)}"
            fname = f"{_sanitize_filename(ch_title)}.md"
            md_text = _node_to_md(ch)
            toc.append(f"- [[{folder}/{_sanitize_filename(ch_title)}|{ch_title}]]")
            if uploader is not None:
                md_text = _to_oss_links(md_text, uploader, book_folder, src_md_dir)
            zf.writestr(f"{book_folder}/{folder}/{fname}", md_text)
            # local 模式：打包该章引用的图片（保持相对路径 images/xxx.jpg 同级）
            if uploader is None:
                seen: set[str] = set()
                for m in IMG_RE.finditer(md_text):
                    rel = _img_rel(m)
                    if rel in seen:
                        continue
                    seen.add(rel)
                    src = src_md_dir / rel
                    if src.exists():
                        zf.writestr(f"{book_folder}/{folder}/{rel}", src.read_bytes())
        zf.writestr(f"{book_folder}/00_总览.md", "\n".join(toc))
    return buf.getvalue()


def export_zip(
    book_id: int,
    book_title: str,
    md_text: str,
    md_name: str,
    image_mode: str = "local",
) -> bytes:
    """把导出的 markdown 及其引用的图片打包成 zip（md + images/ 子目录）。

    markdown 里的图片引用是相对路径 images/xxx.jpg，图片文件源在
    data/md/b{book_id}_{book_title}/images/ 下；zip 内保持相同相对结构，
    解压后 md 与 images/ 同级，Obsidian / Typora 打开即可显示图片。
    只打包 md 实际引用到的图片，避免冗余体积。

    image_mode="oss"：图片上传 OSS，md 引用改公网 URL，zip 只含文本。
    """
    if image_mode not in ("local", "oss"):
        raise ValueError("image_mode 必须是 local / oss")
    # 防御性 sanitize：公共函数防调用方传入含路径分隔符的文件名（zip slip）
    md_name = _sanitize_filename(md_name) or "export.md"
    src_md_dir = settings.md_dir / f"b{book_id}_{book_title}"
    uploader = None
    if image_mode == "oss":
        uploader = oss_images.OssImageUploader()
        md_text = _to_oss_links(md_text, uploader, _sanitize_filename(book_title), src_md_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(md_name, md_text)
        if uploader is None:
            seen: set[str] = set()
            for m in IMG_RE.finditer(md_text):
                rel = _img_rel(m)
                if rel in seen:
                    continue
                seen.add(rel)
                src = src_md_dir / rel
                if src.exists():
                    zf.writestr(rel, src.read_bytes())
    return buf.getvalue()