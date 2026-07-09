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

import asyncio
import json
import logging
from typing import List, Optional

from cachetools import TTLCache
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from agents.memory import (
    get_business_memory,
    remember_focused_product,
    remember_product_cards,
)
from core.database import get_session_factory
from core.llm import get_llm
from shopping.models import ShoppingIntent
from shopping.orm_models import ProductORM, ProductSkuORM

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


# ---- 商品特征抽取（compare_products 深度对比用）--------------------------

class ProductFeatures(BaseModel):
    """LLM 从商品文本中抽取的标准化特征。"""
    core_ingredients: List[str] = Field(default_factory=list, description="核心成分列表，如['烟酰胺','透明质酸']")
    concentration: str = Field(default="", description="浓度描述，如'10%'、'高浓度'、'未标明'")
    suitable_skin: List[str] = Field(default_factory=list, description="适合肤质，如['油皮','混油']")
    key_benefits: List[str] = Field(default_factory=list, description="主打功效，如['控油','淡化毛孔','提亮']")
    texture: str = Field(default="", description="质地/使用感，如'清透水润'、'滋润厚重'")
    cautions: List[str] = Field(default_factory=list, description="注意事项/禁忌，如['敏感肌先测试','含酒精']")

    @field_validator("core_ingredients", "suitable_skin", "key_benefits", "cautions", mode="before")
    @classmethod
    def _coerce_empty_str_to_list(cls, v: object) -> object:
        """LLM 有时对列表字段返回空字符串 "" 而非空列表 []，做容错转换。"""
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v


# 商品特征缓存：product_id → ProductFeatures，30 分钟 TTL，最多 200 条
_feature_cache: TTLCache = TTLCache(maxsize=200, ttl=1800)

_EXTRACT_FEATURES_PROMPT = """从以下商品信息中提取标准化特征，用 JSON 格式返回：

商品标题：{title}
品牌：{brand}
品类：{category}
描述：{description}
标签：{tags}

提取以下字段（找不到就填空字符串或空列表）：
- core_ingredients: 核心成分列表
- concentration: 浓度描述
- suitable_skin: 适合肤质列表
- key_benefits: 主打功效列表
- texture: 质地/使用感
- cautions: 注意事项/禁忌

只返回 JSON，不要额外文字。"""


async def _extract_product_features(products: List[dict]) -> dict[int, ProductFeatures]:
    """批量抽取商品特征，用 TTLCache 缓存结果。"""
    llm = get_llm()
    structured_llm = llm.with_structured_output(ProductFeatures) if llm else None

    result: dict[int, ProductFeatures] = {}
    uncached: list[dict] = []

    # 先查缓存
    for p in products:
        pid = p.get("product_id") or p.get("id")
        if pid is None:
            continue
        pid = int(pid)
        if pid in _feature_cache:
            result[pid] = _feature_cache[pid]
        else:
            uncached.append(p)

    if not uncached or structured_llm is None:
        return result

    async def _extract_one(p: dict) -> tuple[int, ProductFeatures]:
        pid = int(p.get("product_id") or p.get("id", 0))
        if pid == 0:
            return (0, ProductFeatures())
        text = _EXTRACT_FEATURES_PROMPT.format(
            title=p.get("title", ""),
            brand=p.get("brand", ""),
            category=p.get("sub_category", p.get("category", "")),
            description=(p.get("description") or "")[:800],
            tags=p.get("tags", ""),
        )
        try:
            features = await structured_llm.ainvoke(text)
            _feature_cache[pid] = features
            return (pid, features)
        except Exception:  # noqa: BLE001
            logger.warning("商品特征抽取失败 pid=%d", pid, exc_info=True)
            # 失败也缓存空对象，避免重复尝试
            empty = ProductFeatures()
            _feature_cache[pid] = empty
            return (pid, empty)

    # 并行抽取（原串行 for 循环 N 商品 = N 次串行 LLM，对比场景延迟放大 N 倍）
    outcomes = await asyncio.gather(*[_extract_one(p) for p in uncached])
    for pid, features in outcomes:
        if pid != 0:
            result[pid] = features

    return result


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


# 返回给 LLM 时的最大长度限制。description 平均占单商品 tokens 的 60%+，
# 是首轮 shopping 慢的主要来源。截断到 220 字符（≈100-140 中文 tokens）
# 既让 LLM 能看到主打卖点，又不至于把整个 detail 全塞进 LLM 上下文。
# 如果 LLM 需要完整信息，让它调 get_product_detail 二次拉取。
_DESC_MAX_LEN = 220


def _slim_for_llm(products: list[dict]) -> list[dict]:
    """把商品列表压缩成"给 LLM 看"的最小充分表示。

    首轮 shopping 慢的主因：search 返回的 20-30 个商品 JSON 里每个都带完整
    description + tags，输入 tokens 爆炸 → LLM 又要把这堆东西消化一遍再输出
    结构化 product_cards（等于重抄一遍）。

    这里做两件事：
    1. description 截断到 220 字符
    2. 去掉 review_count / image_url 这类 LLM 决策不需要的字段
       （反正 product_cards 由系统兜底填充，image_url 从 Store 里拿）
    """
    slim = []
    for p in products or []:
        desc = (p.get("description") or "")
        if len(desc) > _DESC_MAX_LEN:
            desc = desc[:_DESC_MAX_LEN] + "…"
        slim.append({
            "product_id": p.get("product_id") or p.get("id"),
            "title": p.get("title", ""),
            "brand": p.get("brand", ""),
            "price": p.get("price") or p.get("base_price"),
            "rating": p.get("rating"),
            "sales_count": p.get("sales_count"),
            "sub_category": p.get("sub_category", ""),
            "tags": p.get("tags", ""),
            "description_preview": desc,
            "reason": p.get("reason", ""),
        })
    return slim


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
    # 返回给 LLM 的是瘦身版：只保留决策必需字段，description 截断
    # 完整 cards 已经写进 Store，shopping_node 会在结束时用它兜底 product_cards
    return _slim_for_llm(results)


