"""数据库引擎与会话（SQLAlchemy 2.0 asyncio）。

- 连接池小池化：pool_size + max_overflow 与 PG max_connections=20 匹配；
- Base 仅为 Alembic autogenerate 的 metadata 来源，运行时绝不 create_all；
- get_db 为 FastAPI 依赖注入用的请求级会话。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# pool_pre_ping：避免 PG 重启/空闲断连后的首个请求报错
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """ORM 基类。批次 2 起各模型模块从此继承并汇总到 app.models。"""


async def get_db():
    """请求级数据库会话依赖：路由内单请求单事务，显式 commit。"""
    async with SessionLocal() as session:
        yield session
