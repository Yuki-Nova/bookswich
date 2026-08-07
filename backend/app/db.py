"""SQLite 初始化：books 表（教材元数据）。

注：原 chunks / qa_logs（RAG 知识库）已于 2026-08-06 按用户决策移除，
项目只保留「解析 + 导出下载」功能。
"""
import sqlite3
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    edition TEXT DEFAULT '',
    publisher TEXT DEFAULT '',
    page_count INTEGER DEFAULT 0,
    parse_status TEXT DEFAULT 'pending',   -- pending|parsing|parsed|structure_ok|failed
    quota_used INTEGER DEFAULT 0,
    raw_path TEXT DEFAULT '',
    parse_progress TEXT DEFAULT '',        -- 如 "3/15"，解析进度
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    settings.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # 轻量迁移：为旧库补充缺失列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
        if "parse_progress" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN parse_progress TEXT DEFAULT ''")
