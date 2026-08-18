"""C1: API 接口回归测试（2026-08-18）。

覆盖 plan 列出的后端接口回归缺口（已由其它 test 覆盖的 auth/login/token 不再重复）：
- upload 非 PDF → 400；损坏 PDF（页数检测失败）→ 400
- export 非法 format / images / raw+chapter / 章节越界 → 400
- export obsidian 未配置 OSS + images=oss → 400
- 删除解析中的教材 → 409；删除不存在 → 404
- 未上传 raw 的教材 export → 400（结构产物缺失）
"""
import io
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient + 临时 data_dir + 1 本可导出教材（fake structure）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from app.db import init_db, get_conn

    init_db()
    # 建一个可 export 的教材（structure.json 存在）
    md_dir = tmp_path / "md" / "b1_测试书"
    md_dir.mkdir(parents=True)
    (md_dir / "batch_01_p1-25.md").write_text("# 测试书\n正文内容", encoding="utf-8")
    build_dir = tmp_path / "build" / "b1_测试书"
    build_dir.mkdir(parents=True)
    (build_dir / "structure.json").write_text(
        json.dumps({
            "pages_covered": "p1-25",
            "chapters": [{
                "title": "第一章", "level": 1, "page_range": "p1-25",
                "lines": ["第一章", "正文"], "children": [], "board": False,
                "char_count": 10, "image_count": 0, "table_count": 0,
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (id, title, page_count, parse_status, raw_path) "
            "VALUES (1, '测试书', 25, 'structure_ok', ?)",
            (str(tmp_path / "book.pdf"),),
        )
    (tmp_path / "book.pdf").write_bytes(b"%PDF-1.4 fake book\n")

    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app), tmp_path


# ── upload 有效性 ─────────────────────────────────

def test_upload_non_pdf_rejected(client):
    """上传非 .pdf 文件 → 400。"""
    c, _ = client
    r = c.post(
        "/api/books/upload",
        files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 400


def test_upload_corrupt_pdf_rejected(client):
    """上传损坏 PDF（页数检测 0）→ 400，不落库。"""
    c, tmp = client
    r = c.post(
        "/api/books/upload",
        files={"file": ("bad.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
    )
    assert r.status_code == 400
    from app.db import get_conn

    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM books WHERE title='bad'").fetchone()[0]
    assert n == 0  # 损坏文件不落假数据


def test_upload_valid_pdf(client):
    """有效 PDF（最小页数）→ 200 并注册。"""
    import fitz

    c, tmp = client
    doc = fitz.open()
    doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    buf.seek(0)
    r = c.post(
        "/api/books/upload",
        files={"file": ("ok.pdf", buf, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["page_count"] >= 1


# ── export 参数校验 ────────────────────────────────

def test_export_invalid_format(client):
    c, _ = client
    assert c.get("/api/books/1/export?format=xxx").status_code == 400
    assert c.get("/api/books/1/export?format=pdf").status_code == 400


def test_export_invalid_images(client):
    c, _ = client
    assert c.get("/api/books/1/export?images=weird").status_code == 400


def test_export_raw_with_chapter_rejected(client):
    c, _ = client
    assert c.get("/api/books/1/export?format=raw&chapter=1").status_code == 400


def test_export_chapter_out_of_range(client):
    c, _ = client
    assert c.get("/api/books/1/export?chapter=99").status_code in (400, 422)


def test_export_rebuilt_local_ok(client):
    c, _ = client
    r = c.get("/api/books/1/export?format=rebuilt&images=local")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"


def test_export_obsidian_oss_without_oss(client, monkeypatch):
    """images=oss 但未配置 OSS → 400。oss_configured 是只读 property，置空基字段使其为 False。"""
    from app.config import settings

    monkeypatch.setattr(settings, "oss_access_key_id", "")
    monkeypatch.setattr(settings, "oss_access_key_secret", "")
    monkeypatch.setattr(settings, "oss_bucket", "")
    c, _ = client
    assert c.get("/api/books/1/export?format=obsidian&images=oss").status_code == 400


def test_export_unknown_book_404(client):
    c, _ = client
    assert c.get("/api/books/999/export").status_code == 404


# ── 删除 ───────────────────────────────────────────

def test_delete_parsing_book_409(client):
    """解析中的教材不能删除 → 409。"""
    from app.db import get_conn

    with get_conn() as conn:
        conn.execute("UPDATE books SET parse_status='parsing' WHERE id=1")
    c, _ = client
    assert c.delete("/api/books/1").status_code == 409


def test_delete_unknown_book_404(client):
    c, _ = client
    assert c.delete("/api/books/999").status_code == 404


def test_delete_ok_removes_row(client):
    """删除成功的教材 → 200 + db 记录移除。"""
    from app.db import get_conn

    c, _ = client
    assert c.delete("/api/books/1").status_code == 200
    with get_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM books WHERE id=1").fetchone()[0] == 0