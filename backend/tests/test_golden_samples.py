"""C4 黄金样本回归测试（2026-08-18）。

校验本地教材结构重建 = 固化基线（scripts/golden_samples.py 生成）；
基线不存在或结构退化时测试失败，提醒重跑 --update 确认。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def golden_baseline_exists():
    """基线 JSON 存在性；缺失则跳过（首次需先 --update）。"""
    from app.config import settings

    if not (settings.data_dir / "build_golden_samples.json").exists():
        pytest.skip("黄金样本基线缺失，先跑 scripts/golden_samples.py --update")


def test_golden_samples_verify_ok(golden_baseline_exists):
    """scripts/golden_samples.py 校验应通过（结构无退化）。"""
    py = BACKEND / ".venv" / "Scripts" / "python.exe"
    r = subprocess.run(
        [str(py), "scripts/golden_samples.py"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(BACKEND),
    )
    assert r.returncode == 0, f"黄金样本退化: {r.stdout}\n{r.stderr}"
    assert "通过" in r.stdout


def test_golden_baseline_has_local_books(golden_baseline_exists):
    """基线至少覆盖本地真实教材。"""
    from app.config import settings

    bl = json.loads((settings.data_dir / "build_golden_samples.json").read_text(encoding="utf-8"))
    assert bl, "基线为空"
    # 至少有一本章节数 > 0 的真实教材
    assert any(v["chapter_count"] > 0 for v in bl.values())