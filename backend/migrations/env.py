"""Alembic 环境：异步引擎，复用 app 的 Base 元数据与集中配置。

- 数据库 URL 由 app.core.config 在运行时注入（密钥只走环境变量，绝不写入 alembic.ini）。
- 导入 app.models 让全部表挂到 Base.metadata，供未来 `alembic revision --autogenerate` 使用。
- 异步模式：通过 asyncio.run 驱动 asyncpg/aiosqlite 连接。
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.db import Base, engine
from app import models  # noqa: F401  确保模型注册到 Base.metadata（供 autogenerate）

config = context.config

# 把数据库 URL 从环境变量配置注入（覆盖 ini 中的占位）
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：异步连接并执行迁移。"""
    async_engine: AsyncEngine = engine
    async with async_engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await async_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
