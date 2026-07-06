"""
把 MySQL welove_shop_db 里的商品相关数据同步到 PostgreSQL welove_shop_db。

只同步 ai-service 目前实际读的表：category、product。
其他表（user、conversation、product_sku 等）Java 迁移完成后再由 Java 项目处理。

用法：
    conda activate D:\\dev\\env\\conda_envs\\wlagt
    cd backend/ai-service
    python scripts/sync_mysql_to_pg.py               # 全量同步
    python scripts/sync_mysql_to_pg.py --dry-run     # 只查数量，不写入
    python scripts/sync_mysql_to_pg.py --truncate    # 先清空 PG 目标表再写

幂等策略：
    上游 MySQL 的 id 是权威的，直接 INSERT ... ON CONFLICT (id) DO UPDATE
    这样反复跑不会重复。也不用管 IDENTITY 序列 —— PG 那边 id 是显式插入的。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_mysql_session_factory, get_session_factory
from shopping.orm_models import CategoryORM, ProductORM

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_mysql_to_pg")


# ---- ORM → dict 转换 ---------------------------------------------------------

def category_to_dict(c: CategoryORM) -> dict:
    return {
        "id": int(c.id),
        "name": c.name,
        "description": c.description,
    }


def product_to_dict(p: ProductORM) -> dict:
    return {
        "id": int(p.id),
        "product_code": p.product_code,
        "category_id": int(p.category_id),
        "title": p.title,
        "brand": p.brand,
        "sub_category": p.sub_category,
        "base_price": float(p.base_price) if p.base_price is not None else 0.0,
        "image_url": p.image_url,
        "description": p.description,
        "tags": p.tags,
        "rating": float(p.rating) if p.rating is not None else 0.0,
        "review_count": p.review_count,
        "sales_count": p.sales_count,
        "status": p.status,
        "embedding_status": p.embedding_status,
        "create_time": p.create_time,
        "update_time": p.update_time,
    }


# ---- 同步逻辑 ----------------------------------------------------------------

async def sync_table(
    mysql_factory,
    pg_factory,
    orm_class,
    to_dict,
    tbl_name: str,
    truncate: bool = False,
    dry_run: bool = False,
) -> int:
    """通用表同步：MySQL 全量读 → PG upsert（按主键冲突时更新）。"""
    # 1. 读 MySQL
    async with mysql_factory() as ms:
        rows = (await ms.execute(select(orm_class))).scalars().all()
    logger.info("[%s] MySQL 读到 %d 行", tbl_name, len(rows))

    if dry_run:
        return len(rows)

    if not rows:
        return 0

    # 2. 写 PG
    async with pg_factory() as pg:
        if truncate:
            # CASCADE 会连着 product_sku 等外键子表一起清空 —— 生产慎用。
            # 我们只清 category / product 这两张，其他表 ai-service 不写。
            await pg.execute(text(f"TRUNCATE TABLE {tbl_name} RESTART IDENTITY CASCADE"))
            logger.info("[%s] TRUNCATE done", tbl_name)

        records = [to_dict(r) for r in rows]

        # 用 PG 的 ON CONFLICT DO UPDATE 做 upsert。
        # 直接对着 ORM 表构造 insert，PG 方言。
        stmt = pg_insert(orm_class.__table__).values(records)
        update_cols = {c.name: stmt.excluded[c.name] for c in orm_class.__table__.columns if c.name != "id"}
        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_cols)
        await pg.execute(stmt)
        await pg.commit()

    logger.info("[%s] PG 写入 %d 行", tbl_name, len(rows))
    return len(rows)


async def main_async(dry_run: bool = False, truncate: bool = False):
    mysql_factory = get_mysql_session_factory()
    pg_factory = get_session_factory()

    total_cat = await sync_table(
        mysql_factory, pg_factory, CategoryORM, category_to_dict, "category",
        truncate=truncate, dry_run=dry_run,
    )
    total_prod = await sync_table(
        mysql_factory, pg_factory, ProductORM, product_to_dict, "product",
        truncate=truncate, dry_run=dry_run,
    )

    # 释放连接池，避免 Windows aiomysql 析构告警
    # async_sessionmaker 的 bind 通过 .kw 传入，但更稳的做法是从 factory 里现取一个 session 拿 engine
    try:
        await mysql_factory.kw.get("bind").dispose()  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        await pg_factory.kw.get("bind").dispose()  # type: ignore[union-attr]
    except Exception:
        pass

    logger.info("同步完成：category=%d, product=%d", total_cat, total_prod)


def main():
    parser = argparse.ArgumentParser(description="MySQL → PostgreSQL 商品数据同步")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--truncate", action="store_true", help="写入前 TRUNCATE 目标表（RESTART IDENTITY CASCADE）")
    args = parser.parse_args()
    asyncio.run(main_async(dry_run=args.dry_run, truncate=args.truncate))


if __name__ == "__main__":
    main()
