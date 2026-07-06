"""把 MySQL welove_shop_db 里的数据同步到 PostgreSQL welove_shop_db。

覆盖表（按当前 MySQL 里有数据的表决定）：
    category, product, product_sku, product_image, product_review, product_faq,
    knowledge_doc, knowledge_chunk, qa_unanswered

其他空表（address / order / conversation 等）无需同步，Java 端上线后自然产生数据。

用法：
    conda activate D:\\dev\\env\\conda_envs\\wlagt
    cd backend/ai-service
    python scripts/sync_mysql_to_pg.py                # 全部同步
    python scripts/sync_mysql_to_pg.py --dry-run      # 只查数量，不写入
    python scripts/sync_mysql_to_pg.py --tables product,product_sku    # 只同步指定表
    python scripts/sync_mysql_to_pg.py --truncate                       # 写入前 TRUNCATE 目标表

## 幂等策略
上游 MySQL 的 id 是权威主键，用 INSERT ... ON CONFLICT (id) DO UPDATE。
反复跑不会重复。写入后 PG 的 IDENTITY 序列需要跳过已用 id，本脚本用
`SELECT setval(pg_get_serial_sequence(...), MAX(id))` 修复序列。

## 反射式表结构读取
不依赖 Python ORM。用 SQLAlchemy `MetaData.reflect(bind=..., only=[...])` 读取
MySQL 表结构，然后按列名映射写入 PG（假设两侧列名一致 —— pg-init-business.sql 保证了这点）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.database import build_database_url, build_mysql_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_mysql_to_pg")

# 要同步的表清单。顺序按外键依赖排：先父表后子表，避免 FK 场景问题（虽然 PG 建表没加 FK）。
SYNC_TABLES: list[str] = [
    "category",
    "users",           # MySQL 侧已 rename from `user`（PG 保留字冲突）
    "product",
    "product_sku",
    "product_image",
    "product_review",
    "product_faq",
    "knowledge_doc",
    "knowledge_chunk",
    "qa_unanswered",
]


async def _reflect_mysql_table(mysql_engine: AsyncEngine, tbl_name: str) -> Table:
    """异步反射 MySQL 表结构。返回 SQLAlchemy Table 对象。"""
    metadata = MetaData()

    def _sync_reflect(sync_conn):
        metadata.reflect(bind=sync_conn, only=[tbl_name])

    async with mysql_engine.begin() as conn:
        await conn.run_sync(_sync_reflect)
    return metadata.tables[tbl_name]


async def _sync_one_table(
    mysql_engine: AsyncEngine,
    pg_engine: AsyncEngine,
    tbl_name: str,
    truncate: bool,
    dry_run: bool,
) -> int:
    """从 MySQL 读一张表 → PG upsert。"""
    # 1. 反射 MySQL 表结构，然后 SELECT * 全量读
    mysql_tbl = await _reflect_mysql_table(mysql_engine, tbl_name)

    async with mysql_engine.connect() as conn:
        result = await conn.execute(select(mysql_tbl))
        # 用 mappings() 拿到 name-keyed dict，方便直接给 PG 插入用
        rows = [dict(m) for m in result.mappings().all()]

    logger.info("[%s] MySQL 读到 %d 行", tbl_name, len(rows))

    if dry_run or not rows:
        return len(rows)

    # 2. 反射 PG 目标表结构，用 PG 方言的 insert...on conflict do update 实现幂等 upsert
    pg_metadata = MetaData()

    def _sync_reflect_pg(sync_conn):
        pg_metadata.reflect(bind=sync_conn, only=[tbl_name])

    async with pg_engine.begin() as conn:
        await conn.run_sync(_sync_reflect_pg)
        pg_tbl = pg_metadata.tables[tbl_name]

        if truncate:
            # RESTART IDENTITY 重置 IDENTITY 序列；CASCADE 会带外键子表一起清（我们没加 FK 所以其实无副作用）
            await conn.execute(text(f'TRUNCATE TABLE "{tbl_name}" RESTART IDENTITY CASCADE'))
            logger.info("[%s] TRUNCATE done", tbl_name)

        # 只保留 PG 表实际存在的列（防止 MySQL 有多余列 / json 类型名不同等意外）
        pg_col_names = {c.name for c in pg_tbl.columns}
        filtered_rows = [
            {k: v for k, v in row.items() if k in pg_col_names} for row in rows
        ]

        stmt = pg_insert(pg_tbl).values(filtered_rows)
        # ON CONFLICT (id) DO UPDATE SET <所有非id列>=EXCLUDED.<列>
        update_cols = {c.name: stmt.excluded[c.name] for c in pg_tbl.columns if c.name != "id"}
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
        await conn.execute(stmt)

        # 修正 IDENTITY 序列到 MAX(id) + 1，否则后续 INSERT 不指定 id 会撞主键
        # pg_get_serial_sequence 返回 "public.product_id_seq" 这类名字
        await conn.execute(text(f"""
            SELECT setval(
                pg_get_serial_sequence('{tbl_name}', 'id'),
                COALESCE((SELECT MAX(id) FROM "{tbl_name}"), 1),
                (SELECT MAX(id) FROM "{tbl_name}") IS NOT NULL
            )
        """))

    logger.info("[%s] PG 写入 %d 行 + 序列已修正", tbl_name, len(rows))
    return len(rows)


async def main_async(
    tables: list[str],
    dry_run: bool = False,
    truncate: bool = False,
) -> None:
    mysql_engine = create_async_engine(build_mysql_url(), pool_pre_ping=True)
    pg_engine = create_async_engine(build_database_url(), pool_pre_ping=True)

    totals: dict[str, int] = {}
    try:
        for tbl in tables:
            totals[tbl] = await _sync_one_table(
                mysql_engine, pg_engine, tbl, truncate=truncate, dry_run=dry_run,
            )
    finally:
        await mysql_engine.dispose()
        await pg_engine.dispose()

    logger.info("同步完成 (%s): %s", "DRY" if dry_run else "REAL", totals)


def main():
    parser = argparse.ArgumentParser(description="MySQL → PostgreSQL 全量同步")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--truncate", action="store_true", help="写入前 TRUNCATE 目标表")
    parser.add_argument(
        "--tables",
        type=str,
        help="逗号分隔的表名，只同步这些表（默认全部）",
    )
    args = parser.parse_args()

    tables = SYNC_TABLES
    if args.tables:
        tables = [t.strip() for t in args.tables.split(",") if t.strip()]
        invalid = [t for t in tables if t not in SYNC_TABLES]
        if invalid:
            parser.error(f"未知的表名: {invalid}，支持的表：{SYNC_TABLES}")

    asyncio.run(main_async(tables=tables, dry_run=args.dry_run, truncate=args.truncate))


if __name__ == "__main__":
    main()
