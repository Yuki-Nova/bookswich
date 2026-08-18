"""B3: 文件生命周期 & 孤儿产物只读审计逻辑（2026-08-18）。

纯函数判定，不做实际删除；删除入口在 scripts/audit_orphans.py（dry-run 优先）。

- scan_dir_diff：DB 记录 vs 磁盘 build/md 目录差异
    orphan_*    —— 磁盘存在但 DB 无记录（删除教材后残留/历史遗留）
    missing_*   —— DB 有记录但磁盘目录缺失（记录完整性损坏，可感知）
- scan_orphan_images：images/ 中未被任何 batch md 引用的文件（MinerU 重跑残留旧 hash）
    —— 只删明确孤儿；md 引用了但 images/ 缺文件 = 缺图（需重跑补图，**不删**）
- dry_run_clean_orphan_images：dry-run 列出但不删除

跨批共享 images/，判定必须以「该 md 目录下所有 batch 的引用」为准（not 整个仓库）。
"""
from __future__ import annotations

import re
from pathlib import Path

_IMG_REF_RE = re.compile(r"images/([A-Za-z0-9._-]+\.(?:jpg|jpeg|png|gif|webp))", re.I)


def scan_dir_diff(settings, db_dirs: set[str]) -> dict:
    """扫描磁盘 build/md 目录与 DB 记录差异（只读）。db_dirs = {b<id>_<title>, ...}。

    孤儿：磁盘存在但 DB 无记录（删除教材后残留/历史遗留）。
    缺失：DB 有记录但磁盘目录缺失（记录完整性损坏，可感知）。
    书目录规范化：用 `b<id>_` 前缀匹配（DB 记录与磁盘目录同构），
    忽略本地特有的 `_b<n>` 后缀差异。
    """
    build_dir, md_dir = settings.build_dir, settings.md_dir
    result = {"orphan_build": [], "orphan_md": [], "missing_build": [], "missing_md": []}

    def _prefix(name: str) -> str | None:
        # "b1_医药应用概率统计" → "b1"；"b1_x_b2" → None（本地唯一后缀 _b<n>）
        m = re.match(r"^(b\d+)_", name)
        return m.group(1) if m else None

    def _scan(dirname: Path, key_orphan: str) -> None:
        if not dirname.exists():
            return
        for d in sorted(dirname.iterdir()):
            if not d.is_dir():
                continue
            p = _prefix(d.name)
            if p is None:
                continue
            if any(p == _prefix(x) for x in db_dirs if _prefix(x)):
                continue
            result[key_orphan].append(d)

    _scan(build_dir, "orphan_build")
    _scan(md_dir, "orphan_md")

    for canonical in db_dirs:
        p = _prefix(canonical)
        if p is None or not any(_prefix(x) == p for x in db_dirs):
            continue
        if not (build_dir / canonical).exists():
            result["missing_build"].append(build_dir / canonical)
        if not (md_dir / canonical).exists():
            result["missing_md"].append(md_dir / canonical)
    return result


def _referenced_images(md_dir: Path) -> set[str]:
    """该 md 目录下所有 batch md 引用的图片文件名集合。"""
    refs: set[str] = set()
    if not md_dir.exists():
        return refs
    for f in md_dir.glob("batch_*.md"):
        refs.update(_IMG_REF_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    return refs


def scan_orphan_images(md_root: Path, books: list[tuple[str, Path]]) -> list[Path]:
    """返回各教材 images/ 中未被引用的孤儿图片文件（相对完整路径）。"""
    orphans: list[Path] = []
    for _canonical, md_dir in books:
        img_dir = md_dir / "images"
        if not img_dir.is_dir():
            continue
        refs = _referenced_images(md_dir)
        for f in sorted(img_dir.iterdir()):
            if f.is_file() and f.name not in refs:
                orphans.append(f)
    return orphans


def dry_run_clean_orphan_images(md_root: Path, books: list[tuple[str, Path]]) -> list[str]:
    """dry-run：扫描并返回将删除的孤儿图片绝对路径，但**不删除**。"""
    return [str(p) for p in scan_orphan_images(md_root, books)]
