"""pgvector 初始化：建表 + HNSW 索引。

在 docker-compose 首次启动时自动执行（通过 docker-entrypoint-initdb.d），
也可手动调用 init_db()。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from pg_search.engine import get_pg_session_factory

logger = logging.getLogger("ai-service.pg_search")

INIT_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS products_search (
    id              BIGINT PRIMARY KEY,
    title           VARCHAR(500) NOT NULL DEFAULT '',
    brand           VARCHAR(100),
    category_name   VARCHAR(50),
    sub_category    VARCHAR(50),
    base_price      DOUBLE PRECISION,
    image_url       VARCHAR(500),
    rating          DOUBLE PRECISION,
    review_count    INTEGER,
    sales_count     INTEGER,
    tags            TEXT,
    description     TEXT,
    status          INTEGER DEFAULT 1,
    embedding       vector(1536),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- HNSW 索引，加速向量近似搜索
CREATE INDEX IF NOT EXISTS idx_products_embedding
    ON products_search
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- 辅助索引：按 status 过滤
CREATE INDEX IF NOT EXISTS idx_products_status
    ON products_search (status);

-- 辅助索引：按销量排序
CREATE INDEX IF NOT EXISTS idx_products_sales
    ON products_search (sales_count DESC);
""".strip()


async def init_db() -> bool:
    """创建 products_search 表 + 索引。幂等，可重复执行。"""
    session_factory = get_pg_session_factory()
    async with session_factory() as session:
        # 逐条执行以避免 asyncpg 多语句限制
        statements = [s.strip() for s in INIT_SQL.split(";") if s.strip()]
        for stmt in statements:
            try:
                await session.execute(text(stmt + ";"))
            except Exception as e:
                logger.warning("init_db statement skipped: %s", e)
        await session.commit()
    logger.info("pgvector init_db completed")
    return True


def write_init_sql(path: str) -> None:
    """将 INIT_SQL 写入文件，供 docker-entrypoint-initdb.d 使用。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(INIT_SQL + "\n")
    logger.info("pgvector init SQL written to %s", path)
