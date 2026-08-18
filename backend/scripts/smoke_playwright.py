"""C3 + C5 生产冒烟（2026-08-18）。

Playwright（复用系统 Edge，channel=\"msedge\"）对生产站 bookswich.yukinova.top 做核心流程冒烟，
并在 C5 基础上**收集 console error / pageerror / HTTP 5xx** 并断言为零：

  C3 流程：
    1. 首页（登录页）正常渲染
    2. 错误密码 → 报错
    3. 正确密码登录 → 主界面渲染（教材列表加载，服务器真实数据）
    4. token 存 localStorage、刷新后登录态保持
    5. 打开一本教材 → workspace 切换、无页面崩溃
  C5 门禁：
    - console error = 0
    - pageerror    = 0
    - HTTP 5xx     = 0

用法（backend/ 目录，.venv 内）：
    $env:BOOKSWICH_WEB_PASS='xxxx'
    .venv\\Scripts\\python.exe scripts/smoke_playwright.py [--url https://bookswich.yukinova.top] [--headful]

退出码：0 = 冒烟通过（含零 console error / pageerror / 5xx）；1 = 任一阶段失败；
2 = 环境/参数错误（未设密码等）。

安全：密码只从环境变量 BOOKSWICH_WEB_PASS 读取，不写入脚本/日志/截图。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_URL = "https://bookswich.yukinova.top"


def main() -> int:
    ap = argparse.ArgumentParser(description="bookswich 生产冒烟（C3+C5）")
    ap.add_argument("--url", default=DEFAULT_URL, help="目标站点")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口（默认 headless）")
    ap.add_argument("--shots", default="export/shots", help="截图输出目录（相对项目根）")
    args = ap.parse_args()

    web_pass = os.environ.get("BOOKSWICH_WEB_PASS", "")
    if not web_pass:
        print("[smoke] 未设置环境变量 BOOKSWICH_WEB_PASS（登录密码），无法冒烟。", file=sys.stderr)
        return 2

    # 项目根（backend/scripts/smoke_playwright.py -> bookswich/）
    root = Path(__file__).resolve().parents[2]
    shots = (root / args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    # C5：收集三类运行时信号
    console_errors: list[str] = []
    page_errors: list[str] = []
    http_5xx: list[str] = []
    # 透明的「已知认证 401」：登录探活/错误密码/会话校验等本就返回 401（浏览器把响应码
    # 记为 console error 属预期）。单独归类、在报告里显式列出，不计入硬失败，但绝不静默。
    known_auth_401: list[str] = []

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = ""):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    # 401 响应在 console 中表现为 "Failed to load resource: ... 401"（认证流程设计内）
    AUTH_401_CONSOLE = "401 (Unauthorized)"

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not args.headful)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()

        # —— 挂钩三类运行时信号 ——
        def on_console(msg):
            if msg.type != "error":
                return
            if AUTH_401_CONSOLE in msg.text:
                known_auth_401.append(msg.text)
            else:
                console_errors.append(msg.text)

        page.on("console", on_console)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("response", lambda r: http_5xx.append(f"{r.status} {r.url}")
                if r.status >= 500 else None)

        try:
            # 1. 首页渲染（登录页）
            page.goto(args.url, wait_until="load", timeout=30000)
            page.wait_for_selector(".login-card", timeout=15000)
            record("首页登录页渲染", True)

            # 2. 错误密码 → 报错提示
            page.fill("input[type='password']", "wrong-pass-example")
            page.click("button[type='submit']")
            page.wait_for_selector(".login-error", timeout=8000)
            err_text = page.text_content(".login-error") or ""
            record("错误密码提示", bool(err_text.strip()), err_text.strip()[:40])

            # 3. 正确密码登录 → 主界面
            page.fill("input[type='password']", web_pass)
            page.click("button[type='submit']")
            page.wait_for_selector(".layout", timeout=15000)
            record("登录成功渲染主界面", True)

            # 4. token 存 localStorage；刷新后登录态保持
            token_ok = page.evaluate("!!localStorage.getItem('bookswich_token')")
            record("token 存 localStorage", bool(token_ok))
            page.reload(wait_until="load")
            page.wait_for_selector(".layout", timeout=15000)
            record("刷新后登录态保持", True)

            # 5. 教材列表加载（服务器真实数据）→ 打开第一本
            page.wait_for_selector(".book-row", timeout=15000)
            if page.locator(".book-row").count() > 0:
                page.locator(".book-row").first.click(timeout=8000)
                page.wait_for_timeout(2500)  # 等 workspace 渲染 + 请求返回
                record("打开教材进入 workspace", True)
            else:
                record("打开教材进入 workspace", False, "未找到教材列表项")

            page.screenshot(path=str(shots / "c5-smoke-home.png"), full_page=False)

        except Exception as exc:  # noqa: BLE001
            page.screenshot(path=str(shots / "c5-smoke-fail.png"), full_page=False)
            record("冒烟执行未中断到结尾", False, f"{type(exc).__name__}: {exc}")
        finally:
            ctx.close()
            browser.close()

    # —— 汇总 ——
    print("\n=== C5 运行时信号收集 ===")
    bad = False
    print(f"  console error × {len(console_errors)}", "→ " + str(console_errors[:3]) if console_errors else "")
    bad |= bool(console_errors)
    print(f"  pageerror     × {len(page_errors)}", "→ " + str(page_errors[:3]) if page_errors else "")
    bad |= bool(page_errors)
    print(f"  HTTP 5xx      × {len(http_5xx)}", "→ " + str(http_5xx[:3]) if http_5xx else "")
    bad |= bool(http_5xx)
    if known_auth_401:
        print(f"  （已归类未计）已知认证 401 × {len(known_auth_401)}"
              " — 认证流程设计内响应，非事故，见下方明细")
        for i, m in enumerate(known_auth_401[:3], 1):
            print(f"      {i}. {m}")
    else:
        print("  （已归类未计）已知认证 401 × 0")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n[smoke] 阶段通过 {len(results) - len(failed)}/{len(results)}；"
          f"console/pageerror/5xx 全零={'是' if not bad else '否'}")
    if failed or bad:
        print("[smoke] 冒烟未通过。", file=sys.stderr)
        return 1
    print("[smoke] 冒烟通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
