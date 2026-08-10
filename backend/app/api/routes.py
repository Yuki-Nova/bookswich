"""API 路由。"""
import json
import logging
import shutil
import threading
import time
from datetime import date
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from urllib.parse import quote

from ..config import settings
from ..db import get_conn
from ..services.mineru_client import MineruParser, QuotaManager

logger = logging.getLogger(__name__)

router = APIRouter()


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


@router.get("/health")
async def health():
    return {"status": "ok", "data_dir": str(settings.data_dir)}


# ── 教材 ──────────────────────────────────────────────


class BookCreate(BaseModel):
    title: str
    author: str = ""
    edition: str = ""
    publisher: str = ""
    page_count: int = 0
    raw_path: str = ""


@router.post("/books")
async def create_book(body: BookCreate):
    """注册教材。raw_path 为服务器本地 PDF 路径。"""
    raw_path = ""
    if body.raw_path:
        src = Path(body.raw_path)
        if not src.exists():
            raise HTTPException(400, f"raw_path 不存在: {src}")
        settings.ensure_dirs()
        dest = settings.raw_dir / src.name
        if not dest.exists():
            import shutil

            shutil.copy2(src, dest)
        raw_path = str(dest)

    with get_conn() as conn:
        _ensure_column(conn, "books", "parse_progress", "TEXT DEFAULT ''")
        cur = conn.execute(
            "INSERT INTO books (title, author, edition, publisher, page_count, raw_path) "
            "VALUES (?,?,?,?,?,?)",
            (body.title, body.author, body.edition, body.publisher, body.page_count, raw_path),
        )
        book_id = cur.lastrowid
    return {"book_id": book_id}


def _detect_pages(pdf_path: str) -> int:
    """用 PyMuPDF 检测 PDF 页数。"""
    try:
        import fitz

        doc = fitz.open(pdf_path)
        n = doc.page_count
        doc.close()
        return n
    except Exception:
        return 0


@router.post("/books/upload")
async def upload_book(file: UploadFile = File(...)):
    """上传 PDF（multipart），自动检测页数并注册教材。"""
    filename = file.filename or "unnamed.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 PDF 文件")
    settings.ensure_dirs()
    dest = settings.raw_dir / f"{int(time.time())}_{filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    page_count = _detect_pages(str(dest))
    if page_count <= 0:
        # 页数检测失败（服务器缺 PyMuPDF 或文件损坏）→ 清理并明确报错，不落 0 页假数据
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "无法读取 PDF 页数（服务器环境缺 PyMuPDF 或文件损坏）")
    title = Path(filename).stem
    with get_conn() as conn:
        _ensure_column(conn, "books", "parse_progress", "TEXT DEFAULT ''")
        cur = conn.execute(
            "INSERT INTO books (title, page_count, raw_path) VALUES (?,?,?)",
            (title, page_count, str(dest)),
        )
        book_id = cur.lastrowid
    return {"book_id": book_id, "title": title, "page_count": page_count, "raw_path": str(dest)}


@router.get("/books/{book_id}")
async def get_book(book_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    d = dict(row)
    d["md_dir"] = str(settings.md_dir / f"b{book_id}_{row['title']}")
    return d


@router.get("/books")
async def list_books():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, author, edition, page_count, parse_status, "
            "parse_progress, quota_used, raw_path, created_at FROM books ORDER BY id"
        ).fetchall()
    return {"books": [dict(r) for r in rows]}


