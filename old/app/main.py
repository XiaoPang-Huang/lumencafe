import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .config import settings
from .db import init_db
from .llm.providers import ensure_llm_seed
from .routers import admin, apps, auth, chat, focus, me, space, stats, papers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("island")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.dev_login:
        logger.warning("ISLAND_DEV_LOGIN=true：dev:* 账号可直接登录，仅限本地开发！")
    if settings.jwt_secret == "change-me-in-production":
        logger.warning("ISLAND_JWT_SECRET 仍为默认值，生产环境请更换为长随机串！")
    await init_db()
    await ensure_llm_seed()
    yield


app = FastAPI(title="小岛 API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(me.router)
app.include_router(apps.router)
app.include_router(focus.router)
app.include_router(chat.router)
app.include_router(space.router)
app.include_router(stats.router)
app.include_router(papers.router)
app.include_router(admin.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    logger.info("%s %s -> %s (%.0fms)", request.method, request.url.path, response.status_code, (time.time() - start) * 1000)
    return response


@app.get("/health")
async def health():
    return {"ok": True}
