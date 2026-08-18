"""C5: 后端可定位错误日志测试（2026-08-18）。

验证解析/导出关键路径确实记录「可定位」日志（带 book_id / 批次 / 页区间），
保证服务端出现问题时能按日志定位到教材与环节，而不只是客户端一个 400。

用 caplog 捕获 app.services.mineru_client / app.api.routes 的日志输出。
"""
import logging
from pathlib import Path

from app.db import get_conn, init_db


def _fresh_env(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    init_db()
    return tmp_path


def test_parse_book_logs_start_and_done(tmp_path, monkeypatch, caplog):
    """parse_book 记录「parse start」（带 book 上下文）与「parse done」汇总。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")

    def fake_extract(self, pdf_path, pages):
        return {"markdown": "# 内容\n正文", "content_list": [], "images": [], "error": None}

    monkeypatch.setattr(MineruParser, "_extract", fake_extract)
    monkeypatch.setattr("app.services.mineru_client.settings.parse_batch_size", 25)

    with caplog.at_level(logging.INFO, logger="app.services.mineru_client"):
        r = MineruParser().parse_book(7, str(pdf), total_pages=10, book_title="日志书")

    assert r["errors"] == []
    # parse start 带 book=7 与页数/批次数，可定位
    start = [rec.getMessage() for rec in caplog.records if "parse start" in rec.getMessage()]
    assert start, "应记录 parse start 日志"
    assert "book=7" in start[0] and "pages=10" in start[0]
    # parse done 汇总
    done = [rec.getMessage() for rec in caplog.records if "parse done" in rec.getMessage()]
    assert done and "book=7" in done[0]


def test_parse_book_logs_batch_failure_with_book_id(tmp_path, monkeypatch, caplog):
    """批次解析失败时，日志含 book_id 与批次/页区间（可定位到具体批次）。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")

    def biz_fail(self, pdf_path, pages):
        return {"markdown": None, "content_list": None, "images": [], "error": "server-side boom"}

    monkeypatch.setattr(MineruParser, "_extract", biz_fail)

    with caplog.at_level(logging.ERROR, logger="app.services.mineru_client"):
        r = MineruParser().parse_book(3, str(pdf), total_pages=10, book_title="日志书")

    assert r["errors"] and "server-side" in r["errors"][0]
    err_records = [rec.getMessage() for rec in caplog.records
                   if rec.levelno >= logging.ERROR and "server-side boom" in rec.getMessage()]
    assert err_records, "应记录批次错误日志"
    assert "book=3" in err_records[0]
    assert "batch 1 (p1-10)" in err_records[0]  # 页区间可定位


def test_parse_book_logs_warning_when_errors(tmp_path, monkeypatch, caplog):
    """存在错误时记录 parse finished warning 级汇总（含错误数/首个错误）。"""
    from app.services.mineru_client import MineruParser

    tmp = _fresh_env(tmp_path, monkeypatch)
    pdf = tmp / "book.pdf"
    pdf.write_bytes(b"%PDF")

    def biz_fail(self, pdf_path, pages):
        return {"markdown": None, "content_list": None, "images": [], "error": "nope"}

    monkeypatch.setattr(MineruParser, "_extract", biz_fail)

    with caplog.at_level(logging.WARNING, logger="app.services.mineru_client"):
        r = MineruParser().parse_book(5, str(pdf), total_pages=10, book_title="日志书")

    warn = [rec.getMessage() for rec in caplog.records if "parse finished" in rec.getMessage()]
    assert warn, "有错误时应记录 parse finished 汇总 warning"
    assert "book=5" in warn[0] and "errors=1/1 batches" in warn[0]
