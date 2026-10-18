"""LumenCafe FastAPI 入口（批次 1-T01 环境地基；T02 起挂种子与中间件）。

后续批次在此挂路由：auth / admin / apps / chat / me 等。
"""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import SessionLocal, engine
from app.logging_conf import get_logger, setup_logging
from app.routers import (
    admin_models,
    admin_users,
    apps,
    auth,
    chat,
    gateway,
    internal,
    me,
    money,
    papers,
)
from app.services.seed import run_seed

setup_logging(settings.log_level)
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子：种子数据 → 敏感配置告警；退出时释放数据库连接池。"""
    async with SessionLocal() as db:
        await run_seed(db)
    if settings.jwt_secret == "change-me-in-production":
        logger.warning("LUMEN_JWT_SECRET 仍为默认值，生产环境请更换为长随机串！")
    yield
    await engine.dispose()


app = FastAPI(title="流光咖啡馆 API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin_users.router)
app.include_router(admin_models.router)
app.include_router(money.router)
app.include_router(apps.router)
app.include_router(internal.router)
app.include_router(gateway.router)
app.include_router(chat.router)
app.include_router(papers.router)

# 本地开发跨域；生产由 Caddy 同域反代，可将 LUMEN_CORS_ORIGINS 留空
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """请求日志：method/path/status/耗时（沿用旧版约定，见架构设计 §9.1）。"""
    start = time.time()
    response = await call_next(request)
    logger.info(
        "%s %s -> %s (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        (time.time() - start) * 1000,
    )
    return response


@app.get("/health")
async def health():
    """健康检查（docker-compose api 服务 healthcheck 同款探测）。"""
    return {"ok": True}