@router.delete("/books/{book_id}")
async def delete_book(book_id: int):
    """删除教材：移除服务器上全部相关遗留文件（raw PDF + md/ + build/）并删除 db 记录。

    返回删除的文件/目录清单（可安全重试——文件不存在时静默跳过）。
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not row:
            raise HTTPException(404, "book not found")
        if row["parse_status"] == "parsing":
            raise HTTPException(409, "解析进行中，无法删除")

    removed = {"raw": [], "md": [], "build": []}

    # 1) 原始 PDF（raw_path 可能是服务器任意路径，仅删除位于 data/raw/ 内的文件，防路径穿越）
    if row["raw_path"]:
        raw = Path(row["raw_path"])
        try:
            raw_rel = raw.resolve().relative_to(settings.raw_dir.resolve())
        except ValueError:
            raw_rel = None
        if raw_rel is not None and raw.exists():
            raw.unlink(missing_ok=True)
            removed["raw"].append(str(raw))

    # 2) 解析产物 data/md/b{id}_{title}/
    md_dir = settings.md_dir / f"b{book_id}_{row['title']}"
    if md_dir.exists():
        shutil.rmtree(md_dir)
        removed["md"].append(str(md_dir))

    # 3) 结构重建产物 data/build/b{id}_{title}/
    build_dir = settings.build_dir / f"b{book_id}_{row['title']}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        removed["build"].append(str(build_dir))

    # 4) db 记录
    with get_conn() as conn:
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))

    return {
        "status": "ok",
        "book_id": book_id,
        "title": row["title"],
        "removed": removed,
    }


# ── 解析 ──────────────────────────────────────────────


@router.post("/books/{book_id}/parse")
async def start_parse(book_id: int):
    """后台线程分批解析全书（MinerU）。返回 started 后由 GET /books/{id} 轮询进度。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    if not row["raw_path"] or not Path(row["raw_path"]).exists():
        raise HTTPException(400, "教材未关联有效 PDF（需先注册 raw_path）")
    if row["parse_status"] == "parsing":
        raise HTTPException(409, "解析已在进行中")

    parser = MineruParser()

    def _run():
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE books SET parse_status='parsing', parse_progress='0/0' WHERE id=?",
                    (book_id,),
                )

            def _progress(done: int, total: int):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE books SET parse_status='parsing', parse_progress=? WHERE id=?",
                        (f"{done}/{total}", book_id),
                    )

            result = parser.parse_book(
                book_id=book_id,
                pdf_path=row["raw_path"],
                total_pages=row["page_count"],
                book_title=row["title"],
                progress_cb=_progress,
            )
            ok = not result["errors"]
            final_status = "parsed" if ok else "failed"

            # 解析成功后自动跑结构重建（生成 structure.json，chapters/按章导出依赖它）
            if ok:
                try:
                    from ..services import structure

                    structure.run(book_id, row["title"])
                    final_status = "structure_ok"
                except Exception:
                    # 重建失败不致命：保持 parsed，可后续手动重跑 structure.run
                    logger.exception("structure.run failed for book %s", book_id)

            with get_conn() as conn:
                conn.execute(
                    "UPDATE books SET parse_status=?, parse_progress=?, quota_used=? WHERE id=?",
                    (
                        final_status,
                        f"{len(result['batch_files'])}/{result['batches_total']}",
                        result["pages_used"],
                        book_id,
                    ),
                )
        except Exception:
            logger.exception("parse thread crashed for book %s", book_id)
            try:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE books SET parse_status='failed' WHERE id=?", (book_id,)
                    )
            except Exception:
                logger.exception("failed to mark book %s as failed", book_id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "book_id": book_id}


# ── 导出 ──────────────────────────────────────────────


