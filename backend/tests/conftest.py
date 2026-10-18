"""pytest 基建：独立测试库 lumencafe_test + 迁移 + 种子（架构设计 §9.1 约定）。

运行前提：本机 PostgreSQL 已启动（docker compose up -d db 或系统 PG）。
在 backend/ 目录下执行：``.venv/Scripts/python.exe -m pytest tests -v``
"""
import asyncio
import os

import pytest_asyncio

# ── 必须在任何 app 模块导入前设定测试环境 ──────────────────
BASE_URL = os.environ.get(
    "LUMEN_TEST_BASE_URL", "postgresql+asyncpg://lumencafe:lumencafe@localhost:5432"
)
TEST_DB = "lumencafe_test"
TEST_URL = f"{BASE_URL}/{TEST_DB}"

os.environ["LUMEN_DATABASE_URL"] = TEST_URL
os.environ["LUMEN_JWT_SECRET"] = "pytest-only-secret-0123456789abcdef"
os.environ["LUMEN_ADMIN_PASSWORD"] = "admin-test-pass"
os.environ["LUMEN_INTERNAL_TOKEN"] = "pytest-internal-token-0123456789abcdef"
os.environ["LUMEN_RATE_LIMIT_ENABLED"] = "false"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin-test-pass"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def prepare_db():
    """重建 lumencafe_test 库并跑到最新迁移（session 级一次）。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_engine = create_async_engine(f"{BASE_URL}/postgres", isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}"'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin_engine.dispose()

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")  # 要求 CWD = backend/
    # env.py 内部 asyncio.run() 需要独立事件循环，放到线程里执行
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(prepare_db):
    """ASGI 客户端 + 种子数据（不进 lifespan，种子在此手动跑）。"""
    import httpx

    import app.models  # noqa: F401  确保 16 张表注册到 metadata
    from app.db import SessionLocal
    from app.main import app as fastapi_app
    from app.services.seed import run_seed

    async with SessionLocal() as db:
        await run_seed(db)

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean(client):
    """每个用例前清空全部业务表并重新种子（providers 等不级联 users，需显式列出）。"""
    from sqlalchemy import text

    from app.db import SessionLocal
    from app.services.seed import run_seed

    tables = (
        "users, roles, permissions, user_roles, role_permissions, "
        "user_settings, app_registry, app_visibility, categories, "
        "chat_conversations, chat_messages, "
        "providers, llm_models, gateway_tokens, "
        "money_categories, money_transactions"
    )
    async with SessionLocal() as db:
        await db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await db.commit()
        await run_seed(db)
    yield


async def login(client, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> dict:
    """登录并返回带 Bearer 头的请求头。"""
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
