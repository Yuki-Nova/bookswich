"""SQLite 初始化：books 表（教材元数据）。

注：原 chunks / qa_logs（RAG 知识库）已于 2026-08-06 按用户决策移除，
项目只保留「解析 + 导出下载」功能。

B1（2026-08-18）：get_conn 增加 busy_timeout 30s + timeout 参数；init_db 启用 WAL。
B2（2026-08-18）：books 表新增 parse_error 列（解析失败的可读原因）。
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
    quota_files INTEGER DEFAULT 0,          -- 该书是否已计入每日文件数（0/1，防续跑重复计）
    raw_path TEXT DEFAULT '',
    parse_progress TEXT DEFAULT '',        -- 如 "3/15"，解析进度
    parse_error TEXT DEFAULT '',            -- 解析失败的可读原因（B2）
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
"""


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    """新建 SQLite 连接（B1：busy_timeout 30s，防并发写锁立即报错）。

    每次调用新建连接、`with` 内短事务（项目约定，无长连接）；
    busy_timeout 让写冲突时等待而非立即抛 database is locked。
    """
    conn = sqlite3.connect(
        db_path or settings.db_path,
        timeout=30,  # 连接级 busy 等待，与下方 PRAGMA 一致
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    settings.ensure_dirs()
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # B1：WAL 模式（文件级持久，读写不互斥）
        conn.executescript(SCHEMA)
        # 轻量迁移：为旧库补充缺失列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(books)").fetchall()}
        if "parse_progress" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN parse_progress TEXT DEFAULT ''")
        if "quota_files" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN quota_files INTEGER DEFAULT 0")
        if "parse_error" not in cols:
            conn.execute("ALTER TABLE books ADD COLUMN parse_error TEXT DEFAULT ''")


def recover_stale_parsing() -> int:
    """重置上次进程异常退出遗留的 parsing 状态（daemon 线程随进程死亡，书会永久卡 parsing、删不掉）。

    返回被重置的记录数。
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE books SET parse_status='pending', parse_progress='' WHERE parse_status='parsing'"
        )
        return cur.rowcount
