"""pytest 共享 fixtures。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.exporter import export_rebuilt

BOOK_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "md" / "b1_医药应用概率统计"


@pytest.fixture(autouse=True)
def _no_auth(monkeypatch):
    """测试环境默认无鉴权（隔离真实 .env 的 web_password/api_token，避免 TestClient 匿名请求被 401 拦截）。

    需要鉴权的测试（如 tests/test_auth.py）在函数内用 monkeypatch 自行重设 web_password/api_token，
    顺序上 autouse 先置空、测试体再覆盖，互不冲突。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "")
    monkeypatch.setattr(settings, "api_token", "")


@pytest.fixture(scope="module")
def rebuilt_full():
    """全书导出（需要结构重建产物存在；缺失则跳过）。"""
    if not (BOOK_DIR.parent.parent / "build" / "b1_医药应用概率统计" / "structure.json").exists():
        pytest.skip("structure.json 不存在，跳过全书导出测试")
    return export_rebuilt(1, "医药应用概率统计")
