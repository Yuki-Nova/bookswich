"""B5-A 鉴权服务（2026-08-18）：网页登录会话 token 生成与校验。

设计：web_password 固定（.env），会话 token = 确定性签名（web_password + 固定盐），
登录时前端 POST 密码 → 若匹配返回该 token；此后 /api 请求带 X-Auth-Token。
token 静态可每次重算比对（无需 session 存储 / 过期管理），
前端存 localStorage，登录态在浏览器周期内持续有效。

与 api_token（程序化调用）并存：/api 校验时二者任一有效即放行——
  - api_token       ：脚本/插件（X-Auth-Token 头）
  - 会话 token       ：浏览器网页（登录后由 /api/auth/login 签发）
"""
from __future__ import annotations

import hashlib

from ..config import settings

# 固定盐：会话 token 确定性签名用（web_password + 盐 → 不变 token）
_SALT = "bookswich-web-session-v1"


def session_token(web_password: str | None = None) -> str:
    """由 web_password 计算确定性会话 token（不落库）。"""
    pw = web_password if web_password is not None else settings.web_password
    return "web_" + hashlib.sha256((pw + _SALT).encode("utf-8")).hexdigest()[:48]


def is_token_valid(supplied: str | None) -> bool:
    """校验前端/程序提供的 token 是否有效（api_token 或 web 会话 token）。"""
    if not supplied:
        return False
    # 程序化调用 token
    if settings.api_token and supplied == settings.api_token:
        return True
    # 浏览器会话 token（web_password 配置时）
    if settings.web_password and supplied == session_token():
        return True
    return False


def has_auth_configured() -> bool:
    """是否启用了任何一层鉴权（api_token 或 web_password）。"""
    return bool(settings.api_token or settings.web_password)
