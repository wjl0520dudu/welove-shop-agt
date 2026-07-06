"""ShoppingAgent 工具集（ToolRuntime 模式，教程 05）。

工具是**模块级常量**，不再每次请求重建。
`conversation_id` / `user_id` 通过 `runtime.state` 传入（不再用闭包捕获）。

## 为什么用 parse_docstring 而不是 args_schema
`ToolRuntime` 是 LangGraph 特殊注入参数，必须让 `@tool` 装饰器识别它。
用 `args_schema=XxxInput` 会强制走 pydantic schema，`runtime` 参数无法被识别 →
调用时 "missing 1 required positional argument: 'runtime'"。
`parse_docstring=True` 让 `@tool` 从函数签名+docstring 自动推导 schema，
自动把 `runtime: ToolRuntime` 排除在 LLM 可见的 args 之外。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from sqlalchemy import or_, select

from agents.memory import remember_focused_product, remember_product_cards
from core.database import get_session_factory
from shopping.models import ShoppingIntent
from shopping.orm_models import ProductORM

logger = logging.getLogger("ai-service.shopping_tools")


# ---- 懒加载单例 -----------------------------------------------------------

_pg_vector_store = None
_product_repository = None


def _get_pg_vector_store():
    """懒加载 PgVectorStore 单例。第一次调用时才 import + 建实例。

    pgvector / asyncpg 包未安装时抛 ImportError，由调用方捕获后回退到 MySQL LIKE。
    放在函数内而非模块顶层，避免 app 启动时因缺依赖而整体 import 失败。
    """
    global _pg_vector_store
    if _pg_vector_store is None:
        from pg_search.pgvector_store import PgVectorStore
        _pg_vector_store = PgVectorStore()
    return _pg_vector_store


def _get_repository():
    """懒加载 ProductRepository 单例（MySQL LIKE 回退用）。"""
    global _product_repository
    if _product_repository is None:
        from shopping.product_repository import ProductRepository
        _product_repository = ProductRepository()
    return _product_repository


# ---- 内部 helper ---------------------------------------------------------

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


def _runtime_context(runtime: ToolRuntime) -> tuple[Optional[str], Optional[int | str]]:
    """从 ToolRuntime.state 读 conversation_id / user_id。

    ShoppingAgentState 里定义了这两个字段，agent.ainvoke 时会作为初始 state 传入。
    """
    state = runtime.state or {}
    return state.get("conversation_id"), state.get("user_id")


# ---- 工具（模块级常量，agent 里直接 import 使用）---------------------------

@tool(parse_docstring=True)
async def search_products(
    runtime: ToolRuntime,
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
    """Search real products using vector semantic search + SQL filtering.

    Uses pgvector for embedding-based semantic recall combined with
    exact SQL filters (price, brand, exclude) in a single query.

    Args:
        category: Product category (e.g. 粉底液, 面霜).
        brand: Brand name filter.
        budget_min: Minimum price.
        budget_max: Maximum price.
        target_user: Target user group (e.g. 干皮, 敏感肌).
        scenario: Usage scenario (e.g. 通勤, 派对).
        preferences: Positive preference keywords.
        avoid: Negative preference keywords to exclude.
        limit: Max number of results (default 6).
    """
    conversation_id, user_id = _runtime_context(runtime)

    # 构建搜索查询文本：偏好 + 场景 + 品类
    query_parts = []
    if preferences:
        query_parts.extend(preferences)
    if scenario:
        query_parts.append(scenario)
    if target_user:
        query_parts.append(target_user)
    if category:
        query_parts.append(category)
    search_query = " ".join(query_parts) if query_parts else (category or "")

    try:
        pg_vector = _get_pg_vector_store()
        results = await pg_vector.search(
            query=search_query,
            top_k=limit * 3,
            category=category,
            brand=brand,
            budget_min=budget_min,
            budget_max=budget_max,
            preferences=preferences,
            avoid=avoid,
            limit=limit,
        )
    except Exception:
        logger.warning("pgvector search failed, falling back to MySQL LIKE", exc_info=True)
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
        products = await _get_repository().search_products(intent, limit=limit)
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
        await remember_product_cards(conversation_id, user_id, _cards_from_products(results))
    return results


@tool(parse_docstring=True)
async def search_products_by_name(
    runtime: ToolRuntime,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """Search real products by exact or fuzzy product name, brand, tags, or description.

    Args:
        query: Product name, brand, or natural language product query.
        limit: Max number of results (default 5).
    """
    conversation_id, user_id = _runtime_context(runtime)

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
        await remember_product_cards(conversation_id, user_id, _cards_from_products(results))
        await remember_focused_product(conversation_id, user_id, _cards_from_products(results, limit=1)[0])
    return results


@tool(parse_docstring=True)
async def get_product_detail(runtime: ToolRuntime, product_id: int) -> dict:
    """Get detailed information for one product by product_id.

    Args:
        product_id: Product ID to look up.
    """
    conversation_id, user_id = _runtime_context(runtime)

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(ProductORM).where(ProductORM.id == product_id))
        product = result.scalar_one_or_none()
    if not product:
        return {"error": True, "error_code": "PRODUCT_NOT_FOUND", "message": "Product not found", "product_id": product_id}
    data = _dump_product(product)
    await remember_focused_product(conversation_id, user_id, _cards_from_products([data], limit=1)[0])
    return data


@tool(parse_docstring=True)
async def list_product_skus(product_id: int) -> dict:
    """List product SKUs. Currently not implemented in Python service.

    Args:
        product_id: Product ID.
    """
    return {"product_id": product_id, "skus": [], "message": "SKU data is not available in ai-service yet."}


@tool(parse_docstring=True)
async def build_product_cards(
    runtime: ToolRuntime,
    products: List[dict],
    limit: int = 3,
) -> dict:
    """Build frontend product_cards from products selected by the agent.

    Args:
        products: Products returned by other product tools.
        limit: Max number of cards to build (default 3).
    """
    conversation_id, user_id = _runtime_context(runtime)

    cards = _cards_from_products(products, limit)
    await remember_product_cards(conversation_id, user_id, cards)
    return {"task_type": "shopping", "product_cards": cards, "answer": "已根据你的需求整理了商品卡片。"}


@tool(parse_docstring=True)
async def compare_products(products: List[dict]) -> dict:
    """Compare products using factual fields already returned by tools.

    Args:
        products: Products to compare.
    """
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


# ---- 模块级工具列表 -------------------------------------------------------

SHOPPING_TOOLS = [
    search_products,
    search_products_by_name,
    get_product_detail,
    list_product_skus,
    build_product_cards,
    compare_products,
]


# ---- 向后兼容包装 --------------------------------------------------------
# 老代码用 build_shopping_tools(repository, memory_context) 得到工具列表。
# 新架构下工具是模块级的，repository 通过 _get_repository() 懒加载。
# 保留旧签名让老测试和 build_search_products_tool() 无需改动。

def build_shopping_tools(repository=None, memory_context=None):
    """已废弃：现在工具是模块级 SHOPPING_TOOLS，无需按上下文重建。

    保留这个函数是为了兼容旧测试和 build_search_products_tool()。
    repository / memory_context 参数会被忽略（新工具用懒加载 + ToolRuntime）。
    """
    return SHOPPING_TOOLS


def build_search_products_tool(repository=None):
    """Backward-compatible single-tool factory used by older tests and chains."""
    return search_products
