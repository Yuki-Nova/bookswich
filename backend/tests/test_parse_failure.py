"""B2: 解析异常状态与重试边界测试（2026-08-18）。

覆盖：
- parse_error 列迁移（旧库补列不丢数据）
- 网络瞬时异常有限重试（前 2 次抛、第 3 次成功 → 批次成功）
- 超过重试上限 → errors 记录、批次失败
- 路由：失败后写可读 parse_error；failed 状态可重新解析；parsing 拒绝并发
- recover_stale_parsing：异常退出遗留的 parsing 重置为 pending
"""
import json
import threading
from pathlib import Path

import pytest

from app.db import get_conn, init_db, recover_stale_parsing


def _fresh_env(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db()
    return tmp_path


# ── parse_error 列迁移 ──────────────────────────────

def test_parse_error_column_migrated(tmp_path, monkeypatch):
    """旧库（无 parse_error 列）init_db 后补列，数据保留。"""
    import sqlite3

    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    legacy = tmp_path / "kb.db"
    old = sqlite3.connect(legacy)
    old.execute(
        "CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
        " page_count INTEGER DEFAULT 0, parse_status TEXT DEFAULT 'pending')"
    )
    old.execute("INSERT INTO books (title, page_count) VALUES ('旧', 5)")
    old.commit()
    old.close()
    init_db()
    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
        n = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    assert "parse_error" in cols
    assert n == 1


# ── 有限重试 ────────────────────────────────────────

def test_parse_book_retries_transient_errors(tmp_path, monkeypatch):
    """_extract 前 2 次抛网络异常，第 3 次成功 → 批次成功、0 error。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")
    calls = {"n": 0}

    def fake_extract(self, pdf_path, pages):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("connection reset by peer (transient)")
        return {
            "markdown": f"# 内容 {pages}\n正文",
            "content_list": [],
            "images": [],
            "error": None,
        }

    monkeypatch.setattr(MineruParser, "_extract", fake_extract)
    # 小批量：10 页 → 1 批
    monkeypatch.setattr(
        "app.services.mineru_client.settings.parse_batch_size", 25
    )
    monkeypatch.setattr("app.services.mineru_client.RETRY_DELAYS", (0.0, 0.0))
    r = MineruParser().parse_book(1, str(pdf), total_pages=10, book_title="测试")
    assert r["errors"] == [], r["errors"]
    assert calls["n"] == 3  # 2 次重试后成功
    assert len(r["batch_files"]) == 1
    md = Path(r["batch_files"][0]).read_text(encoding="utf-8")
    assert "正文" in md


def test_parse_book_fails_after_max_retries(tmp_path, monkeypatch):
    """_extract 一直抛异常 → 重试 3 次后放弃，errors 有记录、无批次文件。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")
    calls = {"n": 0}

    def always_fail(self, pdf_path, pages):
        calls["n"] += 1
        raise ConnectionError("always down")

    monkeypatch.setattr(MineruParser, "_extract", always_fail)
    monkeypatch.setattr("app.services.mineru_client.RETRY_DELAYS", (0.0, 0.0))
    r = MineruParser().parse_book(1, str(pdf), total_pages=10, book_title="测试")
    assert calls["n"] == 3  # 1 次原始 + 2 次重试
    assert r["errors"], "应有错误记录"
    assert "网络异常，重试 2 次后仍失败" in r["errors"][0]  # 不泄漏底层异常细节
    assert r["batch_files"] == []


def test_parse_book_no_retry_on_business_failure(tmp_path, monkeypatch):
    """业务失败（云端返回 error 而非异常）不重试——避免重复消耗云端额度。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")
    calls = {"n": 0}

    def biz_fail(self, pdf_path, pages):
        calls["n"] += 1
        return {"markdown": None, "content_list": None, "images": [], "error": "server-side parse failed"}

    monkeypatch.setattr(MineruParser, "_extract", biz_fail)
    r = MineruParser().parse_book(1, str(pdf), total_pages=10, book_title="测试")
    assert calls["n"] == 1  # 只调 1 次
    assert r["errors"] and "server-side" in r["errors"][0]


# ── 路由：失败状态 + 可读错误 + 重试 ─────────────────

@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """TestClient 环境：1 本无解析的教材。"""
    _fresh_env(tmp_path, monkeypatch)
    from app.db import get_conn as _gc

    with _gc() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status, raw_path) "
            "VALUES ('测试书', 10, 'pending', ?)",
            (str(tmp_path / "book.pdf"),),
        )
    (tmp_path / "book.pdf").write_bytes(b"%PDF")
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app), tmp_path


def test_routes_failed_writes_parse_error(api_env, monkeypatch):
    """解析失败：parse_status='failed' 且 parse_error 为可读信息。"""

    def fake_parse_book(self, **kwargs):
        return {
            "batch_files": [],
            "batches_total": 1,
            "pages_used": 0,
            "files_reserved": 0,
            "skipped_cached": 0,
            "errors": ["batch 1: 配额不足或网络错误: boom"],
        }

    monkeypatch.setattr("app.api.routes.MineruParser.parse_book", fake_parse_book)
    client, tmp = api_env
    r = client.post("/api/books/1/parse")
    assert r.status_code == 200 and r.json()["status"] == "started"
    # 等待后台线程写完状态
    import time

    deadline = time.time() + 10
    status = ""
    while time.time() < deadline:
        with get_conn() as conn:
            status = conn.execute(
                "SELECT parse_status FROM books WHERE id=1"
            ).fetchone()[0]
        if status in ("failed", "parsed"):
            break
        time.sleep(0.2)
    with get_conn() as conn:
        row = conn.execute("SELECT parse_status, parse_error FROM books WHERE id=1").fetchone()
    assert row["parse_status"] == "failed"
    assert row["parse_error"] and "配额不足" in row["parse_error"]


def test_routes_can_retry_from_failed(api_env, monkeypatch):
    """failed 之后重新 POST /parse 返回 started（可重试）。"""
    from app.db import get_conn as _gc

    with _gc() as conn:
        conn.execute("UPDATE books SET parse_status='failed', parse_error='旧错误' WHERE id=1")

    client, _ = api_env
    r = client.post("/api/books/1/parse")
    assert r.status_code == 200 and r.json()["status"] == "started"


def test_routes_rejects_parallel_parsing(api_env):
    """parsing 中再次 POST /parse → 409。"""
    from app.db import get_conn as _gc

    with _gc() as conn:
        conn.execute("UPDATE books SET parse_status='parsing' WHERE id=1")
    client, _ = api_env
    assert client.post("/api/books/1/parse").status_code == 409


# ── 重启恢复 ────────────────────────────────────────

def test_recover_stale_parsing(tmp_path, monkeypatch):
    """遗留 parsing 状态启动恢复为 pending（可重新解析）。"""
    _fresh_env(tmp_path, monkeypatch)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status, parse_progress) "
            "VALUES ('卡死书', 10, 'parsing', '3/5')"
        )
    n = recover_stale_parsing()
    assert n == 1
    with get_conn() as conn:
        row = conn.execute("SELECT parse_status, parse_progress FROM books WHERE title='卡死书'").fetchone()
    assert row["parse_status"] == "pending" and row["parse_progress"] == ""