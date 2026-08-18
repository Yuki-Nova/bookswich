"""C4 真实教材黄金样本固化脚本（2026-08-18）。

可重复验证「结构重建 = 已知基线」，用于：每次 structure/export 规则修改后重跑，
确保不退化（章节数量/标题与记录一致即通过）。

用法（backend/ 目录）：
    .venv\\Scripts\\python.exe scripts/golden_samples.py           # 校验本地已知基线
    .venv\\Scripts\\python.exe scripts/golden_samples.py --update   # 生成/更新黄金样本基线 JSON
    .venv\\Scripts\\python.exe scripts/golden_samples.py --json     # 机器可读输出

黄金样本定义（哪些书、关注什么）：
    b1 概率统计        —— 公式/表格密集（本地）
    b6 分析化学        —— 目录驱动章节纠错（本地）
    b8 工业药剂学       —— 章数量受目录白名单影响（本地）
    服务器 5 本(6/7/8/9/11) —— 生产真实交付（需 --server 或手动提供数据）

基线文件: backend/data/build_golden_samples.json（不存在时需 --update 生成）
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings

# 黄金样本：本地 build 目录可用的教材 (book_id, 说明)
# 章节基线由 --update 时从 structure.json 采集并固化
GOLDEN_DIR = "build_golden_samples.json"


def collect_local_samples() -> dict:
    """从本地 data/build/ 采集所有教材的 (章数, 章标题) 基线。"""
    samples = {}
    if not settings.build_dir.exists():
        return samples
    for d in sorted(settings.build_dir.iterdir()):
        sf = d / "structure.json"
        if not sf.is_file():
            continue
        name_parts = d.name.split("_", 1)
        if len(name_parts) != 2 or not name_parts[0].startswith("b"):
            continue
        book_id = name_parts[0][1:]
        st = json.loads(sf.read_text(encoding="utf-8"))
        chapters = st.get("chapters", [])
        samples[d.name] = {
            "book_id": book_id,
            "chapter_count": len(chapters),
            "titles": [c.get("title", "") for c in chapters],
            "pages_covered": st.get("pages_covered", ""),
        }
    return samples


def verify(samples: dict, baseline: dict) -> tuple[int, list[str]]:
    """校验当前样本 vs 基线，返回 (通过数, 失败说明列表)。"""
    ok = 0
    failures = []
    for name, data in samples.items():
        bl = baseline.get(name)
        if bl is None:
            failures.append(f"{name}: 基线缺失（先 --update）")
            continue
        if data["chapter_count"] != bl["chapter_count"]:
            failures.append(
                f"{name}: 章数 {data['chapter_count']} != 基线 {bl['chapter_count']}"
            )
            continue
        if data["titles"] != bl["titles"]:
            failures.append(f"{name}: 章标题与基线不一致")
            continue
        ok += 1
    return ok, failures


def main() -> int:
    ap = argparse.ArgumentParser(description="黄金样本校验（C4）")
    ap.add_argument("--update", action="store_true", help="更新基线 JSON")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    baseline_path = settings.data_dir / GOLDEN_DIR
    samples = collect_local_samples()

    if args.update or not baseline_path.exists():
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"基线已更新: {baseline_path}（{len(samples)} 本）")
        return 0

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    ok, failures = verify(samples, baseline)

    if args.json:
        print(json.dumps({
            "ok": ok, "total": len(samples), "failures": failures,
        }, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print(f"=== 黄金样本校验（C4）===")
    print(f"通过 {ok}/{len(samples)}")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())