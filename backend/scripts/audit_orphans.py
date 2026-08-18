"""B3 孤儿产物审计 CLI（2026-08-18）：DB vs 磁盘差异 + 孤儿图片（dry-run 优先）。

功能（全部从现有产物计算，只读 / 默认 dry-run）：
- DB 记录 vs 磁盘 build/md 目录差异（孤儿目录 = 删除教材残留/历史遗留）
- images/ 中未被任何 batch 引用的孤儿图（MinerU 重跑 hash 变化残留旧图）
- md 引用了但缺文件（= 缺图需重跑补图，**不是孤儿不删**，仅提示）

用法（backend/ 目录，DB 在 settings.db_path）：
    .venv\\Scripts\\python.exe scripts/audit_orphans.py              # 只读报告
    .venv\\Scripts\\python.exe scripts/audit_orphans.py --json       # 机器可读
    .venv\\Scripts\\python.exe scripts/audit_orphans.py --dry-run    # dry-run 列出将删孤儿图（默认）
    .venv\\Scripts\\python.exe scripts/audit_orphans.py --delete     # 实际删除孤儿图（先 dry-run 确认）

孤儿图片删除仅针对「未被任何 batch md 引用」的文件；目录级孤儿（build/md 无 DB 记录）
只报告不删除——删除教材请用 DELETE /api/books/{id} 接口。
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.audit_orphans import (
    scan_dir_diff,
    scan_orphan_images,
    dry_run_clean_orphan_images,
)


def _db_book_dirs() -> set[str]:
    """DB 中所有教材的 canonical 目录名（b<id>_<title>）。"""
    if not settings.db_path.exists():
        return set()
    conn = sqlite3.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT DISTINCT id, title FROM books").fetchall()
    finally:
        conn.close()
    return {f"b{bid}_{title}" for bid, title in rows}


def _books(settings) -> list[tuple[str, Path]]:
    """(canonical, md_dir) 列表：以磁盘 md 目录为准（DB 记录缺失的书也纳入扫孤儿图）。"""
    md_dir = settings.md_dir
    if not md_dir.exists():
        return []
    return [(d.name, d) for d in md_dir.iterdir() if d.is_dir()]


def main() -> int:
    ap = argparse.ArgumentParser(description="孤儿产物审计（B3）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="dry-run：列出将删孤儿图但不删（默认）")
    ap.add_argument("--delete", action="store_true", help="实际删除孤儿图（先 dry-run 确认）")
    args = ap.parse_args()
    if args.delete and args.dry_run:
        ap.error("--delete 与 --dry-run 互斥")
    mode = "dry-run" if not args.delete else "delete"

    db_dirs = _db_book_dirs()
    diff = scan_dir_diff(settings, db_dirs)
    books = _books(settings)

    orphans = scan_orphan_images(settings.md_dir, books)
    orphan_sizes = sum(p.stat().st_size for p in orphans if p.exists())

    if mode == "delete":
        removed = 0
        freed = 0
        for p in orphans:
            try:
                freed += p.stat().st_size
                p.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
        action_files = [str(p) for p in orphans]
        action_detail = f"已删 {removed} 个，释放 {freed // 1024} KB"
    else:
        action_files = [str(p) for p in orphans]
        action_detail = "dry-run：列出未删除"

    report = {
        "db_books": sorted(db_dirs),
        "orphan_build_dirs": [str(p) for p in diff["orphan_build"]],
        "orphan_md_dirs": [str(p) for p in diff["orphan_md"]],
        "missing_build_dirs": [str(p) for p in diff["missing_build"]],
        "missing_md_dirs": [str(p) for p in diff["missing_md"]],
        "orphan_images": {  # 仅用于报告计数，实际动作在 mode
            "count": len(orphans),
            "bytes": orphan_sizes,
            "files": [str(p) for p in orphans] if args.json else None,
        },
        "action": mode,
        "action_files": action_files,
        "action_detail": action_detail,
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("=== 孤儿产物审计（B3）===")
    print(f"DB 教材: {len(db_dirs)} 本")
    for k, label in (("orphan_build", "孤儿 build 目录"), ("orphan_md", "孤儿 md 目录"),
                     ("missing_build", "DB 记录但 build 缺失"), ("missing_md", "DB 记录但 md 缺失")):
        v = diff[k]
        print(f"  {label}: {len(v)}")
        for p in v[:10]:
            print(f"    - {p}")

    print(f"\n孤儿图片: {len(orphans)} 个, 共 {orphan_sizes // 1024} KB")
    if orphans:
        by_dir = Counter(str(p.parent) for p in orphans)
        for d, n in sorted(by_dir.items()):
            print(f"    {d}: {n}")
    print(f"\n动作: {mode}" + ("（列出，未删除）" if mode == "dry-run" else "（已删除）"))
    if mode == "delete":
        print(f"  已删 {len(orphan_bytes)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())