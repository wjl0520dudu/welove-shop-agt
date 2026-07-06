"""
验证 pgvector 商品搜索效果

用法：
    cd backend/ai-service
    python scripts/verify_pgvector.py
    python scripts/verify_pgvector.py --query "油皮控油散粉"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pg_search.pgvector_store import PgVectorStore
from pg_search.engine import get_pg_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("verify_pgvector")

DEFAULT_QUERIES = [
    "干皮适合的保湿粉底液",
    "控油散粉定妆",
    "性价比高的面霜",
    "敏感肌防晒霜",
]


async def verify(query: str | None = None):
    store = PgVectorStore()

    # 1. 基本统计
    stats = await store.stats()
    total = stats.get("total_products", 0)
    logger.info("pgvector 统计: total=%s", total)

    if total == 0:
        logger.error("pgvector 中没有商品数据！请先运行 scripts/build_product_embeddings.py")
        return

    # 2. 语义搜索
    queries = [query] if query else DEFAULT_QUERIES
    for q in queries:
        logger.info("=" * 60)
        logger.info("搜索: %s", q)
        results = await store.search(q, top_k=5)
        if not results:
            logger.info("  (无结果)")
            continue
        for r in results:
            logger.info(
                "  [%s] %s | ¥%s | 评分:%s | 销量:%s",
                r.get("product_id"),
                r.get("title", "")[:40],
                r.get("base_price"),
                r.get("rating"),
                r.get("sales_count"),
            )

    # 3. 过滤搜索测试
    logger.info("=" * 60)
    logger.info("过滤搜索: 保湿 + 预算 ≤ 200")
    results = await store.search("保湿", top_k=5, budget_max=200)
    for r in results:
        logger.info(
            "  [%s] %s | ¥%s | 评分:%s",
            r.get("product_id"),
            r.get("title", "")[:40],
            r.get("base_price"),
            r.get("rating"),
        )

    # 清理连接
    await get_pg_session_factory().bind.dispose()


def main():
    parser = argparse.ArgumentParser(description="验证 pgvector 商品搜索")
    parser.add_argument("--query", "-q", type=str, help="指定搜索词（不传则跑默认测试集）")
    args = parser.parse_args()
    asyncio.run(verify(query=args.query))


if __name__ == "__main__":
    main()
