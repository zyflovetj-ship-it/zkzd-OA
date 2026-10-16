"""异步数据库引擎、会话工厂与声明基类。兼容 PostgreSQL / SQLite。"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # SQLite 跨线程访问需要放开检查
    _connect_args = {"check_same_thread": False}

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    future=True,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# 说明：表结构由 Alembic 迁移管理（见 migrations/ 与 alembic.ini），
# 不再使用 Base.metadata.create_all。部署/启动前请执行 `alembic upgrade head`
# （run.sh 与 Dockerfile 已内置该预启动步骤）。

