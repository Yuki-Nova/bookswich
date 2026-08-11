"""解析质检报告 + 按章对比 测试（2026-08-11）。

覆盖：
- build_compare_report：章节数 / 表格门禁原因分布（converted/kept/reasons）/
  图片缺失清单 / 质检警告 / raw vs rebuilt 体积
- build_chapter_diff：行级 diff（eq 合并计数 / del / add）
- 路由：GET /api/books/{id}/compare、/compare/chapter/{n}（404/400）
"""
import json
from pathlib import Path

import pytest

from app.config import settings
from app.services import compare

# 门禁通过的表（2 列 2 行规整）+ 被拦的表（含 colspan → merged）
TABLE_OK = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
TABLE_MERGED = '<table><tr><td colspan="2">A</td></tr><tr><td>1</td><td>2</td></tr></table>'


@pytest.fixture
def fake_book(tmp_path, monkeypatch):
    """临时 data_dir：1 本 1 章教材（1 批 md + 2 表 + 2 图引用 + 节编号不连续）。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    md_dir = tmp_path / "md" / "b1_测试教材"
    (md_dir / "images").mkdir(parents=True)
    (md_dir / "images" / "a.jpg").write_bytes(b"img")
    (md_dir / "batch_01_p1-25.md").write_text(
        "第1章 绪论\n旧内容A\n" + TABLE_OK + "\n图1 ![](images/a.jpg)\n删除行\n",
        encoding="utf-8",
    )

    build_dir = tmp_path / "build" / "b1_测试教材"
    build_dir.mkdir(parents=True)
    structure = {
        "book": "测试教材",
        "pages_covered": "p1-25",
        "pre_matter_chars": 0,
        "skipped_orphans": ["孤儿标题X"],
        "chapters": [
            {
                "title": "第1章 绪论",
                "level": 1,
                "page_range": "p1-25",
                "lines": [
                    "第1章 绪论",
                    TABLE_OK,
                    TABLE_MERGED,
                    "图1 ![](images/a.jpg)",
                    "图2 ![](images/missing.jpg)",
                ],
                "char_count": 120,
                "image_count": 2,
                "table_count": 2,
                "children": [
                    {"title": "第1节 甲", "level": 2, "page_range": "p1-25",
                     "lines": ["第1节 甲", "正文"], "char_count": 10,
                     "image_count": 0, "table_count": 0, "children": [], "board": False},
                    {"title": "第3节 丙", "level": 2, "page_range": "p1-25",
                     "lines": ["第3节 丙", "正文"], "char_count": 10,
                     "image_count": 0, "table_count": 0, "children": [], "board": False},
                ],
                "board": False,
            }
        ],
    }
    (build_dir / "structure.json").write_text(
        json.dumps(structure, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


# ── 质检报告 ─────────────────────────────────────────


def test_compare_report_structure(fake_book):
    r = compare.build_compare_report(1, "测试教材")
    assert r["book"] == "测试教材"
    assert r["pages_covered"] == "p1-25"
    assert r["chapter_count"] == 1
    assert r["chapters"][0]["no"] == 1
    assert r["chapters"][0]["title"] == "第1章 绪论"
    assert r["raw_chars"] > 0 and r["rebuilt_chars"] > 0


def test_compare_report_table_gates(fake_book):
    """表格门禁统计：1 转 + 1 保（merged），原因分布正确。"""
    r = compare.build_compare_report(1, "测试教材")
    t = r["tables"]
    assert t["converted"] == 1
    assert t["kept"] == 1
    assert t["reasons"].get("merged") == 1
    # 章节级表格统计一致
    assert r["chapters"][0]["tables"]["converted"] == 1
    assert r["chapters"][0]["tables"]["kept"] == 1


def test_compare_report_image_missing(fake_book):
    """图片统计：2 引用，missing.jpg 缺失列入清单。"""
    r = compare.build_compare_report(1, "测试教材")
    assert r["images"]["referenced"] == 2
    assert "images/missing.jpg" in r["images"]["missing"]
    assert "images/a.jpg" not in r["images"]["missing"]


def test_compare_report_warnings_orphans(fake_book):
    """节编号不连续 → 警告；孤儿标题列出。"""
    r = compare.build_compare_report(1, "测试教材")
    assert any("节编号不连续" in w for w in r["warnings"])
    assert "孤儿标题X" in r["orphans"]


def test_compare_report_missing_structure(tmp_path, monkeypatch):
    """structure.json 缺失 → FileNotFoundError。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "md" / "b1_x").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        compare.build_compare_report(1, "x")


