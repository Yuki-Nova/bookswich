"""B1: SQLite 并发与事务配置测试（2026-08-18）。

覆盖：
- get_conn 连接级 busy_timeout ≥30s
- init_db 开启 WAL（文件级持久）
- 多线程并发读写压力：无 database is locked / 无异常 / 数据一致
- 后台进度更新短事务并发（解析线程模式）
- 旧库轻量迁移不丢数据
"""
import sqlite3
import threading
from pathlib import Path

import pytest

from app.db import get_conn, init_db


def test_get_conn_busy_timeout():
    """连接级 busy_timeout 默认 ≥30s（默认 0 = 立即报锁）。"""
    with get_conn() as conn:
        ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert ms >= 30000, f"busy_timeout={ms}ms，应 ≥30000ms"


def test_init_db_wal_enabled(tmp_path, monkeypatch):
    """init_db 后 journal_mode 为 wal（写 db 文件头，持久生效）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db()
    with get_conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"journal_mode={mode}，应为 wal"


def _hammer(db_path: Path, n_threads: int = 8, per_thread: int = 30) -> list[Exception]:
    """并发读写压力：INSERT + UPDATE + SELECT 循环。"""
    errors: list[Exception] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(tid: int):
        try:
            barrier.wait(timeout=10)
            for i in range(per_thread):
                with get_conn(db_path) as c:
                    c.execute(
                        "INSERT INTO books (title, page_count, parse_status) VALUES (?,?,?)",
                        (f"t{tid}-{i}", 10, "pending"),
                    )
                    c.execute(
                        "UPDATE books SET parse_progress=? WHERE id=?",
                        (f"{i}/10", c.execute("SELECT last_insert_rowid()").fetchone()[0]),
                    )
                    c.execute("SELECT COUNT(*) FROM books").fetchone()
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    return errors


def test_concurrent_write_read_no_lock(tmp_path, monkeypatch):
    """8 线程 ×30 次读写：0 锁冲突、行数精确、无 database is locked。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db()
    errors = _hammer(tmp_path / "kb.db")
    assert errors == [], f"并发异常: {[type(e).__name__ + ': ' + str(e)[:80] for e in errors]}"
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    assert n == 8 * 30, f"行数 {n} ≠ 240"


def test_concurrent_progress_updates(tmp_path, monkeypatch):
    """模拟解析线程进度更新（短 UPDATE 事务）：无锁、进度字段正确。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status) VALUES ('b', 100, 'parsing')"
        )
        book_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    errors: list[Exception] = []
    lock = threading.Lock()
    n_writes = 50

    def updater():
        try:
            for i in range(n_writes):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE books SET parse_progress=? WHERE id=?",
                        (f"{i}/50", book_id),
                    )
        except Exception as e:  # noqa: BLE001
            with lock:
                errors.append(e)

    ts = [threading.Thread(target=updater) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=60)
    assert errors == []
    with get_conn() as conn:
        row = conn.execute("SELECT parse_progress FROM books WHERE id=?", (book_id,)).fetchone()
    assert row[0] == "49/50"  # 最后一次写入胜出（SAR 语义）


def test_legacy_db_migration_keeps_data(tmp_path, monkeypatch):
    """旧 schema 库（缺 parse_progress/quota_files 列）init_db 迁移后数据保留。"""
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    legacy = tmp_path / "kb.db"
    legacy_conn = sqlite3.connect(legacy)
    legacy_conn.executescript(
        "CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
        " page_count INTEGER DEFAULT 0, parse_status TEXT DEFAULT 'pending');"
        "INSERT INTO books (title, page_count, parse_status) VALUES ('旧书', 99, 'parsed');"
    )
    legacy_conn.commit()
    legacy_conn.close()

    init_db()
    with get_conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
        row = conn.execute("SELECT title, page_count FROM books WHERE id=1").fetchone()
    assert {"parse_progress", "quota_files"} <= cols
    assert row["title"] == "旧书" and row["page_count"] == 99