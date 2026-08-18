"""B5-A: 前端登录 + token 鉴权后端测试（2026-08-18）。

覆盖：
- config.web_password 存在
- POST /api/auth/login 密码正确 → 返回 token；错误 → 401
- login 返回的 token 能访问受保护 /api（浏览器会话）
- 配了 api_token 时登录 token 与 api_token 均可用（程序+浏览器通吃）
- 匿名访问 /api（配置了密码时）→ 401
- 未配置任何密码 → 匿名访问正常（本地零摩擦，向后兼容）
"""
import json
import pytest


def _env(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from app.db import init_db

    init_db()


def _client(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


def test_login_success_and_token(tmp_path, monkeypatch):
    """密码正确 → 返回 token；token 可访问受保护 /api。"""
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "secret123")
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/auth/login", json={"password": "secret123"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert token
    # 用 token 访问受保护接口
    r2 = c.get("/api/health", headers={"X-Auth-Token": token})
    assert r2.status_code == 200


def test_login_wrong_password(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "secret123")
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401


def test_anonymous_blocked_when_password_set(tmp_path, monkeypatch):
    """配置密码后，匿名访问 /api → 401。"""
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "secret123")
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/health").status_code == 401
    assert c.get("/api/books").status_code == 401


def test_both_api_token_and_session_token_valid(tmp_path, monkeypatch):
    """api_token（程序）与登录会话 token（浏览器）皆可访问。"""
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "secret123")
    monkeypatch.setattr(settings, "api_token", "prog-token-xyz")
    c = _client(tmp_path, monkeypatch)
    # api_token 程序调用
    assert c.get("/api/health", headers={"X-Auth-Token": "prog-token-xyz"}).status_code == 200
    # 登录会话 token
    tok = c.post("/api/auth/login", json={"password": "secret123"}).json()["token"]
    assert c.get("/api/health", headers={"X-Auth-Token": tok}).status_code == 200


def test_no_password_configured_allows_anonymous(tmp_path, monkeypatch):
    """未配置 web_password：local 模式匿名可用（向后兼容）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "")
    monkeypatch.setattr(settings, "api_token", "")
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/health").status_code == 200


def test_login_missing_field(tmp_path, monkeypatch):
    """login 无 password 字段 → 400。"""
    from app.config import settings

    monkeypatch.setattr(settings, "web_password", "secret123")
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/auth/login", json={})
    assert r.status_code in (400, 422)