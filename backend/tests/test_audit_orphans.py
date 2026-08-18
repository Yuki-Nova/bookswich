"""B3: 文件生命周期 & 孤儿产物审计逻辑测试（2026-08-18）。

覆盖 audit_orphans 的核心判定（纯函数，不碰磁盘删除）：
- DB 与磁盘目录差异：磁盘有 build/md 目录但 DB 无记录 → 孤儿
- DB 有记录但磁盘目录缺失 → 记录完整性损坏（可感知，不是孤儿）
- images/ 残留图未被任何 batch 引用 → 孤儿文件
- batch 文件与 content_list 图片引用：缺图 = 缓存不完整（不删，需重跑）
- 删除安全：dry-run 不删任何文件；清理只删明确孤儿
"""
import pytest

from app.services import audit_orphans as ao


def _path_set(items):
    return {p.as_posix() for p in items}


# ── DB vs 磁盘差异 ─────────────────────────────────

def make_scanner(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    # 目录结构：raw/, md/b1_a/, build/b1_a/, build/b2_b/（b2 无 DB 记录）
    (tmp_path / "raw").mkdir(parents=True)
    (tmp_path / "md" / "b1_a").mkdir(parents=True)
    (tmp_path / "build" / "b1_a").mkdir(parents=True)
    (tmp_path / "build" / "b2_b").mkdir(parents=True)
    return settings


def test_db_dir_diff(tmp_path, monkeypatch):
    """磁盘 build/b2_b 无 DB 记录 → 孤儿；build/b1_a 有记录 → 正常。"""
    settings = make_scanner(tmp_path, monkeypatch)
    db_dirs = {"b1_a"}  # 模拟 DB 只有 b1_a
    loc = ao.scan_dir_diff(settings, db_dirs)
    assert loc["orphan_build"] == [tmp_path / "build" / "b2_b"]
    assert loc["missing_build"] == []  # DB 记录都在
    assert loc["orphan_md"] == []  # 注意 b1_a 是 share 前缀，需精确


def test_db_record_without_dir_reported(tmp_path, monkeypatch):
    """DB 有 b9_x 记录但 build 目录不存在 → missing_build 清单。"""
    settings = make_scanner(tmp_path, monkeypatch)
    db_dirs = {"b1_a", "b9_x"}
    loc = ao.scan_dir_diff(settings, db_dirs)
    assert loc["missing_build"] == [tmp_path / "build" / "b9_x"]


def test_orphan_images(tmp_path, monkeypatch):
    """images/ 里未被任何 batch md 引用的文件 → 孤儿图片。"""
    make_scanner(tmp_path, monkeypatch)
    img_dir = tmp_path / "md" / "b1_a" / "images"
    img_dir.mkdir(parents=True)
    for name in ("used.jpg", "orphan.jpg"):
        (img_dir / name).write_bytes(b"x")
    (img_dir / "orphan.jpg").write_bytes(b"y")
    (tmp_path / "md" / "b1_a" / "batch_01_p1-25.md").write_text(
        "![](images/used.jpg)", encoding="utf-8"
    )
    orp = ao.scan_orphan_images(
        tmp_path / "md", {("b1_a", tmp_path / "md" / "b1_a")}
    )
    assert _path_set(orp) == {(img_dir / "orphan.jpg").as_posix()}


def test_missing_ref_image_not_orphan(tmp_path, monkeypatch):
    """md 引用了但 images/ 缺文件 → 是缺图（需重跑），不是孤儿（不删）。"""
    make_scanner(tmp_path, monkeypatch)
    img_dir = tmp_path / "md" / "b1_a" / "images"
    img_dir.mkdir(parents=True)
    (tmp_path / "md" / "b1_a" / "batch_01_p1-25.md").write_text(
        "![](images/gone.jpg)", encoding="utf-8"
    )
    orp = ao.scan_orphan_images(tmp_path / "md", {("b1_a", tmp_path / "md" / "b1_a")})
    assert (img_dir / "gone.jpg").as_posix() not in _path_set(orp)


def test_dry_run_removes_nothing(tmp_path, monkeypatch, capsys):
    """dry-run 模式审计孤儿图片：打印但磁盘文件保留。"""
    make_scanner(tmp_path, monkeypatch)
    img_dir = tmp_path / "md" / "b1_a" / "images"
    img_dir.mkdir(parents=True)
    f = img_dir / "orphan.jpg"
    f.write_bytes(b"y")
    removed = ao.dry_run_clean_orphan_images(
        tmp_path / "md", {("b1_a", tmp_path / "md" / "b1_a")}
    )
    assert f.exists()  # dry-run 不删
    assert str(f) in removed  # 但列出将删除