# ── 按章 diff ────────────────────────────────────────


def test_chapter_diff_types(fake_book):
    """diff 含 eq（合并计数）/ del / add 三类。"""
    d = compare.build_chapter_diff(1, "测试教材", 1)
    assert d["chapter"] == 1
    assert d["title"] == "第1章 绪论"
    types = {item["t"] for item in d["diff"]}
    assert "eq" in types and "del" in types and "add" in types
    # eq 块带计数
    eq = next(x for x in d["diff"] if x["t"] == "eq")
    assert eq["n"] >= 1
    # raw 的「删除行」出现在 del（rebuilt 无此行）
    dels = [x["a"] for x in d["diff"] if x["t"] == "del"]
    assert any("删除行" in s for s in dels)


def test_chapter_diff_out_of_range(fake_book):
    with pytest.raises(ValueError):
        compare.build_chapter_diff(1, "测试教材", 99)


# ── 章节 markdown（并排预览数据源）─────────────────────


def test_chapter_markdown(fake_book):
    """as=markdown 返回 rebuilt 单章原文，含章节标题。"""
    d = compare.chapter_markdown(1, "测试教材", 1)
    assert d["chapter"] == 1
    assert d["title"] == "第1章 绪论"
    assert d["page_range"] == "p1-25"
    assert "第1章 绪论" in d["markdown"]
    assert "图1" in d["markdown"]


def test_chapter_markdown_out_of_range(fake_book):
    with pytest.raises(ValueError):
        compare.chapter_markdown(1, "测试教材", 99)


# ── 路由 ─────────────────────────────────────────────


def test_compare_routes(fake_book):
    from app.db import init_db, get_conn

    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status) VALUES ('测试教材', 25, 'structure_ok')"
        )

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/books/1/compare")
        assert r.status_code == 200
        body = r.json()
        assert body["chapter_count"] == 1
        assert body["tables"]["converted"] == 1

        r2 = c.get("/api/books/1/compare/chapter/1")
        assert r2.status_code == 200
        assert r2.json()["chapter"] == 1

        # as=markdown 返回 rebuilt 原文
        r3 = c.get("/api/books/1/compare/chapter/1?as=markdown")
        assert r3.status_code == 200
        assert "markdown" in r3.json()
        assert "第1章 绪论" in r3.json()["markdown"]

        assert c.get("/api/books/999/compare").status_code == 404
        assert c.get("/api/books/1/compare/chapter/99").status_code == 400


def test_pdf_route(fake_book):
    """GET /api/books/{id}/pdf 返回原始 PDF；无 raw_path 404。"""
    from app.db import init_db, get_conn

    init_db()
    raw_dir = settings.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    pdf_file = raw_dir / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, raw_path, parse_status) "
            "VALUES ('测试教材', 25, ?, 'structure_ok')",
            (str(pdf_file),),
        )

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/books/1/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

        # 无 raw_path 的书
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO books (title, page_count, parse_status) "
                "VALUES ('无PDF', 10, 'structure_ok')"
            )
        assert c.get("/api/books/2/pdf").status_code == 404
        assert c.get("/api/books/999/pdf").status_code == 404


def test_media_route(fake_book):
    """GET /api/books/{id}/media/... 返回 md 内图片；路径穿越/缺失 400/404。"""
    from app.db import init_db, get_conn

    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO books (title, page_count, parse_status) VALUES ('测试教材', 25, 'structure_ok')"
        )

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/books/1/media/images/a.jpg")
        assert r.status_code == 200
        assert r.content == b"img"

        assert c.get("/api/books/1/media/images/nope.jpg").status_code == 404
        # 路径穿越（URL 编码 %2e%2e，避免客户端规范化）
        assert c.get("/api/books/1/media/%2e%2e/batch_01_p1-25.md").status_code == 400
        assert c.get("/api/books/999/media/images/a.jpg").status_code == 404
