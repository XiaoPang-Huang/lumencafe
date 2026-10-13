"""LumenCafe FastAPI 入口（批次 1-T01：仅环境地基 + 健康检查）。

后续批次在此挂路由：auth / admin / apps / chat / me 等。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import engine
from app.logging_conf import get_logger, setup_logging

setup_logging(settings.log_level)
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子：敏感配置告警；退出时释放数据库连接池。"""
    if settings.jwt_secret == "change-me-in-production":
        logger.warning("LUMEN_JWT_SECRET 仍为默认值，生产环境请更换为长随机串！")
    yield
    await engine.dispose()


app = FastAPI(title="流光咖啡馆 API", lifespan=lifespan)

# 本地开发跨域；生产由 Caddy 同域反代，可将 LUMEN_CORS_ORIGINS 留空
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health():
    """健康检查（docker-compose api 服务 healthcheck 同款探测）。"""
    return {"ok": True}
