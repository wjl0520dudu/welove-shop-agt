from __future__ import annotations

from typing import List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from agents.memory import remember_focused_product, remember_product_cards
from core.database import get_session_factory
from shopping.models import ShoppingIntent
from shopping.orm_models import ProductORM


class SearchProductsInput(BaseModel):
    category: Optional[str] = Field(default=None, description="Product category")
    brand: Optional[str] = Field(default=None, description="Brand")
    budget_min: Optional[float] = Field(default=None, description="Minimum budget")
    budget_max: Optional[float] = Field(default=None, description="Maximum budget")
    target_user: Optional[str] = Field(default=None, description="Target user group")
    scenario: Optional[str] = Field(default=None, description="Usage scenario")
    preferences: List[str] = Field(default_factory=list, description="Positive preferences")
    avoid: List[str] = Field(default_factory=list, description="Negative preferences")
    limit: int = Field(default=6, ge=1, le=20, description="Result limit")


class SearchProductsByNameInput(BaseModel):
    query: str = Field(..., description="Product name, brand, or natural language product query")
    limit: int = Field(default=5, ge=1, le=20, description="Result limit")


class ProductIdInput(BaseModel):
    product_id: int = Field(..., description="Product ID")


class ProductCardsInput(BaseModel):
    products: List[dict] = Field(default_factory=list, description="Products returned by product tools")
    limit: int = Field(default=3, ge=1, le=10, description="Card limit")


class CompareProductsInput(BaseModel):
    products: List[dict] = Field(default_factory=list, description="Products to compare")


def _dump_product(product: ProductORM) -> dict:
    return {
        "product_id": int(product.id),
        "title": product.title or "",
        "brand": product.brand or "",
        "price": float(product.base_price) if product.base_price is not None else None,
        "base_price": float(product.base_price) if product.base_price is not None else None,
        "image_url": product.image_url or "",
        "rating": float(product.rating) if product.rating is not None else None,
        "review_count": int(product.review_count or 0),
        "sales_count": int(product.sales_count or 0),
        "sub_category": product.sub_category or "",
        "tags": product.tags or "",
        "description": product.description or "",
    }


def _cards_from_products(products: List[dict], limit: int = 3) -> list[dict]:
    cards = []
    for item in (products or [])[:limit]:
        cards.append(
            {
                "product_id": item.get("product_id") or item.get("id"),
                "title": item.get("title") or "",
                "brand": item.get("brand") or "",
                "price": item.get("price") or item.get("base_price") or 0,
                "base_price": item.get("base_price") or item.get("price"),
                "image_url": item.get("image_url") or "",
                "rating": item.get("rating") or 0,
                "sales_count": item.get("sales_count") or 0,
                "sub_category": item.get("sub_category") or "",
                "reason": item.get("reason") or "根据你的需求匹配到的商品。",
            }
        )
    return cards


def build_shopping_tools(repository, memory_context: Optional[dict] = None):
    memory_context = memory_context or {}
    conversation_id = memory_context.get("conversation_id")
    user_id = memory_context.get("user_id")

    @tool(args_schema=SearchProductsInput)
    async def search_products(
        category: Optional[str] = None,
        brand: Optional[str] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        target_user: Optional[str] = None,
        scenario: Optional[str] = None,
        preferences: Optional[List[str]] = None,
        avoid: Optional[List[str]] = None,
        limit: int = 6,
    ) -> list[dict]:
        """Search real products from the product repository based on shopping requirements."""
        intent = ShoppingIntent(
            is_shopping_request=True,
            category=category,
            brand=brand,
            budget_min=budget_min,
            budget_max=budget_max,
            target_user=target_user,
            scenario=scenario,
            preferences=preferences or [],
            avoid=avoid or [],
        )
        products = await repository.search_products(intent, limit=limit)
        results = [
            {
                "product_id": item.product_id,
                "title": item.title,
                "brand": item.brand,
                "price": item.price,
                "base_price": item.base_price,
                "rating": item.rating,
                "sales_count": item.sales_count,
                "category": item.category,
                "sub_category": item.sub_category,
                "image_url": item.image_url,
                "reason": item.reason,
            }
            for item in products
        ]
        if results:
            remember_product_cards(conversation_id, user_id, _cards_from_products(results))
        return results

    @tool(args_schema=SearchProductsByNameInput)
    async def search_products_by_name(query: str, limit: int = 5) -> list[dict]:
        """Search real products by exact or fuzzy product name, brand, tags, or description."""
        clean_query = (query or "").strip()
        if not clean_query:
            return []
        like = f"%{clean_query}%"
        stmt = (
            select(ProductORM)
            .where(ProductORM.status == 1)
            .where(
                or_(
                    ProductORM.title.like(like),
                    ProductORM.brand.like(like),
                    ProductORM.tags.like(like),
                    ProductORM.description.like(like),
                )
            )
            .order_by(ProductORM.sales_count.desc(), ProductORM.rating.desc())
            .limit(limit)
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
        results = [_dump_product(product) for product in rows]
        if results:
            remember_product_cards(conversation_id, user_id, _cards_from_products(results))
            remember_focused_product(conversation_id, user_id, _cards_from_products(results, limit=1)[0])
        return results

    @tool(args_schema=ProductIdInput)
    async def get_product_detail(product_id: int) -> dict:
        """Get detailed information for one product by product_id."""
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(select(ProductORM).where(ProductORM.id == product_id))
            product = result.scalar_one_or_none()
        if not product:
            return {"error": True, "error_code": "PRODUCT_NOT_FOUND", "message": "Product not found", "product_id": product_id}
        data = _dump_product(product)
        remember_focused_product(conversation_id, user_id, _cards_from_products([data], limit=1)[0])
        return data

    @tool(args_schema=ProductIdInput)
    async def list_product_skus(product_id: int) -> dict:
        """List product SKUs. Current Python service has no SKU table mapping; use Java product API in a later iteration."""
        return {"product_id": product_id, "skus": [], "message": "SKU data is not available in ai-service yet."}

    @tool(args_schema=ProductCardsInput)
    async def build_product_cards(products: List[dict], limit: int = 3) -> dict:
        """Build frontend product_cards from products selected by the agent."""
        cards = _cards_from_products(products, limit)
        remember_product_cards(conversation_id, user_id, cards)
        return {"task_type": "shopping", "product_cards": cards, "answer": "已根据你的需求整理了商品卡片。"}

    @tool(args_schema=CompareProductsInput)
    async def compare_products(products: List[dict]) -> dict:
        """Compare products using factual fields already returned by tools."""
        comparisons = []
        for item in products or []:
            comparisons.append(
                {
                    "product_id": item.get("product_id") or item.get("id"),
                    "title": item.get("title") or "",
                    "price": item.get("price") or item.get("base_price"),
                    "rating": item.get("rating"),
                    "sales_count": item.get("sales_count"),
                    "reason": item.get("reason") or "",
                }
            )
        return {"task_type": "shopping", "comparisons": comparisons, "count": len(comparisons)}

    return [search_products, search_products_by_name, get_product_detail, list_product_skus, build_product_cards, compare_products]


def build_search_products_tool(repository):
    """Backward-compatible single-tool factory used by older tests and chains."""
    return build_shopping_tools(repository)[0]