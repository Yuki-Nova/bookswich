"""导出物静态规则回归扫描 CLI（A4，2026-08-18）。

用法（backend/ 目录下）:
    .venv\\Scripts\\python.exe scripts/verify_export.py <md文件> [images目录]

输出 JSON 数组（机器可读，含 rule/severity/line/message）；
存在 error 级 issue 时退出码 1，仅 warning 或无问题退出码 0。

示例:
    .venv\\Scripts\\python.exe scripts/verify_export.py ^
        ../export/医药应用概率统计.md ../data/md/b1_医药应用概率统计
说明: images 目录参数传 md 同级的 data/md/<book> 目录（引用本身含 images/ 前缀）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.verify_export import scan_export


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    md_path = Path(sys.argv[1])
    img_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if not md_path.exists():
        print(f"文件不存在: {md_path}", file=sys.stderr)
        return 2
    issues = scan_export(md_path.read_text(encoding="utf-8"), img_dir)
    print(json.dumps(issues, ensure_ascii=False, indent=2))
    if issues:
        n_err = sum(1 for x in issues if x["severity"] == "error")
        print(f"# {len(issues)} issue(s)，其中 error {n_err} 个", file=sys.stderr)
    return 1 if any(x["severity"] == "error" for x in issues) else 0


if __name__ == "__main__":
    sys.exit(main())