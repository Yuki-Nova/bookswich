"""无章节兜底导出 + 文件名安全化 正式测试。

覆盖（2026-08-11 代码体检批次 + 生产问题 2）：
- 无章节兜底：structure.json 缺失或 chapters 为空 → 整本一个「全文」章节，不再报错
- _safe_stem：上传/导出文件名安全化（zip slip / Windows 非法字符）
- export_zip：md_name 内部防御性 sanitize
"""
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.config import settings
from app.api.routes import _safe_stem
from app.services.exporter import export_obsidian_zip, export_zip


@pytest.fixture
def fake_book(tmp_path, monkeypatch):
    """临时 data_dir：1 本无章节教材（2 批 md + 1 张图）。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    md_dir = tmp_path / "md" / "b1_测试论文"
    (md_dir / "images").mkdir(parents=True)
    (md_dir / "images" / "a.jpg").write_bytes(b"fakeimg")
    (md_dir / "batch_01_p1-10.md").write_text(
        "# 标题\n\n摘要内容 ![](images/a.jpg)\n", encoding="utf-8"
    )
    (md_dir / "batch_02_p11-20.md").write_text(
        "# 第二节\n\n更多内容\n", encoding="utf-8"
    )
    return tmp_path


def _write_empty_structure(tmp_path: Path) -> None:
    """写空章节 structure.json（模拟无编号教材重建结果）。"""
    build_dir = tmp_path / "build" / "b1_测试论文"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "structure.json").write_text(
        json.dumps({"book": "测试论文", "pages_covered": "p1-20", "chapters": []}),
        encoding="utf-8",
    )


# ── 无章节兜底 ────────────────────────────────────────


def test_obsidian_zip_fallback_empty_chapters(fake_book):
    """chapters 为空（无编号教材）：整本一个「全文」章节，不再抛 ValueError。"""
    _write_empty_structure(fake_book)
    data = export_obsidian_zip(1, "测试论文", image_mode="local")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "测试论文/01_全文/全文.md" in names
        assert "测试论文/00_总览.md" in names
        # MOC 链接规范
        assert "[[01_全文/全文|全文]]" in zf.read("测试论文/00_总览.md").decode("utf-8")
        # 正文 = 批次合并内容
        body = zf.read("测试论文/01_全文/全文.md").decode("utf-8")
        assert "摘要内容" in body and "更多内容" in body
        # local 模式图片按引用打包
        assert "测试论文/01_全文/images/a.jpg" in names


def test_obsidian_zip_fallback_missing_structure(fake_book):
    """structure.json 缺失（未跑重建）：同样走全文兜底，不再 FileNotFoundError。"""
    data = export_obsidian_zip(1, "测试论文", image_mode="local")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "测试论文/01_全文/全文.md" in names
        body = zf.read("测试论文/01_全文/全文.md").decode("utf-8")
        assert "摘要内容" in body


def test_obsidian_zip_fallback_oss_mode(fake_book, monkeypatch):
    """无章节 + oss 模式：zip 只含文本，md 引用为 OSS URL（vault 纯文本化一致）。"""
    _write_empty_structure(fake_book)

    class FakeUploader:
        def __init__(self) -> None:
            pass

        def upload_many(self, items: list[tuple[str, Path]]) -> tuple[dict[str, str], list[str]]:
            return {key: "https://obs.example.com/" + key for key, _ in items}, []

    monkeypatch.setattr("app.services.oss_images.OssImageUploader", FakeUploader)
    data = export_obsidian_zip(1, "测试论文", image_mode="oss")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert not any("/images/" in n for n in names)
        body = zf.read("测试论文/01_全文/全文.md").decode("utf-8")
        assert "(images/" not in body
        assert "https://obs.example.com/测试论文/images/a.jpg" in body


# ── 文件名安全化（_safe_stem）─────────────────────────


def test_safe_stem_zip_slip():
    """路径穿越文件名：只保留 basename，/ 与 \\ 不构成路径。"""
    assert _safe_stem("..\\..\\evil.pdf") == "evil"
    assert _safe_stem("C:/x/y/第1章 绪论.pdf") == "第1章 绪论"
    assert _safe_stem("../第1章.md") == "第1章"


def test_safe_stem_illegal_chars():
    """Windows 非法字符替换为 _，首尾下划线 strip。"""
    assert _safe_stem("a:b*c?.pdf") == "a_b_c"
    assert _safe_stem(":::.pdf") == "unnamed"  # 全非法 → fallback


def test_safe_stem_normal():
    """正常中文/英文文件名不受影响。"""
    assert _safe_stem("医药应用概率统计.pdf") == "医药应用概率统计"
    assert _safe_stem("paper2024.pdf") == "paper2024"


# ── export_zip md_name 防御性 sanitize ────────────────


def test_export_zip_sanitizes_md_name(fake_book):
    """md_name 含路径分隔符：zip 内无 ../ 与分隔符（防 zip slip 双保险）。"""
    md = "# 测试\n\n正文,无图片引用\n"
    data = export_zip(1, "测试论文", md, "../evil.md", image_mode="local")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert len(names) == 1
        assert not any("/" in n or "\\" in n or n.startswith("..") for n in names)
        assert zf.read(names[0]).decode("utf-8") == md
