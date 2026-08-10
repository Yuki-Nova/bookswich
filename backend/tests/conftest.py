"""pytest 共享 fixtures。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.exporter import export_rebuilt

BOOK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "md" / "b1_医药应用概率统计"


@pytest.fixture(scope="module")
def rebuilt_full():
    """全书导出（需要结构重建产物存在；缺失则跳过）。"""
    if not (BOOK_DIR.parent.parent / "build" / "b1_医药应用概率统计" / "structure.json").exists():
        pytest.skip("structure.json 不存在，跳过全书导出测试")
    return export_rebuilt(1, "医药应用概率统计")