@router.get("/books/{book_id}/chapters")
async def list_chapters(book_id: int):
    """教材章节列表（结构重建产物）。"""
    from ..services import exporter

    with get_conn() as conn:
        row = conn.execute("SELECT id, title FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    try:
        titles = exporter.chapter_titles(book_id, row["title"])
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    return {"book_id": book_id, "chapters": [{"no": i + 1, "title": t} for i, t in enumerate(titles)]}


@router.get("/books/{book_id}/export")
async def export_markdown(
    book_id: int,
    format: str = "rebuilt",
    chapter: int | None = None,
    images: str = "local",
):
    """下载教材 Markdown：format=rebuilt（结构重建后，默认）| raw（MinerU 原始合并）；
    chapter 指定时只导出该章（rebuilt 支持）。
    images=local（默认，图片打进 zip）| oss（图片传 OSS，md 引用改公网 URL）。"""
    from ..services import exporter

    with get_conn() as conn:
        row = conn.execute("SELECT id, title FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    if format not in ("rebuilt", "raw", "obsidian"):
        raise HTTPException(400, "format 参数必须是 rebuilt / raw / obsidian")
    if images not in ("local", "oss"):
        raise HTTPException(400, "images 参数必须是 local / oss")
    if images == "oss" and not settings.oss_configured:
        raise HTTPException(
            400, "未配置 OSS（backend/.env 缺少 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET）"
        )
    try:
        if format == "obsidian":
            zip_bytes = exporter.export_obsidian_zip(book_id, row["title"], image_mode=images)
            stem = row["title"]
            filename = f"{stem}-Obsidian.zip"
            headers = {
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            }
            return Response(
                content=zip_bytes, media_type="application/zip", headers=headers
            )
        if format == "rebuilt":
            text = exporter.export_rebuilt(book_id, row["title"], chapter=chapter)
        else:
            if chapter is not None:
                raise HTTPException(400, "raw 格式不支持按章导出")
            text = exporter.export_raw(book_id, row["title"])
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    stem = f"{row['title']}{f'-第{chapter}章' if chapter else ''}"
    # 打包 zip（md + images/ 子目录，图片相对引用可用），解压即 Obsidian/Typora 可读
    zip_bytes = exporter.export_zip(book_id, row["title"], text, f"{stem}.md", image_mode=images)
    filename = f"{stem}.zip"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    }
    return Response(
        content=zip_bytes, media_type="application/zip", headers=headers
    )


@router.post("/books/{book_id}/import-obsidian")
async def import_obsidian(book_id: int):
    """按章拆分导入 Obsidian vault（需 .env 配置 OBSIDIAN_VAULT_DIR + OSS）。

    生成 <vault>/<obsidian_sub_dir>/<书名>/ 目录：00_总览.md + 各章 md。
    图片转 OSS 外链（OSS_BUCKET 配置的桶）：md 引用公网 URL，vault 只落文本，
    不写 images/ —— 多端同步（WebDAV/Syncthing）时 vault 体积最小化。
    """
    import io
    import zipfile

    from ..services import exporter

    if not settings.obsidian_vault_dir:
        raise HTTPException(400, "未配置 OBSIDIAN_VAULT_DIR（backend/.env）")
    if not settings.oss_configured:
        raise HTTPException(
            400, "未配置 OSS（backend/.env 缺少 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET），图片转外链需要 OSS"
        )
    with get_conn() as conn:
        row = conn.execute("SELECT id, title FROM books WHERE id=?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "book not found")
    try:
        data = exporter.export_obsidian_zip(book_id, row["title"], image_mode="oss")
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    target = settings.obsidian_vault_dir / settings.obsidian_sub_dir
    target.mkdir(parents=True, exist_ok=True)
    target_resolved = target.resolve()
    n_files = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for m in zf.infolist():
            dest = (target / m.filename).resolve()
            if not str(dest).startswith(str(target_resolved)):
                raise HTTPException(400, f"非法路径: {m.filename}")
        zf.extractall(target)
        n_files = len(zf.infolist())
    return {"status": "ok", "target": str(target), "files": n_files}


# ── 配置 ──────────────────────────────────────────────


@router.get("/settings")
async def settings_status():
    """前端需要的配置状态（Obsidian vault 是否已配置等）。"""
    return {
        "obsidian_vault_configured": bool(settings.obsidian_vault_dir),
        "obsidian_sub_dir": settings.obsidian_sub_dir,
    }


# ── 配额 ──────────────────────────────────────────────


@router.get("/quota")
async def quota_status():
    q = QuotaManager()
    return {
        # 双维度（2026-08-10）：优先页数 + 文件数
        "daily_priority_pages": settings.daily_quota_pages,
        "priority_used": q.priority_used_today(),
        "priority_remaining": q.priority_remaining(),
        "priority_exhausted": q.priority_exhausted(),
        "daily_file_limit": settings.daily_file_limit,
        "files_used": q.files_used_today(),
        "files_remaining": q.files_remaining(),
        "date": date.today().isoformat(),
        "has_api_key": bool(settings.mineru_api_key),
        # 兼容旧字段（前端过渡期）
        "daily_limit": settings.daily_quota_pages,
        "used": q.priority_used_today(),
        "remaining": q.priority_remaining(),
    }
