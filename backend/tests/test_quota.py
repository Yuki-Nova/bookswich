"""QuotaManager 双维度配额记账 + parse_book 超限逻辑 + /api/quota 接口测试。

覆盖（2026-08-10 配额模型修正）：
- 双维度记账（priority_pages_used / files_used）
- 跨日重置 / 旧结构 {date, used} 迁移
- 并发安全（全局锁：多个 QuotaManager 实例写同一文件不丢计数）
- parse_book：优先页数不足不中断、文件数满额中断、续跑不重复计文件数
- /api/quota 返回双维度字段
"""
import json
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import settings
from app.services.mineru_client import QuotaManager, MineruParser


# ── QuotaManager ──────────────────────────────────────


def test_double_dimension_accounting(tmp_path):
    q = QuotaManager(tmp_path / "quota.json")
    assert q.priority_used_today() == 0
    assert q.files_used_today() == 0
    assert q.priority_remaining() == settings.daily_quota_pages
    assert q.files_remaining() == settings.daily_file_limit
    assert not q.priority_exhausted()

    q.add_pages(25)
    q.add_pages(30)
    assert q.priority_used_today() == 55
    assert q.priority_remaining() == settings.daily_quota_pages - 55
    assert not q.priority_exhausted()

    assert q.try_reserve_file()
    assert q.files_used_today() == 1
    assert q.files_remaining() == settings.daily_file_limit - 1


def test_day_rollover_resets(tmp_path):
    q = QuotaManager(tmp_path / "quota.json")
    q.add_pages(10)
    q.try_reserve_file()
    # 伪造昨天日期 → 跨日重置
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = json.loads(q.path.read_text(encoding="utf-8"))
    data["date"] = yesterday
    q.path.write_text(json.dumps(data), encoding="utf-8")
    assert q.priority_used_today() == 0
    assert q.files_used_today() == 0


def test_old_structure_migration(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text(
        json.dumps({"date": date.today().isoformat(), "used": 42}), encoding="utf-8"
    )
    q = QuotaManager(path)
    assert q.priority_used_today() == 42
    assert q.files_used_today() == 0
    # 写回后落盘新结构
    q.add_pages(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "used" not in data
    assert data["priority_pages_used"] == 43
    assert "files_used" in data


def test_concurrent_pages_atomic(tmp_path):
    """多个 QuotaManager 实例（模拟并发请求各自 new）写同一文件不丢计数。"""
    n = 30
    threads = []
    for _ in range(n):
        t = threading.Thread(
            target=lambda: QuotaManager(tmp_path / "quota.json").add_pages(1)
        )
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert QuotaManager(tmp_path / "quota.json").priority_used_today() == n


def test_concurrent_file_slots(monkeypatch, tmp_path):
    """10 个并发抢 3 个文件名额 → 恰好 3 个成功。"""
    monkeypatch.setattr(settings, "daily_file_limit", 3)
    results: list = []

    def worker():
        results.append(QuotaManager(tmp_path / "quota.json").try_reserve_file())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 3
    assert QuotaManager(tmp_path / "quota.json").files_used_today() == 3


# ── parse_book 配额行为 ───────────────────────────────


@pytest.fixture
def fake_db(tmp_path, monkeypatch):
    """临时 data_dir + init_db + 插入一本测试书（60 页 → 3 批）。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from app.db import init_db, get_conn

    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status, raw_path) "
            "VALUES (?,?,?,?)",
            ("测试书", 60, "pending", str(tmp_path / "test.pdf")),
        )
    return tmp_path


def _mk_parser(tmp_path, monkeypatch, quota_pages=0, quota_files=0):
    """构造 MineruParser：直接写 quota.json 预设配额 + _extract mock 记录调用。"""
    qpath = tmp_path / "quota.json"
    qpath.write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "priority_pages_used": quota_pages,
                "files_used": quota_files,
            }
        ),
        encoding="utf-8",
    )
    parser = MineruParser(api_key="fake")
    calls: list = []

    def fake_extract(pdf_path: str, pages: str) -> dict:
        calls.append(pages)
        return {"markdown": f"# p{pages}\n内容", "content_list": None, "images": [], "error": None}

    monkeypatch.setattr(parser, "_extract", fake_extract)
    return parser, calls


def test_parse_priority_exhausted_continues(fake_db, tmp_path, monkeypatch):
    """优先 1000 页用完：不中断，继续解析（排队语义）。"""
    parser, calls = _mk_parser(tmp_path, monkeypatch, quota_pages=settings.daily_quota_pages)
    result = parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    assert not result["errors"]
    assert result["pages_used"] == 60
    assert len(calls) == 3  # 60 页 / 25 页一批 = 3 批
    assert result["files_reserved"] == 1


def test_parse_file_limit_exhausted_aborts(fake_db, tmp_path, monkeypatch):
    """文件数满：中断，且不调 API、不占名额。"""
    parser, calls = _mk_parser(tmp_path, monkeypatch, quota_files=settings.daily_file_limit)
    result = parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    assert any("file_limit_exceeded" in e for e in result["errors"])
    assert calls == []
    assert result["files_reserved"] == 0


def test_parse_resume_does_not_double_count_file(fake_db, tmp_path, monkeypatch):
    """中断后续跑：books.quota_files=1 → 不再占用新文件名额。"""
    parser, calls = _mk_parser(tmp_path, monkeypatch)
    r1 = parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    assert r1["files_reserved"] == 1
    files_after_first = QuotaManager(tmp_path / "quota.json").files_used_today()

    r2 = parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    assert r2["files_reserved"] == 1
    assert QuotaManager(tmp_path / "quota.json").files_used_today() == files_after_first


def test_parse_all_cached_no_file_count(fake_db, tmp_path, monkeypatch):
    """全缓存命中：不调 API、文件数不增加（缓存续跑零成本）。"""
    parser, calls = _mk_parser(tmp_path, monkeypatch)
    parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    files_after = QuotaManager(tmp_path / "quota.json").files_used_today()

    calls.clear()
    r2 = parser.parse_book(1, str(tmp_path / "test.pdf"), 60, "测试书")
    assert r2["skipped_cached"] == 3
    assert calls == []
    assert QuotaManager(tmp_path / "quota.json").files_used_today() == files_after


# ── /api/quota 接口 ───────────────────────────────────


def test_api_quota_fields(fake_db):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/quota")
        assert r.status_code == 200
        d = r.json()
        # 新双维度字段
        assert d["daily_priority_pages"] == settings.daily_quota_pages
        assert d["priority_used"] >= 0
        assert d["priority_remaining"] >= 0
        assert "priority_exhausted" in d
        assert d["daily_file_limit"] == settings.daily_file_limit
        assert d["files_used"] >= 0
        assert d["files_remaining"] >= 0
        # 兼容旧字段
        assert d["daily_limit"] == settings.daily_quota_pages
        assert "used" in d and "remaining" in d
