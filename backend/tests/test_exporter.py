"""exporter 导出逻辑正式单测（pytest）。

运行：cd backend && .venv\Scripts\python -m pytest

v4 策略：表格保留 MinerU 原样（纯排版换行），公式定界符规范化。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.services.exporter import (
    export_obsidian_zip,
    export_rebuilt,
    export_zip,
    format_html_table,
    normalize_math,
)

BOOK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "md" / "b1_医药应用概率统计"
# ── 公式规范化 ─────────────────────────────────────────


def test_normalize_inline_math():
    assert normalize_math("均值 $ \\overline { x } $ 记为") == "均值 $\\overline { x }$ 记为"


def test_normalize_block_math():
    """块级公式保持 $$ 独占行格式（Typora 标准块级公式）。"""
    assert normalize_math("$$\n P ( X = k ) = p ^ { k } \n$$") == "$$\nP ( X = k ) = p ^ { k }\n$$"


def test_normalize_block_math_single_line():
    """同行块级公式也规范化为多行格式。"""
    assert normalize_math("$$ 公式 $$") == "$$\n公式\n$$"


def test_normalize_no_double_strip():
    """定界符内侧去空格，公式内部空格保留。"""
    out = normalize_math("$P ( A + B ) = P ( A ) + P ( B )$")
    assert out == "$P ( A + B ) = P ( A ) + P ( B )$"


def test_normalize_latex_delimiters():
    """公式内混入的 \\( \\) LaTeX 定界符 → 转普通括号（MathJax 数学模式不认）。"""
    assert normalize_math("$P(a\\( \\int_{-\\infty}^{x}f(t)dt$") == "$P(a( \\int_{-\\infty}^{x}f(t)dt$"


def test_normalize_adjacent_math_spaces():
    """相邻行内公式间多余空格压平：$A$  $B$ → $A$ $B$；$$ 块级不受影响。"""
    assert normalize_math("$A$  $B$ 相邻") == "$A$ $B$ 相邻"
    # 块级公式（$$ 独占行）不被压平破坏
    block = "$$\nE(X) = 1\n$$"
    assert normalize_math(block) == block


# ── 表格保留原样 ───────────────────────────────────────


def test_table_html_kept():
    """HTML 表格原样保留（语义不变），仅排版换行。"""
    tbl = "<table><tr><td>X</td><td>0</td></tr><tr><td>P</td><td>q</td></tr></table>"
    out = format_html_table(tbl)
    assert "<table>" in out and "</table>" in out
    assert "<td>X</td>" in out and "<td>q</td>" in out  # 标签完整
    assert out.count("\n") >= 2     # 有换行


def test_table_no_long_single_line():
    """表格换行后无超长单行（CodeMirror/Typora 性能）。"""
    long_tbl = "<table>" + "".join(
        f"<tr><td>cell_{i}</td><td>{'x' * 300}</td></tr>" for i in range(50)
    ) + "</table>"
    out = format_html_table(long_tbl)
    assert max(len(l) for l in out.splitlines()) < 1000


def test_full_export_tables_kept(rebuilt_full):
    """全书导出：HTML 表格保留（<table> 存在），且无超长单行。"""
    lines = rebuilt_full.splitlines()
    assert any(l.strip().startswith("<table") for l in lines)
    assert max(len(l) for l in lines) <= 2000, max(len(l) for l in lines)


def test_full_export_math_normalized(rebuilt_full):
    """全书导出：行内公式"开始符后空格"（`$ P` 形式）已消除。

    注：公式结束符后的空格（`$d$ 是指`）合法，Typora 可识别，不检查。
    """
    import re

    bad = [l[:70] for l in rebuilt_full.splitlines() if re.search(r"(?<=\s)\$ (?=\S)", l)]
    assert not bad, bad[:5]


# ── 结构/章节 ──────────────────────────────────────────


def test_full_export_distribution_table_region(rebuilt_full):
    """分布律表区域：规整表格门禁通过 → Markdown（公式可渲染）。"""
    ls = rebuilt_full.splitlines()
    idx = next(i for i, l in enumerate(ls) if "分布律还可表示为下列表形式" in l)
    seg = "\n".join(ls[idx : idx + 30])
    assert "| X |" in seg            # 表格已转 Markdown
    assert "| --- |" in seg          # 分隔行存在
    assert "其中 $p_{k}" in seg


# ── OSS 外链模式（图片转外链）────────────────────────────────


def _fake_uploader_cls(calls: list):
    """返回一个假 OssImageUploader：upload_many 记录调用并返回固定 URL 映射。"""

    class FakeUploader:
        def __init__(self) -> None:
            pass

        def upload_many(self, items: list[tuple[str, Path]]) -> tuple[dict[str, str], list[str]]:
            calls.extend(items)
            return {key: "https://obs.example.com/" + key for key, _ in items}, []

    return FakeUploader


@pytest.fixture(scope="module")
def oss_build_exists():
    """b1 结构重建产物存在性（OSS 模式测试依赖真实教材数据）。"""
    if not (
        BOOK_DIR.parent.parent / "build" / "b1_医药应用概率统计" / "structure.json"
    ).exists():
        pytest.skip("structure.json 不存在，跳过 OSS 模式测试")


def test_obsidian_oss_mode_rewrites_urls(oss_build_exists, monkeypatch):
    """obsidian 版 oss 模式：md 图片引用改为 OSS URL，zip 不含 images/。"""
    import io
    import zipfile

    calls: list = []
    monkeypatch.setattr(
        "app.services.oss_images.OssImageUploader", _fake_uploader_cls(calls)
    )
    data = export_obsidian_zip(1, "医药应用概率统计", image_mode="oss")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert not any("/images/" in n for n in names), "oss 模式 zip 不应含 images/ 条目"
        md_names = [n for n in names if n.endswith(".md")]
        assert len(md_names) >= 2, "应含 00_总览 + 至少一章"
        for n in md_names:
            text = zf.read(n).decode("utf-8")
            assert "(images/" not in text, f"{n} 仍含相对图片引用"
            if "obs.example.com" in text:
                assert "https://obs.example.com/医药应用概率统计/images/" in text
    assert calls, "应触发图片上传"
    assert all(k.startswith("医药应用概率统计/images/") for k, _ in calls)


def test_export_zip_oss_mode_no_images(oss_build_exists, monkeypatch):
    """整本导出 oss 模式：zip 只含 1 个 md（无 images/），md 内为 OSS URL。"""
    import io
    import zipfile

    calls: list = []
    monkeypatch.setattr(
        "app.services.oss_images.OssImageUploader", _fake_uploader_cls(calls)
    )
    text = export_rebuilt(1, "医药应用概率统计")
    data = export_zip(1, "医药应用概率统计", text, "医药应用概率统计.md", image_mode="oss")

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert len(names) == 1 and names[0].endswith(".md"), "oss 模式整本 zip 只应含 md"
        body = zf.read(names[0]).decode("utf-8")
        assert "(images/" not in body
        assert "https://obs.example.com/医药应用概率统计/images/" in body
    assert calls


def test_invalid_image_mode_raises():
    """非法 image_mode 抛 ValueError（在任何 I/O 之前）。"""
    with pytest.raises(ValueError):
        export_obsidian_zip(1, "x", image_mode="weird")
    with pytest.raises(ValueError):
        export_zip(1, "x", "md", "x.md", image_mode="weird")


def test_oss_uploader_requires_config(monkeypatch):
    """OSS 未配置时 OssImageUploader 构造抛 RuntimeError（不静默产生坏链接）。"""
    from app.services.oss_images import OssImageUploader

    monkeypatch.setattr(settings, "oss_access_key_id", "")
    monkeypatch.setattr(settings, "oss_access_key_secret", "")
    with pytest.raises(RuntimeError):
        OssImageUploader()
