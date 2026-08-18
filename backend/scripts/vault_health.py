"""D2 vault 体检命令（2026-08-18）。

扫描 Obsidian vault 教材库，输出健康状态：
- 教材目录与章节数量（对照左侧 data/build structure）
- MOC 链接是否存在（00_总览.md 的 [[]] 引用）
- 图片引用是否为 OSS URL
- 残留 HTML/实体/坏公式/异常空行
- 同名旧目录和孤儿 md

用法： .venv\\Scripts\\python.exe scripts/vault_health.py [--vault DIR] [--json]
默认 vault = settings.obsidian_vault_dir / obsidian_sub_dir。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

# 残留检测规则（A/B 阶段定义过，体检复用）
RE_HTML_TAG = re.compile(r"</?(table|div|span|p|br|img|tr|td|th)[^>]*>", re.I)
RE_HTML_ENTITY = re.compile(r"&[a-z]+;|&#\d+;")
RE_LATEX = re.compile(r"\$\$.*?\$\$|\$[^$\n]+?\$", re.S)
RE_BAD_BRIEF = re.compile(r"\\\(|\\\)")  # 裸 LaTeX 括号残留
RE_BLANK_RUN = re.compile(r"\n{3,}")


def scan_dir(structure_dir: Path | None, vault_sub: Path) -> dict:
    """单个 vault 教材目录的体检。structure_dir 可为 None（无对应左侧结构）。"""
    report = {"dir": vault_sub.name, "chapter_count": 0, "moc_ok": False,
              "image_non_oss": 0, "html_tag": 0, "html_entity": 0, "bad_math": 0,
              "blank_run": 0, "orphan_md": []}
    # 章节数：从 build structure 读（左侧数据为准）
    if structure_dir is not None and structure_dir.exists():
        sf = structure_dir / "structure.json"
        if sf.exists():
            st = json.loads(sf.read_text(encoding="utf-8"))
            report["chapter_count"] = len(st.get("chapters", []))
    # 各 md 文件扫描
    mds = sorted(vault_sub.rglob("*.md"))
    for f in mds:
        t = f.read_text(encoding="utf-8", errors="replace")
        # MOC：00_总览 里有 [[]] 章节链接
        if f.name.startswith("00_") or "总览" in f.stem:
            report["moc_ok"] = "[[" in t
        # 图片引用非 OSS（本地相对图/缺 src）
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", t):
            url = m.group(1)
            if not re.match(r"^https?://", url):
                report["image_non_oss"] += 1
        report["html_tag"] += len(RE_HTML_TAG.findall(t))
        report["html_entity"] += len(RE_HTML_ENTITY.findall(t))
        report["bad_math"] += len(RE_BAD_BRIEF.findall(t))
        report["blank_run"] += len(RE_BLANK_RUN.findall(t))
    # 孤儿 md：不属于任何章节命名（非 00_总览 也非 第x章）
    known = {"总览"}
    for f in mds:
        if f.name.startswith("00_"):
            continue
        if re.match(r"^第[一二三四五六七八九十百\d]+章", f.stem) or f.stem.startswith("第"):
            known.add(f.stem)
    for f in mds:
        if f.stem not in known and not f.name.startswith("00_"):
            report["orphan_md"].append(f.name)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="vault 体检（D2）")
    ap.add_argument("--vault", default=None, help="vault 教材库目录（默认 settings.obsidian_...）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.vault:
        vault_sub = Path(args.vault)
    elif settings.obsidian_vault_dir:
        vault_sub = settings.obsidian_vault_dir / settings.obsidian_sub_dir
    else:
        print("错误：未配置 OBSIDIAN_VAULT_DIR，需 --vault 指定目录", file=sys.stderr)
        return 3
    if not vault_sub.exists():
        print(f"错误：vault 目录不存在: {vault_sub}", file=sys.stderr)
        return 3

    reports = []
    structure_root = settings.build_dir
    # 教材目录 = vault_sub 下每个子目录对应一本（其 build structure 在 data/build/b<id>_<sanitize title>）
    for book_dir in sorted(vault_sub.iterdir()):
        if not book_dir.is_dir():
            continue
        # 匹配左侧 structure 目录名（b<id>_<书名> 前缀）
        matched = None
        if structure_root.exists():
            for sd in sorted(structure_root.iterdir()):
                # 用书名匹配：strip 书名里非法字符后的比对太脆，直接用 build 目录 title 段
                title_seg = sd.name.split("_", 1)[-1] if "_" in sd.name else sd.name
                if title_seg and title_seg in book_dir.name:
                    matched = sd
                    break
        reports.append(scan_dir(matched, book_dir))

    # 汇总
    issues = sum(r["image_non_oss"] + r["html_tag"] + r["html_entity"] + r["bad_math"]
                 + r["blank_run"] + len(r["orphan_md"]) for r in reports)
    if args.json:
        print(json.dumps({"books": reports, "issue_count": issues, "healthy": issues == 0},
                         ensure_ascii=False, indent=2))
        return 1 if issues else 0

    print("=== vault 体检（D2）===")
    for r in reports:
        flag = "OK" if (r["image_non_oss"] + r["html_tag"] + r["html_entity"] + r["bad_math"]
                        + r["blank_run"] + len(r["orphan_md"])) == 0 else "ISSUE"
        print(f"[{flag}] {r['dir']}: {r['chapter_count']}章  MOC={r['moc_ok']} "
              f"非OSS图={r['image_non_oss']} HTML={r['html_tag']} 实体={r['html_entity']} "
              f"坏公式={r['bad_math']} 空行={r['blank_run']} 孤儿={r['orphan_md']}")
    print(f"共 {len(reports)} 教材，问题 {issues} 处" if issues else f"共 {len(reports)} 教材，全部健康")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())