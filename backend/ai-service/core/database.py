"""业务库连接工厂（PostgreSQL / asyncpg）。

ai-service 的商品/用户/购物车等业务数据从 MySQL 迁移到 PostgreSQL，
本模块提供业务库的 async session。

- 连接的是 `PG_BUSINESS_DB`（默认 welove_shop_db）
- 与 pg_search 模块的 langgraph 记忆库分开（那个是 PG_LANGGRAPH_DB / welove_shop_search）
- 同一个 PostgreSQL 实例，不同 database，共用 PG_HOST / PG_USER / PG_PASSWORD

MySQL 兼容层：`build_mysql_url()` 仍保留，供 scripts/sync_mysql_to_pg.py 从 MySQL 拉数据用。
业务代码不应再调用它。
"""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import config


def build_database_url() -> str:
    """业务库连接串（PostgreSQL asyncpg）。"""
    password = quote_plus(config.PG_PASSWORD)
    return (
        f"postgresql+asyncpg://{config.PG_USER}:{password}"
        f"@{config.PG_HOST}:{config.PG_PORT}/{config.PG_BUSINESS_DB}"
    )


def build_mysql_url() -> str:
    """MySQL 连接串（历史遗留，只用于 sync 脚本从 MySQL 拉数据）。

    业务代码请用 build_database_url()。
    """
    password = quote_plus(config.DB_PASSWORD)
    return (
        f"mysql+aiomysql://{config.DB_USER}:{password}"
        f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}"
        f"?charset={config.DB_CHARSET}"
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """业务库 (PostgreSQL) async session factory。"""
    engine = create_async_engine(
        build_database_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    return async_sessionmaker(
        engine, expire_on_commit=False, autoflush=False,
    )


@lru_cache(maxsize=1)
def get_mysql_session_factory() -> async_sessionmaker[AsyncSession]:
    """MySQL async session factory（仅供 sync 脚本使用）。"""
    engine = create_async_engine(
        build_mysql_url(),
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    return async_sessionmaker(
        engine, expire_on_commit=False, autoflush=False,
    )


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
