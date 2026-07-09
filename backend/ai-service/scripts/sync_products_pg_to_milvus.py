"""PG → Milvus 商品同步脚本（Phase 1b 后的运维基础设施）。

## 为什么需要这个脚本

Phase 1b 起商品向量在 Milvus，业务主档在 PG。商品的 title/base_price/tags/status 等
字段会在 PG 里被后台系统 / Java 服务改动，Milvus 里冗余的那些字段必须跟上，
否则用户看到的商品卡片会逐渐过期。

CLAUDE.md 里的分工文档说得很清楚：
- Milvus 冗余存"展示 + 排序 + 筛选"字段（title/brand/base_price/rating/…）
- PG 存"权威真源 + 强一致业务数据"（订单/SKU/库存/用户）

本脚本负责把 PG 的商品字段变化定期同步到 Milvus。

## 三种模式

1. **全量 (--mode full)**：把 PG 所有 status=1 商品灌进 Milvus（覆盖，含删除的清理）
   - 首次上线用
   - 大改动后重灌用
   - 100 商品 ≈ 100 秒（受 DashScope embedding 串行速率限制）

2. **增量 (--mode incremental)**：只同步 PG 里 update_time 变化的商品
   - 日常定时任务（推荐每 5-15 分钟一次 / 或 cron 5min）
   - 需要 --since <timestamp> 指定"上次同步时间"
   - 空跑（无更新）秒级返回，不消耗 embedding 配额

3. **单商品 (--mode one --product-id N)**：立即同步一个商品
   - 后台修改商品后立刻推送
   - 生产 Java 侧可以通过 API 触发（本脚本作为调用入口，或后续做成 HTTP 端点）

## ID 一致性约定（重要！）

**Milvus 里的 product_id == PG 里的 product.id**。

Phase 1b 首次冷启动脚本 (scripts/ingest_products_to_milvus.py) 用的是从
product_code (p_beauty_001) 合成的 100001~400025 —— 那是**权宜之计**，
生产运维必须走本同步脚本重灌，让 Milvus product_id 对齐 PG.id (1~100)。

这样 DetailCapability 拿到 Milvus 里的 product_id 后可以直接
`SELECT * FROM product WHERE id = ?` 查 PG（SKU/库存/订单场景），
不用再做映射转换。

## 增量同步判定逻辑

对每个 PG 商品：
1. 用 PG.update_time 跟 --since 比 → 时间早的直接跳过
2. Milvus 里查有没有这个 product_id
3. 有 → upsert 覆盖；没有 → 新增
4. 反向：Milvus 里存在但 PG 里 status != 1 或不存在的 → 删除

## 灌数据字段映射

PG.product                       → Milvus.product_mm_collection
  id                             → product_id
  title                          → title
  brand                          → brand
  category.name                  → category (顶级类目，来自 join)
  sub_category                   → sub_category
  base_price                     → base_price
  image_url                      → image_url
  description                    → description
  tags                           → tags
  rating                         → rating
  sales_count                    → sales_count
  review_count                   → review_count
  status                         → status
  (BM25 text 由 ProductMilvusStore._build_search_text 自动拼接)

## 用法

    # 首次全量
    python scripts/sync_products_pg_to_milvus.py --mode full

    # 增量（自动读上次同步时间戳）
    python scripts/sync_products_pg_to_milvus.py --mode incremental

    # 增量（手动指定 since）
    python scripts/sync_products_pg_to_milvus.py --mode incremental --since "2026-07-08T00:00:00"

    # 单商品
    python scripts/sync_products_pg_to_milvus.py --mode one --product-id 42

    # dry-run（不真写 Milvus，只打印会做什么）
    python scripts/sync_products_pg_to_milvus.py --mode full --dry-run

## 时间戳持久化

用 Milvus store 的 stats 是不够的（没有"上次同步"字段）。
简单做法：把上次同步时间存到 PG 的一张小表 `sync_watermark`。
本脚本自建（不存在则创建），格式：
    key VARCHAR PRIMARY KEY  ('products_to_milvus')
    last_synced_at TIMESTAMPTZ
    updated_at TIMESTAMPTZ

## 后续演化路径

- Phase 2 图片就绪后：本脚本读 PG.image_url，可能再调 tongyi-vision-flash embed 图片
  更新 multimodal_vector（新增一个 --refresh-multimodal 开关）
- 生产化：可以做成 FastAPI 端点 POST /admin/sync-products，供 Java 后台管理调用
- 事件驱动：改造成消费 PG outbox / Kafka，做实时增量（本脚本作为基础实现留着，
  应急重灌 / 定时任务兜底）
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text                       # noqa: E402
from sqlalchemy.orm import selectinload                   # noqa: E402

from core.database import get_session_factory             # noqa: E402
from shopping.orm_models import CategoryORM, ProductORM   # noqa: E402
from shopping.vector_store import get_product_milvus_store  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("sync_products")


# ---- watermark 持久化 -----------------------------------------------------

_WATERMARK_KEY = "products_to_milvus"

_ENSURE_WATERMARK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sync_watermark (
    key VARCHAR(64) PRIMARY KEY,
    last_synced_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


async def _ensure_watermark_table():
    """首次跑时自动建 sync_watermark 表（幂等）。"""
    sf = get_session_factory()
    async with sf() as s:
        await s.execute(text(_ENSURE_WATERMARK_TABLE_SQL))
        await s.commit()


async def _get_last_synced_at() -> Optional[datetime]:
    sf = get_session_factory()
    async with sf() as s:
        row = (await s.execute(
            text("SELECT last_synced_at FROM sync_watermark WHERE key = :k"),
            {"k": _WATERMARK_KEY},
        )).first()
    return row[0] if row else None


async def _save_last_synced_at(ts: datetime):
    sf = get_session_factory()
    async with sf() as s:
        await s.execute(
            text(
                "INSERT INTO sync_watermark (key, last_synced_at, updated_at) "
                "VALUES (:k, :ts, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET last_synced_at = :ts, updated_at = NOW()"
            ),
            {"k": _WATERMARK_KEY, "ts": ts},
        )
        await s.commit()


# ---- PG 商品读取 ---------------------------------------------------------

async def _fetch_products_from_pg(
    *,
    since: Optional[datetime] = None,
    product_id: Optional[int] = None,
    only_active: bool = True,
) -> List[Dict[str, Any]]:
    """从 PG 读商品 join category，转成 ProductMilvusStore.upsert_products 期望的 dict。

    Args:
        since: 只返回 update_time > since 的记录（增量用）；None 表示全量
        product_id: 只返回这一个（单商品同步用）
        only_active: True 时 filter status=1；False 时全量（含下架，供 delete 判定用）

    Note:
        product.update_time 是 timezone-naive（PG TIMESTAMP WITHOUT TIME ZONE），
        watermark 是 timezone-aware（TIMESTAMPTZ）。这里对齐前者，把 since 剥掉 tz
        再传给 SQL，避免 asyncpg 抛 "can't subtract offset-naive and offset-aware"。
    """
    sf = get_session_factory()
    async with sf() as s:
        stmt = (
            select(ProductORM, CategoryORM.name.label("category_name"))
            .outerjoin(CategoryORM, ProductORM.category_id == CategoryORM.id)
        )
        if only_active:
            stmt = stmt.where(ProductORM.status == 1)
        if product_id is not None:
            stmt = stmt.where(ProductORM.id == product_id)
        if since is not None:
            # tz-aware → tz-naive（对齐 product.update_time 的类型）
            # 先转到 UTC 再剥 tz，保证语义一致
            if since.tzinfo is not None:
                since = since.astimezone(timezone.utc).replace(tzinfo=None)
            stmt = stmt.where(ProductORM.update_time > since)

        rows = (await s.execute(stmt)).all()

    products: List[Dict[str, Any]] = []
    for p, cat_name in rows:
        products.append({
            "product_id": int(p.id),
            "title": p.title or "",
            "brand": p.brand or "",
            "category": cat_name or "",
            "sub_category": p.sub_category or "",
            "base_price": float(p.base_price) if p.base_price is not None else 0.0,
            "image_url": p.image_url or "",
            "description": p.description or "",
            "tags": p.tags or "",
            "rating": float(p.rating) if p.rating is not None else 0.0,
            "sales_count": int(p.sales_count or 0),
            "review_count": int(p.review_count or 0),
            "status": int(p.status if p.status is not None else 1),
        })
    return products


async def _fetch_pg_product_ids(only_active: bool = True) -> Set[int]:
    """返回 PG 里所有商品的 id 集合。用于反向 diff（清理 Milvus 里的孤儿数据）。"""
    sf = get_session_factory()
    async with sf() as s:
        stmt = select(ProductORM.id)
        if only_active:
            stmt = stmt.where(ProductORM.status == 1)
        rows = (await s.execute(stmt)).scalars().all()
    return {int(x) for x in rows}


# ---- Milvus 现存 ID 查询 --------------------------------------------------

def _fetch_milvus_product_ids() -> Set[int]:
    """列出 Milvus 里现有的 product_id。用于反向 diff。"""
    from pymilvus import Collection
    store = get_product_milvus_store()
    collection = Collection(store.collection_name)
    collection.load()
    # Milvus query 没法 "SELECT DISTINCT id"，但 100~1000 商品直接拉一次全量 pk 也 OK
    # 大规模场景可以改成分页 iterator。
    rows = collection.query(
        expr="product_id > 0",
        output_fields=["product_id"],
        limit=16384,   # 单批上限，超过要分页；MVP 阶段够用
    )
    return {int(r["product_id"]) for r in rows}


# ---- 主流程 --------------------------------------------------------------

def _diff_sets(pg_ids: Set[int], milvus_ids: Set[int]) -> Dict[str, Set[int]]:
    """返回 to_add / to_delete / common 三组 id。"""
    return {
        "to_add": pg_ids - milvus_ids,       # PG 有 Milvus 无 → 新增
        "to_delete": milvus_ids - pg_ids,     # Milvus 有 PG 无 → 删除
        "common": pg_ids & milvus_ids,        # 两边都有 → 覆盖更新（增量模式下按 update_time 过滤）
    }


async def _run_full(dry_run: bool = False) -> Dict[str, int]:
    """全量同步：PG 所有 active 商品 → 覆盖 Milvus；孤儿数据（Milvus 有 PG 无）删除。"""
    logger.info("=== 全量同步开始 ===")

    products = await _fetch_products_from_pg(only_active=True)
    pg_ids = {p["product_id"] for p in products}
    milvus_ids = _fetch_milvus_product_ids()

    diff = _diff_sets(pg_ids, milvus_ids)
    logger.info("PG active=%d  Milvus 现存=%d  新增=%d  删除=%d  覆盖=%d",
                len(pg_ids), len(milvus_ids),
                len(diff["to_add"]), len(diff["to_delete"]), len(diff["common"]))

    if dry_run:
        logger.info("[dry-run] 跳过实际写入")
        return {"upserted": 0, "deleted": 0, "skipped": len(products)}

    # upsert 所有 active 商品（新增 + 覆盖一次到位，Milvus upsert 幂等）
    store = get_product_milvus_store()
    upserted = 0
    if products:
        # 走 store.upsert_products 内部按 batch=10 embed
        # 一次全量太大会拖 embedding 时间，切成批打日志
        BATCH = 50
        for i in range(0, len(products), BATCH):
            chunk = products[i:i + BATCH]
            n = store.upsert_products(chunk)
            upserted += n
            logger.info("[batch %d-%d] upsert=%d 累计 %d", i, i + len(chunk) - 1, n, upserted)

    # 删除孤儿
    deleted = 0
    for pid in diff["to_delete"]:
        store.delete_by_product_id(pid)
        deleted += 1
    if deleted:
        logger.info("清理孤儿商品 %d 条", deleted)

    return {"upserted": upserted, "deleted": deleted, "skipped": 0}


async def _run_incremental(since: Optional[datetime], dry_run: bool = False) -> Dict[str, int]:
    """增量同步：只处理 update_time > since 的商品。"""
    if since is None:
        since = await _get_last_synced_at()

    if since is None:
        logger.warning("watermark 为空且未指定 --since，退回全量模式（首次跑推荐用 --mode full）")
        return await _run_full(dry_run=dry_run)

    logger.info("=== 增量同步开始（since=%s）===", since.isoformat())

    # 只查有更新的
    changed_active = await _fetch_products_from_pg(since=since, only_active=True)
    # 还要处理"从 active 变成下架"的：这部分 update_time > since 且 status != 1
    changed_inactive = await _fetch_products_from_pg(since=since, only_active=False)
    inactive_to_delete = [p["product_id"] for p in changed_inactive if p["status"] != 1]

    logger.info("有更新的 active 商品=%d  变下架待删=%d",
                len(changed_active), len(inactive_to_delete))

    if dry_run:
        for p in changed_active[:5]:
            logger.info("  [dry-run upsert] id=%d title=%s", p["product_id"], p["title"][:40])
        for pid in inactive_to_delete[:5]:
            logger.info("  [dry-run delete] id=%d", pid)
        return {"upserted": 0, "deleted": 0, "skipped": len(changed_active) + len(inactive_to_delete)}

    store = get_product_milvus_store()
    upserted = store.upsert_products(changed_active) if changed_active else 0
    deleted = 0
    for pid in inactive_to_delete:
        store.delete_by_product_id(pid)
        deleted += 1

    return {"upserted": upserted, "deleted": deleted, "skipped": 0}


async def _run_one(product_id: int, dry_run: bool = False) -> Dict[str, int]:
    """单商品同步：立即推送指定商品到 Milvus。"""
    logger.info("=== 单商品同步 product_id=%d ===", product_id)

    products = await _fetch_products_from_pg(product_id=product_id, only_active=False)
    if not products:
        logger.warning("PG 里没有 id=%d 的商品，改为从 Milvus 里删除该 id", product_id)
        if dry_run:
            return {"upserted": 0, "deleted": 0, "skipped": 1}
        store = get_product_milvus_store()
        n = store.delete_by_product_id(product_id)
        return {"upserted": 0, "deleted": n, "skipped": 0}

    p = products[0]
    if p["status"] != 1:
        logger.info("商品 %d status=%d（下架），从 Milvus 删除", product_id, p["status"])
        if dry_run:
            return {"upserted": 0, "deleted": 0, "skipped": 1}
        store = get_product_milvus_store()
        n = store.delete_by_product_id(product_id)
        return {"upserted": 0, "deleted": n, "skipped": 0}

    if dry_run:
        logger.info("[dry-run upsert] id=%d title=%s", p["product_id"], p["title"][:40])
        return {"upserted": 0, "deleted": 0, "skipped": 1}

    store = get_product_milvus_store()
    n = store.upsert_products([p])
    return {"upserted": n, "deleted": 0, "skipped": 0}


# ---- CLI 入口 ------------------------------------------------------------

def _parse_since(s: str) -> datetime:
    """支持 ISO 8601 格式的 --since 参数。"""
    # 兼容 '2026-07-08T00:00:00' 和 '2026-07-08 00:00:00'
    s = s.strip().replace(" ", "T")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # 默认按本地时区解析（生产环境建议明确写 tz）
        dt = dt.astimezone()
    return dt


async def main_async(args) -> int:
    await _ensure_watermark_table()

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    if args.mode == "full":
        stats = await _run_full(dry_run=args.dry_run)
    elif args.mode == "incremental":
        since = _parse_since(args.since) if args.since else None
        stats = await _run_incremental(since=since, dry_run=args.dry_run)
    elif args.mode == "one":
        if args.product_id is None:
            print("错误：--mode one 需要 --product-id", file=sys.stderr)
            return 2
        stats = await _run_one(product_id=args.product_id, dry_run=args.dry_run)
    else:
        print(f"未知 mode: {args.mode}", file=sys.stderr)
        return 2

    dt = time.perf_counter() - t0
    logger.info("完成：upserted=%d deleted=%d skipped=%d 耗时 %.1fs",
                stats["upserted"], stats["deleted"], stats["skipped"], dt)

    # 只在真跑成功时更新 watermark
    if not args.dry_run and args.mode in ("full", "incremental"):
        await _save_last_synced_at(started_at)
        logger.info("watermark 更新到 %s", started_at.isoformat())

    return 0


def main():
    parser = argparse.ArgumentParser(description="Sync products from PG to Milvus")
    parser.add_argument("--mode", choices=["full", "incremental", "one"], default="incremental",
                        help="同步模式（默认 incremental）")
    parser.add_argument("--since", type=str, default=None,
                        help="增量模式的起始时间戳（ISO 格式）；不传则读 sync_watermark")
    parser.add_argument("--product-id", type=int, default=None,
                        help="--mode one 时指定的商品 id")
    parser.add_argument("--dry-run", action="store_true",
                        help="不真写 Milvus，只打印计划")
    args = parser.parse_args()

    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
