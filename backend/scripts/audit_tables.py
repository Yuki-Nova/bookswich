"""表格公式分布审计脚本（A2，2026-08-18）。

只读扫描 structure.json（结构重建产物），统计：
- 总表数 / 门禁转换数 / 保留数 / 各失败原因
- 疑似公式表总量及去向（转 MD / 保留 HTML）
- 被门禁拦截的公式表：原因分布、含合并单元格数、含超长单元格数
- 相关比例（不把疑似当确定公式，只作决策输入）

用法（backend/ 目录）：
    .venv\\Scripts\\python.exe scripts/audit_tables.py                    # 全部有 build 的教材
    .venv\\Scripts\\python.exe scripts/audit_tables.py --json             # 机器可读 JSON
    .venv\\Scripts\\python.exe scripts/audit_tables.py 1 医药应用概率统计  # 单本

不改动原始数据和导出物；structure.json 缺失时报错并退出 2。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.compare import _iter_nodes, _table_stats

RE_BUILD_DIR = re.compile(r"^b(\d+)_(.+)$")


def audit_book(book_id: int, book_title: str) -> dict:
    """单本教材表格分布报告（只读）。"""
    build_dir = settings.build_dir / f"b{book_id}_{book_title}"
    sf = build_dir / "structure.json"
    if not sf.exists():
        raise FileNotFoundError(f"结构重建产物缺失：{sf}")
    structure = json.loads(sf.read_text(encoding="utf-8"))
    chapters = structure.get("chapters", [])

    nodes = [n for ch in chapters for n in _iter_nodes([ch])]
    lines = [ln for n in nodes for ln in (n.get("lines") or [])]
    stats = _table_stats(lines)
    total = stats["converted"] + stats["kept"]
    m = stats["math"]
    return {
        "book_id": book_id,
        "book": book_title,
        "pages_covered": structure.get("pages_covered", ""),
        "chapter_count": len(chapters),
        "tables_total": total,
        "tables": {k: stats[k] for k in ("converted", "kept", "reasons")},
        "math": m,
        "math_ratio": round(m["total"] / total, 4) if total else 0,
        "math_converted_ratio": round(m["converted"] / m["total"], 4) if m["total"] else 0,
        "math_kept_ratio": round(m["kept"] / m["total"], 4) if m["total"] else 0,
    }


def _pct(num: int, den: int) -> str:
    return f"{num} ({num / den * 100:.1f}%)" if den else f"{num}"


def print_human(reports: list[dict]) -> None:
    print("=== 表格公式分布审计（A2）===")
    for r in reports:
        t, m = r["tables"], r["math"]
        print(f"\n[{r['book_id']}] {r['book']}  覆盖 {r['pages_covered']} · {r['chapter_count']} 章")
        print(f"  总表数 {r['tables_total']} | 转 MD {_pct(t['converted'], r['tables_total'])}"
              f" | 保留 HTML {_pct(t['kept'], r['tables_total'])}")
        if t["reasons"]:
            why = ", ".join(f"{k}={v}" for k, v in sorted(t["reasons"].items()))
            print(f"  门禁原因: {why}")
        print(f"  疑似公式表 {_pct(m['total'], r['tables_total'])}"
              f"（占总表 {r['math_ratio'] * 100:.1f}%）")
        print(f"    ├ 转 MD（公式可渲染）: {_pct(m['converted'], m['total'])}")
        print(f"    └ 保留 HTML（渲染无保证）: {_pct(m['kept'], m['total'])}")
        if m["kept_reasons"]:
            why = ", ".join(f"{k}={v}" for k, v in sorted(m["kept_reasons"].items()))
            print(f"        拦截原因: {why}")
            print(f"        含 rowspan/colspan（不可转）: {m['kept_merged']}"
                  f" | 含超长单元格: {m['kept_cell_too_long']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="表格公式分布审计（A2）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("book_id", nargs="?", type=int, help="教材 ID（缺省扫全部）")
    ap.add_argument("book_title", nargs="?", help="教材标题（与 book_id 成对）")
    args = ap.parse_args()

    if args.book_id is not None and not args.book_title:
        ap.error("指定 book_id 时必须同时给 book_title")

    if args.book_id is not None:
        targets = [(args.book_id, args.book_title)]
    else:
        if not settings.build_dir.exists():
            print(f"build 目录不存在: {settings.build_dir}", file=sys.stderr)
            return 2
        targets = []
        for d in sorted(settings.build_dir.iterdir()):
            m = RE_BUILD_DIR.match(d.name)
            if m and (d / "structure.json").exists():
                targets.append((int(m.group(1)), m.group(2)))

    if not targets:
        print("没有可审计的教材（build 产物缺失）", file=sys.stderr)
        return 2

    reports: list[dict] = []
    failed = False
    for book_id, title in targets:
        try:
            reports.append(audit_book(book_id, title))
        except FileNotFoundError as e:
            print(f"[{book_id}] {title}: {e}", file=sys.stderr)
            failed = True

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        print_human(reports)
        print(f"\n共 {len(reports)} 本教材；报告只读，未改动任何产物。")
    return 2 if failed else (1 if not reports else 0)


if __name__ == "__main__":
    sys.exit(main())