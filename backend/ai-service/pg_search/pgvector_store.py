"""PgVectorStore — 商品向量语义检索。

接口参考 rag/vector_store.py 的 MilvusVectorStore，提供：
- search: 向量召回 + SQL 精确过滤（一条 SQL 完成）
- upsert_products: 批量 upsert 商品向量
- delete_by_id: 按 product_id 删除
- stats: 统计信息
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, not_, or_, select, text
from sqlalchemy.sql import func

from core.config import config
from core.llm import get_embeddings_model
from pg_search.engine import get_pg_session_factory
from pg_search.orm import ProductSearchORM

logger = logging.getLogger("ai-service.pg_search")


class PgVectorStore:
    """pgvector 商品向量检索器。

    在同一条 SQL 里完成向量召回 + 关系过滤 + 聚合排序，
    不需要跨库拼接。
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_pg_session_factory()
        self._embeddings = None
        self._embedding_dim = 1536  # text-embedding-3-small

    def _get_embeddings(self):
        if self._embeddings is None:
            self._embeddings = get_embeddings_model()
        return self._embeddings

    async def _embed_query(self, query: str) -> list[float]:
        embeddings = self._get_embeddings()
        return await embeddings.aembed_query(query)

    async def search(
        self,
        query: str,
        top_k: int = 10,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        preferences: Optional[List[str]] = None,
        avoid: Optional[List[str]] = None,
        limit: int = 6,
    ) -> list[dict]:
        """向量语义召回 + SQL 精确过滤。

        Args:
            query: 用户查询文本（用于生成 embedding）
            top_k: 向量召回候选数
            category: 品类过滤（可选，用于精确匹配辅助召回）
            brand: 品牌过滤
            budget_min: 最低价格
            budget_max: 最高价格
            preferences: 偏好关键词（参与搜索文本构建）
            avoid: 排除关键词（SQL NOT LIKE）
            limit: 最终返回数量

        Returns:
            商品 dict 列表，含 distance 字段
        """
        # 构建搜索文本：preferences + query
        search_text = query
        if preferences:
            search_text = " ".join(preferences) + " " + query

        query_vec = await self._embed_query(search_text)

        async with self._session_factory() as session:
            # 用 pgvector 的 <=> 运算符做余弦距离排序
            distance_expr = ProductSearchORM.embedding.cosine_distance(query_vec)
            stmt = (
                select(
                    ProductSearchORM,
                    distance_expr.label("distance"),
                )
                .where(ProductSearchORM.status == 1)
            )

            # 精确过滤
            if category:
                category_like = f"%{category}%"
                stmt = stmt.where(
                    or_(
                        ProductSearchORM.category_name.ilike(category_like),
                        ProductSearchORM.sub_category.ilike(category_like),
                        ProductSearchORM.title.ilike(category_like),
                        ProductSearchORM.tags.ilike(category_like),
                    )
                )

            if brand:
                stmt = stmt.where(ProductSearchORM.brand.ilike(f"%{brand}%"))

            if budget_min is not None:
                stmt = stmt.where(ProductSearchORM.base_price >= budget_min)

            if budget_max is not None:
                stmt = stmt.where(ProductSearchORM.base_price <= budget_max)

            # 排除关键词
            for term in (avoid or [])[:5]:
                like = f"%{term}%"
                stmt = stmt.where(
                    and_(
                        not_(ProductSearchORM.title.ilike(like)),
                        or_(
                            ProductSearchORM.tags.is_(None),
                            not_(ProductSearchORM.tags.ilike(like)),
                        ),
                        or_(
                            ProductSearchORM.description.is_(None),
                            not_(ProductSearchORM.description.ilike(like)),
                        ),
                    )
                )

            # 向量距离排序 + 销量/评分辅助排序
            stmt = stmt.order_by(
                distance_expr.asc(),
                ProductSearchORM.sales_count.desc(),
                ProductSearchORM.rating.desc(),
            ).limit(max(top_k, limit * 3))

            result = await session.execute(stmt)
            rows = result.all()

        # 转为 dict 列表
        products = []
        for product, distance in rows:
            products.append(
                {
                    "product_id": product.id,
                    "title": product.title or "",
                    "brand": product.brand or "",
                    "price": product.base_price,
                    "base_price": product.base_price,
                    "image_url": product.image_url or "",
                    "rating": product.rating,
                    "review_count": product.review_count or 0,
                    "sales_count": product.sales_count or 0,
                    "category": product.category_name or "",
                    "sub_category": product.sub_category or "",
                    "tags": product.tags or "",
                    "description": product.description or "",
                    "distance": float(distance) if distance is not None else 1.0,
                }
            )

        # 二次排序：距离 + 销量 + 评分
        products.sort(
            key=lambda p: (
                p["distance"],
                -(p["sales_count"] or 0),
                -(p["rating"] or 0),
            )
        )

        return products[:limit]

    async def upsert_products(self, products: list[dict]) -> int:
        """批量 upsert 商品向量。

        Args:
            products: 商品 dict 列表，每个必须含 id + embedding 字段

        Returns:
            写入数量
        """
        if not products:
            return 0

        async with self._session_factory() as session:
            for item in products:
                existing = await session.get(ProductSearchORM, item["id"])
                if existing:
                    # 更新
                    for key, value in item.items():
                        if hasattr(existing, key) and key != "id":
                            setattr(existing, key, value)
                    existing.updated_at = func.now()
                else:
                    # 插入
                    orm_item = ProductSearchORM(
                        id=item["id"],
                        title=item.get("title", ""),
                        brand=item.get("brand"),
                        category_name=item.get("category_name") or item.get("category"),
                        sub_category=item.get("sub_category"),
                        base_price=item.get("base_price") or item.get("price"),
                        image_url=item.get("image_url"),
                        rating=item.get("rating"),
                        review_count=item.get("review_count"),
                        sales_count=item.get("sales_count"),
                        tags=item.get("tags"),
                        description=item.get("description"),
                        status=item.get("status", 1),
                        embedding=item["embedding"],
                    )
                    session.add(orm_item)

            await session.commit()

        return len(products)

    async def delete_by_id(self, product_id: int) -> bool:
        """按 product_id 删除商品向量。"""
        async with self._session_factory() as session:
            product = await session.get(ProductSearchORM, product_id)
            if product is None:
                return False
            await session.delete(product)
            await session.commit()
        return True

    async def stats(self) -> dict[str, Any]:
        """统计信息。"""
        async with self._session_factory() as session:
            count_stmt = select(func.count()).select_from(ProductSearchORM)
            result = await session.execute(count_stmt)
            total = result.scalar() or 0
        return {
            "provider": "pgvector",
            "total": total,
            "total_products": total,
            "embedding_dim": self._embedding_dim,
        }