@tool(parse_docstring=True)
async def search_products_by_name(
    runtime: ToolRuntime,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """Search real products by exact or fuzzy product name, brand, tags, or description.

    Queries PG product table directly with ILIKE across title / brand / tags / description.

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
    return _slim_for_llm(results)


@tool(parse_docstring=True)
async def get_product_detail(runtime: ToolRuntime, product_id: int) -> dict:
    """Get detailed information for one product by product_id.

    Queries PG product table directly, plus product_sku for SKU variants.

    Args:
        product_id: Product ID to look up.
    """
    conversation_id, user_id = _runtime_context(runtime)

    session_factory = get_session_factory()
    async with session_factory() as session:
        # 查商品主表
        db_result = await session.execute(select(ProductORM).where(ProductORM.id == product_id))
        product = db_result.scalar_one_or_none()

        if not product:
            return {
                "error": True,
                "error_code": "PRODUCT_NOT_FOUND",
                "message": "Product not found",
                "product_id": product_id,
            }

        # 查 SKU 列表
        sku_result = await session.execute(
            select(ProductSkuORM).where(ProductSkuORM.product_id == product_id)
        )
        sku_rows = sku_result.scalars().all()

    data = _dump_product(product)

    # 附带 SKU 数据
    if sku_rows:
        data["skus"] = [
            {
                "id": s.id,
                "skuCode": s.sku_code or "",
                "properties": s.properties or {},
                "price": float(s.price) if s.price is not None else None,
                "stock": s.stock,
                "isDefault": s.is_default,
            }
            for s in sku_rows
        ]
    else:
        data["skus"] = []

    # images / reviews / faqs 暂未落 PG，留空列表（Java 侧开发完毕后补上）
    data["images"] = []
    data["reviews"] = []
    data["faqs"] = []

    await remember_focused_product(conversation_id, user_id, _cards_from_products([data], limit=1)[0])
    return data


@tool(parse_docstring=True)
async def list_product_skus(product_id: int) -> dict:
    """List SKUs for a product by product_id.

    Queries PG product_sku table directly.

    Args:
        product_id: Product ID.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(ProductSkuORM).where(ProductSkuORM.product_id == product_id)
        )
        rows = result.scalars().all()

    if not rows:
        return {"product_id": product_id, "skus": [], "message": "该商品暂无 SKU 数据"}

    skus = [
        {
            "id": s.id,
            "skuCode": s.sku_code or "",
            "properties": s.properties or {},
            "price": float(s.price) if s.price is not None else None,
            "stock": s.stock,
            "isDefault": s.is_default,
        }
        for s in rows
    ]
    return {"product_id": product_id, "skus": skus, "message": "OK"}


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
async def compare_products(runtime: ToolRuntime, products: Optional[List[dict]] = None) -> dict:
    """Compare products with deep feature extraction (ingredients, skin type, benefits).

    Internally calls an LLM to extract standardized features from each product's
    title/description/tags, then builds a multi-dimensional comparison table.

    If products is omitted, uses the last recommended products from memory
    (last_product_cards), so the agent can call compare_products() with no args
    when the user asks "compare those three" / "他们三比较一下".

    Args:
        products: Products to compare (usually from search_products results).
                  If omitted, reads last recommended products from memory.
    """
    items = products or []
    if not items:
        # 没传 products → 从 Store 读上轮推荐的商品（"他们三比较一下"场景）
        cid, uid = _runtime_context(runtime)
        try:
            memory = await get_business_memory(cid, uid)
            items = memory.get("last_product_cards") or []
        except Exception:  # noqa: BLE001
            logger.warning("compare_products: 读取 last_product_cards 失败", exc_info=True)
            items = []
    if not items:
        return {"task_type": "shopping", "comparisons": [], "count": 0,
                "dimensions": [], "message": "没有可对比的商品（上轮推荐记录可能已过期）。"}

    # 基础字段对比
    basic_comparisons = []
    for item in items:
        basic_comparisons.append({
            "product_id": item.get("product_id") or item.get("id"),
            "title": item.get("title") or "",
            "price": item.get("price") or item.get("base_price"),
            "rating": item.get("rating"),
            "sales_count": item.get("sales_count"),
        })

    # 深度特征抽取
    features = await _extract_product_features(items)

    # 组装多维对比
    dimensions = ["价格", "评分", "销量", "核心成分", "浓度", "适合肤质", "主打功效", "质地/使用感", "注意事项"]
    deep_comparisons = []
    for item in items:
        pid = int(item.get("product_id") or item.get("id", 0))
        f = features.get(pid, ProductFeatures())
        deep_comparisons.append({
            "product_id": pid,
            "title": item.get("title") or "",
            "price": item.get("price") or item.get("base_price"),
            "rating": item.get("rating"),
            "sales_count": item.get("sales_count"),
            "core_ingredients": f.core_ingredients,
            "concentration": f.concentration,
            "suitable_skin": f.suitable_skin,
            "key_benefits": f.key_benefits,
            "texture": f.texture,
            "cautions": f.cautions,
        })

    return {
        "task_type": "shopping",
        "comparisons": deep_comparisons,
        "basic_comparisons": basic_comparisons,
        "count": len(deep_comparisons),
        "dimensions": dimensions,
    }


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
