"""D1 教材重建/重导命令行（2026-08-18）。

用法（backend/ 目录，.venv 内，需 2 个位置参数：教材ID 教材标题）：
    .venv\\Scripts\\python.exe scripts/ops.py rebuild --id 1 --title 医药应用概率统计          # 只重建结构
    .venv\\Scripts\\python.exe scripts/ops.py export  --id 1 --title 医药应用概率统计 --out ../export # 只导出
    .venv\\Scripts\\python.exe scripts/ops.py import  --id 1 --title 医药应用概率统计          # 重建+导入 Obsidian
    .venv\\Scripts\\python.exe scripts/ops.py rebuild --id 1 --title 医药应用概率统计 --dry-run # 预演

不把真实教材标题硬编码到默认参数（必须显式传 --title）。
"""
import argparse
import io
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import get_conn  # noqa: E402
from app.services import exporter, structure  # noqa: E402


def _resolve_book(book_id: int) -> tuple[int, str]:
    with get_conn() as conn:
        row = conn.execute("SELECT id, title FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        print(f"错误：教材 #{book_id} 不存在。", file=sys.stderr)
        sys.exit(2)
    return row["id"], row["title"]


def cmd_rebuild(book_id: int, title: str, out: str | None = None, dry_run: bool = False) -> None:
    print(f"[{book_id}] 重建结构: {title}")
    if dry_run:
        print("  dry-run：跳过实际执行（将执行 structure.run）")
        return
    st = structure.run(book_id, title)
    print(f"  完成：{len(st.get('chapters', []))} 章（pages {st.get('pages_covered','')}）")
    print(f"  产物: {settings.build_dir / f'b{book_id}_{title}'}")


def cmd_export(book_id: int, title: str, out: str | None, dry_run: bool = False) -> None:
    out_dir = Path(out) if out else Path(settings.data_dir).parent / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{book_id}] 导出: {title} -> {out_dir}")
    if dry_run:
        print(f"  dry-run：将生成 {out_dir / f'{title}.md'}")
        return
    text = exporter.export_rebuilt(book_id, title)
    stem = exporter._sanitize_filename(title)
    dest = out_dir / f"{stem}.md"
    dest.write_text(text, encoding="utf-8")
    print(f"  完成: {dest}（{len(text)//1024}KB）")


def cmd_import(book_id: int, title: str, out: str | None = None, dry_run: bool = False) -> None:
    """重建结构 + 导出 Obsidian 版并解压到 vault。"""
    if not settings.obsidian_vault_dir:
        print("错误：未配置 OBSIDIAN_VAULT_DIR（backend/.env）", file=sys.stderr)
        sys.exit(3)
    if not settings.oss_configured:
        print("错误：未配置 OSS（图片转外链需要）", file=sys.stderr)
        sys.exit(3)
    print(f"[{book_id}] 重建 + 导入 Obsidian: {title}")
    if dry_run:
        print("  dry-run：将 ①structure.run ②export_obsidian_zip(oss) ③解压到 "
              f"{settings.obsidian_vault_dir / settings.obsidian_sub_dir}")
        return
    cmd_rebuild(book_id, title)
    zip_bytes = exporter.export_obsidian_zip(book_id, title, image_mode="oss")
    target = settings.obsidian_vault_dir / settings.obsidian_sub_dir
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    book_folder = exporter._sanitize_filename(title)
    stale = target / book_folder
    if stale.exists():
        shutil.rmtree(stale)
    n = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for m in zf.infolist():
            dest = (target / m.filename).resolve()
            if not dest.is_relative_to(target_resolved):
                print(f"非法路径，终止: {m.filename}", file=sys.stderr)
                sys.exit(4)
            if m.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(m.filename))
                n += 1
    print(f"  导入完成: {target / book_folder}（{n} 文件）")


def main() -> None:
    ap = argparse.ArgumentParser(description="bookswich 运维命令（D1）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("rebuild", cmd_rebuild), ("export", cmd_export), ("import", cmd_import)):
        p = sub.add_parser(name, help=fn.__doc__.splitlines()[0] if fn.__doc__ else "")
        p.add_argument("--id", type=int, required=True)
        p.add_argument("--title", required=True)
        p.add_argument("--out", default=None)
        p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    book_id, title = _resolve_book(args.id)
    if args.cmd == "rebuild":
        cmd_rebuild(book_id, title, args.out, args.dry_run)
    elif args.cmd == "export":
        cmd_export(book_id, title, args.out, args.dry_run)
    else:
        cmd_import(book_id, title, args.out, args.dry_run)


if __name__ == "__main__":
    main()