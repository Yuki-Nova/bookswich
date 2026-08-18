"""FastAPI 应用入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import settings
from .db import init_db, recover_stale_parsing
from .services.auth import has_auth_configured, is_token_valid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    n = recover_stale_parsing()
    if n:
        logging.getLogger(__name__).info("reset %d stale parsing book(s) -> pending", n)
    yield


app = FastAPI(title="bookswich", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_api_token(request, call_next):
    """可选鉴权（B5-A）：配置 web_password / api_token 后，所有 /api 请求须带有效 token。

    - 未配置任何鉴权 → 零行为变化（本地/内网零摩擦）
    - 校验通过任意一层：api_token（程序调用，X-Auth-Token 头 / ?token=）
      或 web 会话 token（前端登录后由 /api/auth/login 签发，同样是 X-Auth-Token 头）
    - /api/auth/login 本身放行（登录入口）
    """
    if request.url.path.startswith("/api") and not request.url.path.startswith("/api/auth/login"):
        if has_auth_configured():
            supplied = request.headers.get("x-auth-token") or request.query_params.get("token")
            if not is_token_valid(supplied):
                return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"app": "bookswich", "status": "ok", "docs": "/docs"}
