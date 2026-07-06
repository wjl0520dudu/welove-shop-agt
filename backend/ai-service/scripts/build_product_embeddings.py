"""
商品向量化导入脚本

从 MySQL 读取所有 status=1 的商品，生成 embedding 写入 pgvector。

用法：
    cd backend/ai-service
    python scripts/build_product_embeddings.py               # 全量导入
    python scripts/build_product_embeddings.py --dry-run     # 预览
    python scripts/build_product_embeddings.py --batch 50    # 指定批次大小
    python scripts/build_product_embeddings.py --ids 1,2,3   # 只导入指定商品
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 添加 ai-service 到路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from core.database import get_session_factory
from core.llm import get_embeddings_model
from pg_search.engine import get_pg_session_factory
from pg_search.orm import ProductSearchORM
from shopping.orm_models import ProductORM

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_product_embeddings")


def build_product_text(product: ProductORM) -> str:
    """构造商品嵌入文本：标题 + 标签 + 描述 + 子品类。"""
    parts = [
        product.title or "",
        product.tags or "",
        product.description or "",
        product.sub_category or "",
    ]
    return " ".join(p for p in parts if p)


async def build_embeddings(
    batch_size: int = 50,
    dry_run: bool = False,
    product_ids: list[int] | None = None,
) -> dict:
    """主流程：读取 MySQL 商品 → embed → 写入 pgvector。"""
    mysql_factory = get_session_factory()
    pg_factory = get_pg_session_factory()
    embeddings_model = get_embeddings_model()

    # 1. 从 MySQL 读取商品
    async with mysql_factory() as session:
        stmt = select(ProductORM).where(ProductORM.status == 1)
        if product_ids:
            stmt = stmt.where(ProductORM.id.in_(product_ids))
        result = await session.execute(stmt)
        products = result.scalars().all()

    if not products:
        logger.info("没有找到需要向量化的商品")
        return {"total": 0, "embedded": 0, "skipped": 0}

    logger.info("共 %d 个商品待向量化", len(products))

    if dry_run:
        for p in products[:5]:
            text = build_product_text(p)
            logger.info("  [DRY RUN] id=%d title=%s text_len=%d", p.id, p.title, len(text))
        if len(products) > 5:
            logger.info("  ... 还有 %d 个商品", len(products) - 5)
        return {"total": len(products), "embedded": 0, "skipped": 0, "dry_run": True}

    # 2. 分批生成 embedding 并写入 pgvector
    embedded = 0
    skipped = 0

    for i in range(0, len(products), batch_size):
        batch = products[i : i + batch_size]
        texts = [build_product_text(p) for p in batch]

        # 生成 embedding
        vectors = await embeddings_model.aembed_documents(texts)

        # 构造 pgvector 数据
        pg_items = []
        for product, vector in zip(batch, vectors):
            pg_items.append(
                {
                    "id": product.id,
                    "title": product.title or "",
                    "brand": product.brand,
                    "category_name": None,  # 从 category 关联查询在批量场景太慢，用 category_id 即可
                    "sub_category": product.sub_category,
                    "base_price": float(product.base_price) if product.base_price else None,
                    "image_url": product.image_url,
                    "rating": float(product.rating) if product.rating else None,
                    "review_count": product.review_count,
                    "sales_count": product.sales_count,
                    "tags": product.tags,
                    "description": product.description,
                    "status": product.status,
                    "embedding": vector,
                }
            )

        # 写入 pgvector
        async with pg_factory() as pg_session:
            for item in pg_items:
                existing = await pg_session.get(ProductSearchORM, item["id"])
                if existing:
                    for key, value in item.items():
                        if hasattr(existing, key) and key != "id":
                            setattr(existing, key, value)
                else:
                    pg_session.add(ProductSearchORM(**item))
            await pg_session.commit()

        # 更新 MySQL embedding_status
        async with mysql_factory() as mysql_session:
            for product in batch:
                p = await mysql_session.get(ProductORM, product.id)
                if p:
                    p.embedding_status = 1
            await mysql_session.commit()

        embedded += len(batch)
        logger.info(
            "  批次 %d/%d: %d 个商品已写入 pgvector",
            i // batch_size + 1,
            (len(products) + batch_size - 1) // batch_size,
            len(batch),
        )

    # 显式释放引擎连接池，避免 Windows ProactorEventLoop 关闭后的 aiomysql 清理警告
    await get_session_factory().bind.dispose()
    await get_pg_session_factory().bind.dispose()

    return {"total": len(products), "embedded": embedded, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description="商品向量化导入 pgvector")
    parser.add_argument("--batch", type=int, default=50, help="批次大小 (默认 50)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    parser.add_argument("--ids", type=str, help="只导入指定商品 ID，逗号分隔 (如 1,2,3)")
    args = parser.parse_args()

    product_ids = None
    if args.ids:
        product_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]

    result = asyncio.run(
        build_embeddings(
            batch_size=args.batch,
            dry_run=args.dry_run,
            product_ids=product_ids,
        )
    )

    logger.info("完成: total=%d embedded=%d skipped=%d", result["total"], result["embedded"], result["skipped"])


if __name__ == "__main__":
    main()
