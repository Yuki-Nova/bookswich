"""Markdown 导出服务：rebuilt（结构重建后）/ raw（MinerU 原始合并）。

v4 策略（用户决策）：
- **表格不做任何内容判断与转换**：MinerU 的 HTML 表格原样保留（<table> 语义/内容/属性
  零改动）。仅做纯排版换行（标签间插入换行符），避免 CodeMirror 超长单行导致
  Typora 内存爆炸——HTML 解析忽略换行，渲染结果与单行完全一致。
- **公式定界符规范化**：MinerU 输出的 `$ ... $` / `$$ ... $$` 内侧常带空格
  （如 `$ P ( X = k ) $`），Typora 不识别带空格的定界符 → 导出时去掉定界符
  内侧首尾空格（`$P(X=k)$`），公式内容本身零改动。
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
IMG_RE = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")


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

    MinerU 表格内公式用 `<eq>LaTeX</eq>` 标签，HTML `<table>` 里的定界符
    不被 Markdown 渲染器解析（Typora/Obsidian 均如此）。本函数：
    1. `<eq>...</eq>` → `$...$`（先 html.unescape 解码 `&lt;`/`&gt;` 等实体，
       否则 LaTeX 把 `&` 当列分隔符报 misplace &）
    2. `<tr>/<td>` → `| cell | cell |`，colspan=N 补 N-1 个空列、
       rowspan=M 后续 M-1 行对应列补空单元格（列对齐、内容不丢不错位）
    3. 插入 `| --- |` 分隔行

    注：Markdown 无合并单元格语义，展开后视觉上不再合并，但内容完整。
    """
    import html as html_mod
    import re

    # 1. <eq>...</eq> → $...$
    def _eq_to_latex(m: re.Match) -> str:
        return f"${html_mod.unescape(m.group(1))}$"

    table_html = re.sub(r"<eq>(.*?)</eq>", _eq_to_latex, table_html, flags=re.S)

    # 单元格内竖线转义（Markdown 表格列分隔符）：
    # 公式内 `|` → `\vert`（LaTeX 数学模式语义正确，渲染为 |）
    # 公式外 `|` → `\|`（Markdown 转义，渲染为 |）
    # 否则条件概率 P(A|B)、绝对值 |x̄| 会切断表格列（列错乱）
    def _escape_cell_pipes(text: str) -> str:
        parts = re.split(r"(\$[^$]*\$)", text)
        out: list[str] = []
        for part in parts:
            if part.startswith("$") and part.endswith("$") and len(part) > 2:
                # \vert 后带空格分隔控制序列名（\vertB 会解析失败）
                out.append(part.replace("|", r"\vert "))
            else:
                out.append(part.replace("|", r"\|"))
        return "".join(out)

    # 2. 解析行/单元格（含 colspan/rowspan 展开）
    rows = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    md_rows: list[str] = []
    pending: dict[int, int] = {}  # 列位 → 剩余 rowspan 行数
    for row in rows:
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
        out_cells: list[str] = []
        col = 0
        ci = 0
        while col < max(20, len(cells) * 4):  # 列位上限防死循环
            # rowspan 延续：该列还有合并占用 → 补空
            if pending.get(col, 0) > 0:
                out_cells.append("")
                pending[col] = pending[col] - 1
                if pending[col] == 0:
                    pending.pop(col, None)
                col += 1
                continue
            if ci >= len(cells):
                break
            attrs, content = cells[ci]
            ci += 1
            content = _escape_cell_pipes(content.strip().replace("\n", " "))
            colspan = 1
            m = re.search(r"colspan\s*=\s*[\"']?(\d+)", attrs)
            if m:
                colspan = int(m.group(1))
            rowspan = 1
            m = re.search(r"rowspan\s*=\s*[\"']?(\d+)", attrs)
            if m:
                rowspan = int(m.group(1))
            out_cells.append(content)
            for _ in range(max(1, colspan) - 1):
                out_cells.append("")
            if rowspan > 1:
                pending[col] = rowspan - 1
            col += max(1, colspan)
            if col >= 60:  # 防御异常大 colspan
                break
        # 末尾补齐与首行对齐（rowspan 结尾空列不丢）
        while len(out_cells) < len(md_rows[0].split("|")) - 2 if md_rows else False:
            out_cells.append("")
        if out_cells:
            md_rows.append("| " + " | ".join(out_cells) + " |")

    # 3. 分隔行（按第一行列数）
    if len(md_rows) >= 2:
        ncols = md_rows[0].count("|") - 1
        md_rows.insert(1, "| " + " | ".join(["---"] * ncols) + " |")
    return "\n".join(md_rows)


def _node_to_md(node: dict) -> str:
    """章节树节点 → markdown（表格原样保留 + 公式规范化）。"""
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
                # 表格：保持 MinerU HTML 原样（用户决策 2026-08-09）：
                # Markdown 表格转换在真实正文中列错乱（colspan/rowspan 展开 +
                # 复杂公式 + 多分布并表），HTML 表格格式永远正确；
                # 表格内公式（<eq>）不渲染是渲染器限制，接受。
                # 仅拆行（避免超长单行），逐行规范化公式（正文公式）
                formatted = format_html_table(stripped)
                parts.append("\n".join(normalize_math(l) for l in formatted.splitlines()))
            else:
                parts.append(normalize_math(line))
    for sub in node.get("children") or []:
        parts.append(_node_to_md(sub))
    return "\n".join(parts)


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
    return "\n".join(parts)


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
        rel = m.group(1)
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


def export_obsidian_zip(book_id: int, book_title: str, image_mode: str = "local") -> bytes:
    """Obsidian 版导出：按章拆分 + MOC 总览 + 各章独立 images/（或 OSS 外链）。

    zip 内部结构（性能友好：每章 30~80KB 秒开，图片按章分摊）：
        <书名>/
        ├── 00_总览.md            MOC：各章 [[链接]] 导航
        ├── 01_<章名>/<章名>.md + images/（local 模式：本章引用的图）
        ├── 02_<章名>/...
        └── ...

    image_mode:
      - "local"（默认）：图片打包进 zip（旧行为，解压即 Obsidian/Typora 可读）
      - "oss"：图片上传 OSS，md 引用改公网 URL，zip 只含文本（vault 纯文本化）
    """
    if image_mode not in ("local", "oss"):
        raise ValueError("image_mode 必须是 local / oss")
    structure_file = settings.build_dir / f"b{book_id}_{book_title}" / "structure.json"
    if not structure_file.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{structure_file}")
    structure = json.loads(structure_file.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])
    if not chapters:
        raise ValueError("结构重建产物无章节，无法生成 Obsidian 版")

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
                    rel = m.group(1)
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
                rel = m.group(1)
                if rel in seen:
                    continue
                seen.add(rel)
                src = src_md_dir / rel
                if src.exists():
                    zf.writestr(rel, src.read_bytes())
    return buf.getvalue()
