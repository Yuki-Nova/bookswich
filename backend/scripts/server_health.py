"""D3 + D4 服务器运维（2026-08-18）。

本地运行，paramiko SSH 到生产服务器，执行：
  D4 部署后健康检查：服务状态 /health /api 认证 / 首页 / vault/WebDAV
  D3 备份清理：app.bak-* 与 dist.bak-* 保留最新 N 份，先列出再删，记录释放空间

用法：
    .venv\\Scripts\\python.exe scripts/server_health.py --check      # D4 健康检查
    .venv\\Scripts\\python.exe scripts/server_health.py --cleanup    # D3 清理（先 dry-run 列出）
    .venv\\Scripts\\python.exe scripts/server_health.py --cleanup --apply  # D3 实际删除
    .venv\\Scripts\\python.exe scripts/server_health.py --check --cleanup --apply  # 全都要

安全：本脚本读取 环境变量 BOOKSWICH_SSH_PASS / BOOKSWICH_WEB_PASS 用于登录与认证探测，
不从 .env 打印任何密码/token。
"""
import argparse
import base64
import os
import sys
from pathlib import Path

import paramiko

HOST = "121.43.153.125"
ROOT = "/www/wwwroot/bookswich"
KEEP = 3  # D3：保留最新 3 份备份


def ssh(passwd):
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username="root", password=passwd, timeout=20)
    return cli


def run(cli, cmd, t=120):
    _, out, err = cli.exec_command(cmd, timeout=t)
    return out.read().decode("utf-8", "replace").strip(), err.read().decode("utf-8", "replace").strip()


def cmd_check(cli, pw, web_pass):
    print("=== D4 部署后健康检查 ===")
    # 1. 服务状态
    o, _ = run(cli, "systemctl is-active bookswich && systemctl is-enabled bookswich")
    print(f"[服务] {o.replace(chr(10), ' active/enabled=')}")
    # 2. /health（后端直连 127.0.0.1:8001）——需带 web 会话 token 才 200
    if web_pass:
        o, e = run(cli, f"""
P='{web_pass}'
TOK=$(curl -s -X POST http://127.0.0.1:8001/api/auth/login -H 'Content-Type: application/json' \
  -d '{{"password":"'"$P"'"}}' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("token",""))')
[ -n "$TOK" ] && curl -s -o /dev/null -w '%{{http_code}}' -H "X-Auth-Token: $TOK" http://127.0.0.1:8001/api/health || echo no-token
""", t=60)
        print(f"[后端 /api/health 直连+token（应 200）] {o}")
    else:
        o, _ = run(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/api/health")
        print(f"[后端 /api/health 直连匿名（401 因未带 token）] {o}")
    # 3. 前端首页（nginx）
    o, e = run(cli, "curl -s -o /dev/null -w '%{http_code}' https://bookswich.yukinova.top/")
    print(f"[前端首页] {o}（应 200）")
    # 4. /api 认证（无 token → 401；用 web_password 登录 → 带 token → 200）
    a, _ = run(cli, "curl -s -o /dev/null -w '%{http_code}' https://bookswich.yukinova.top/api/health")
    print(f"[api 匿名（应 401）] {a}")
    if web_pass:
        b, _ = run(cli, f"""
P='{web_pass}'
TOK=$(curl -s -X POST https://bookswich.yukinova.top/api/auth/login \
  -H 'Content-Type: application/json' -d '{{"password":"'"$P"'"}}' | python3 -c 'import sys,json;print(json.load(sys.stdin).get("token",""))')
[ -n "$TOK" ] && curl -s -o /dev/null -w '%{{http_code}}' -H "X-Auth-Token: $TOK" https://bookswich.yukinova.top/api/health || echo no-token
""", t=60)
        print(f"[api 登录后带 token（应 200）] {b}")
    else:
        print("[api 登录后带 token] 跳过（未提供 web 密码）")
    # 5. 数据库可读（服务器后端直连查 books 表）
    o, e = run(cli, f"cd {ROOT}/backend && .venv/bin/python -c "
                    f"\"from app.db import get_conn; c=get_conn(); print('db-ok', c.execute('select count(*) from books').fetchone()[0])\"")
    print(f"[数据库可读] {o or e}")
    # 6. WebDAV vault 可访问（服务监听 + 无凭据 401 = 认证启用即健康；不需真实密码）
    o, e = run(cli, "ss -tlnp 2>/dev/null | grep 8081 >/dev/null && echo listening || echo down")
    o2, _ = run(cli, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/ 2>/dev/null")
    print(f"[WebDAV vault] 监听={o} 匿名状态={o2 if o2 else '?'}（401=已启用认证，健康）")
    print("D4 done")


def cmd_cleanup(cli, apply=False):
    print("=== D3 服务器备份清理 ===")
    # 列出 app.bak-* 和 dist.bak-*
    o, _ = run(cli, f"cd {ROOT} && ls -1dt dist.bak-* app.bak-* 2>/dev/null")
    backups = [l for l in o.splitlines() if l.strip()]
    if not backups:
        print("无备份可清理")
        return
    print(f"现有 {len(backups)} 份备份（保留最新 {KEEP}）:")
    for b in backups:
        sz, _ = run(cli, f"du -sk {ROOT}/{b} 2>/dev/null | cut -f1")
        print(f"  {b}  ({int(sz or 0)//1024}MB)")
    to_delete = backups[KEEP:]
    if not to_delete:
        print("无需清理（未超保留数）")
        return
    print(f"将删除 {len(to_delete)} 份旧备份:")
    free = 0
    for b in to_delete:
        sz, _ = run(cli, f"du -sk {ROOT}/{b} 2>/dev/null | cut -f1")
        free += int(sz or 0)
        print(f"  - {b}  (~{int(sz or 0)//1024}MB)")
        if apply:
            run(cli, f"rm -rf {ROOT}/{b}")
    print(f"{'已释放' if apply else 'dry-run 将释放'} ~{free//1024}MB")
    # 记录清理时间/数量/空间（先建 log 目录再追加）
    if apply and to_delete:
        ts = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
        run(cli, f"mkdir -p {ROOT}/scripts && echo '[{ts}] cleanup {len(to_delete)} backups, freed ~{free//1024}MB' "
                 f">> {ROOT}/scripts/backup_cleanup.log")
    print("D3 done")


def main() -> int:
    ap = argparse.ArgumentParser(description="bookswich 服务器运维（D3/D4）")
    ap.add_argument("--check", action="store_true", help="D4 健康检查")
    ap.add_argument("--cleanup", action="store_true", help="D3 备份清理（dry-run 列）")
    ap.add_argument("--apply", action="store_true", help="D3 实际删除")
    args = ap.parse_args()
    if not (args.check or args.cleanup):
        ap.print_help()
        return 2
    pw = os.environ.get("BOOKSWICH_SSH_PASS")
    if not pw:
        print("需设置环境变量 BOOKSWICH_SSH_PASS（服务器 root 密码，不写入脚本/日志）", file=sys.stderr)
        return 3
    web_pass = os.environ.get("BOOKSWICH_WEB_PASS", "")
    cli = ssh(pw)
    try:
        if args.check:
            cmd_check(cli, pw, web_pass)
        if args.cleanup:
            cmd_cleanup(cli, apply=args.apply)
    finally:
        cli.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())