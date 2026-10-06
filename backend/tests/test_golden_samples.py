"""C4 黄金样本回归测试（2026-08-18；2026-10-06 加固）。

校验本地教材结构重建 = 固化基线（scripts/golden_samples.py 生成）；
基线不存在或结构退化时测试失败，提醒重跑 --update 确认。

2026-10-06 两处加固：

1. **子进程显式注入 UTF-8 环境变量 + 允许替换非法字节**。原先只给父进程指定
   `encoding="utf-8"`，而子进程 stdout 是管道、按系统 ANSI 代码页编码中文
   （本机 cp936），解码失败发生在 subprocess 自己的 reader 线程里，异常被吞成
   `PytestUnhandledThreadExceptionWarning`，于是 `r.stdout` 变成 `None`，
   最后报 `TypeError: argument of type 'NoneType' is not iterable`——
   真正的编码原因被完全掩盖。实测：不设 `PYTHONIOENCODING` 时本用例必失败。
2. **本地 build 产物为空时跳过校验**。清空 `data/` 后 `golden_samples.py` 采集到
   0 本样本，原先会打印「通过 0/0」并 exit 0，校验形同虚设而测试照旧绿灯。
   现在改为 `pytest.skip`，并在脚本侧把「无样本」变成显式的未执行状态。
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def golden_baseline_exists():
    """基线 JSON 存在性；缺失则跳过（首次需先 --update）。"""
    from app.config import settings

    if not (settings.data_dir / "build_golden_samples.json").exists():
        pytest.skip("黄金样本基线缺失，先跑 scripts/golden_samples.py --update")


@pytest.fixture(scope="module")
def golden_local_samples():
    """本地 build 产物存在才做校验；data/build 为空时跳过，避免「假通过」。"""
    from app.config import settings

    build_dir = settings.build_dir
    has_sample = build_dir.is_dir() and any(
        (d / "structure.json").is_file() for d in build_dir.iterdir()
    )
    if not has_sample:
        pytest.skip("本地无 build 产物（data/build 为空），跳过黄金样本校验")


def test_golden_samples_verify_ok(golden_baseline_exists, golden_local_samples):
    """scripts/golden_samples.py 校验应通过（结构无退化）。"""
    py = BACKEND / ".venv" / "Scripts" / "python.exe"
    # 子进程 stdout 是管道：不注入 PYTHONIOENCODING 时中文按系统 ANSI 代码页输出，
    # 父进程按 utf-8 解码即失败（详见模块 docstring 第 1 条）。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run(
        [str(py), "scripts/golden_samples.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(BACKEND), env=env,
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
