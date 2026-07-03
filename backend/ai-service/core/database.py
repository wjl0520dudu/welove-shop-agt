from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import config


def build_database_url() -> str:
    password = quote_plus(config.DB_PASSWORD)
    return (
        f"mysql+aiomysql://{config.DB_USER}:{password}"
        f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
        f"?charset={config.DB_CHARSET}"
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        build_database_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
