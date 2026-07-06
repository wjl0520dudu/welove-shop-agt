"""pgvector 异步数据库引擎。

参考 core/database.py 的 MySQL 引擎模式，提供 PostgreSQL + asyncpg 连接。
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import config


def build_pg_database_url() -> str:
    password = quote_plus(config.PG_PASSWORD)
    return (
        f"postgresql+asyncpg://{config.PG_USER}:{password}"
        f"@{config.PG_HOST}:{config.PG_PORT}/{config.PG_NAME}"
    )


@lru_cache(maxsize=1)
def get_pg_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        build_pg_database_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
