from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Callable, List, Optional

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session_factory
from shopping.models import ProductCandidate, ShoppingIntent
from shopping.orm_models import CategoryORM, ProductORM, RecommendationLogORM

logger = logging.getLogger("ai-service.shopping")


class ProductRepository:
    """商品查询仓储层。

    这里只做数据库访问，不调用 LLM，不生成推荐话术。
    """

    def __init__(self, session_factory: Optional[Callable[[], AsyncSession]] = None):
        self.session_factory = session_factory or get_session_factory()

    async def search_products(
        self,
        intent: ShoppingIntent,
        limit: int = 6,
    ) -> List[ProductCandidate]:
        """根据结构化导购意图查询商品。"""

        stmt = (
            select(ProductORM, CategoryORM.name.label("category_name"))
            .outerjoin(CategoryORM, ProductORM.category_id == CategoryORM.id)
            .where(ProductORM.status == 1)
        )

        if intent.category:
            category_like = f"%{intent.category}%"
            stmt = stmt.where(
                or_(
                    CategoryORM.name.like(category_like),
                    ProductORM.sub_category.like(category_like),
                    ProductORM.title.like(category_like),
                    ProductORM.tags.like(category_like),
                    ProductORM.description.like(category_like),
                )
            )

        if intent.brand:
            stmt = stmt.where(ProductORM.brand.like(f"%{intent.brand}%"))

        if intent.budget_min is not None:
            stmt = stmt.where(ProductORM.base_price >= intent.budget_min)

        if intent.budget_max is not None:
            stmt = stmt.where(ProductORM.base_price <= intent.budget_max)

        soft_terms = [
            term
            for term in [intent.scenario, intent.target_user, *intent.preferences]
            if term
        ][:8]
        if soft_terms and not intent.category:
            stmt = stmt.where(or_(*[self._matches_product_text(term) for term in soft_terms]))

        for avoided in intent.avoid[:5]:
            like = f"%{avoided}%"
            stmt = stmt.where(
                and_(
                    not_(ProductORM.title.like(like)),
                    or_(ProductORM.tags.is_(None), not_(ProductORM.tags.like(like))),
                    or_(ProductORM.description.is_(None), not_(ProductORM.description.like(like))),
                )
            )

        stmt = stmt.order_by(
            ProductORM.sales_count.desc(),
            ProductORM.rating.desc(),
            ProductORM.review_count.desc(),
        ).limit(limit)

        async with self.session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [self._row_to_candidate(product, category_name) for product, category_name in rows]

    @staticmethod
    def _matches_product_text(term: str):
        like = f"%{term}%"
        return or_(
            CategoryORM.name.like(like),
            ProductORM.sub_category.like(like),
            ProductORM.title.like(like),
            ProductORM.tags.like(like),
            ProductORM.description.like(like),
        )

    def _row_to_candidate(self, product: ProductORM, category_name: Optional[str]) -> ProductCandidate:
        """把 ORM 对象转换成稳定模型。"""

        price = self._to_float(product.base_price)
        return ProductCandidate(
            product_id=int(product.id),
            title=product.title or "",
            brand=product.brand or "",
            price=price,
            base_price=price,
            image_url=product.image_url or "",
            rating=self._to_float(product.rating) or 0,
            review_count=self._to_int(product.review_count) or 0,
            sales_count=self._to_int(product.sales_count) or 0,
            category=category_name or "",
            sub_category=product.sub_category or "",
            tags=product.tags or "",
            description=product.description or "",
        )

    async def log_recommendation(
        self,
        user_id: Optional[int],
        question: str,
        product_ids: List[int],
        session_id: Optional[str] = None,
        intent: Optional[str] = "shopping",
        recommend_reason: Optional[str] = None,
    ) -> None:
        """记录推荐日志。"""

        log = RecommendationLogORM(
            user_id=user_id,
            session_id=session_id,
            query=question,
            intent=intent,
            recommended_product_ids=product_ids,
            recommend_reason=recommend_reason,
        )
        async with self.session_factory() as session:
            session.add(log)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Failed to save recommendation log")
                raise

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        return int(value)
