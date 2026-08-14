"""FastAPI 应用入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .config import settings
from .db import init_db, recover_stale_parsing

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
    """可选鉴权：配置 API_TOKEN 后，所有 /api 请求须带 X-Auth-Token 头或 ?token= 参数。

    默认未配置时零行为变化（本地/内网零摩擦）。公开部署建议另配 nginx basic auth
    兜住整个站点（含静态资源），本 token 供插件/程序化调用使用。
    """
    token = settings.api_token
    if token and request.url.path.startswith("/api"):
        supplied = request.headers.get("x-auth-token") or request.query_params.get("token")
        if supplied != token:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"app": "bookswich", "status": "ok", "docs": "/docs"}
