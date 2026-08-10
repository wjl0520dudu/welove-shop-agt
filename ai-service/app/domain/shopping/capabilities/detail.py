"""DetailCapability —— 单商品详情追问。

## Pipeline
```
resolve_single_product(query, product_id, context)
  ↓ 未找到 → clarify
load_product_detail(pid)             (复用 tools.shopping_tools 内部逻辑)
  ↓
build_complete_facts(product)
  ↓
DetailToolResult
```

旧回滚 Tool 返回完整商品事实，不再通过关键词 focus 限制详情问法。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.domain.shopping.cards import build_product_card_from_detail
from app.domain.shopping.schemas import DetailToolResult, ShoppingContext

logger = logging.getLogger("ai-service.shopping.detail")


def _resolve_product_id(
    query: str,
    product_id: Optional[int],
    ctx: ShoppingContext,
) -> Optional[int]:
    """Return a Router-bound product id and never parse history locally."""
    del query  # Router already resolves cross-turn references before this tool.
    bound_ids: list[int] = []
    for value in ctx.selected_product_ids:
        try:
            bound_id = int(value)
        except (TypeError, ValueError):
            continue
        if bound_id > 0 and bound_id not in bound_ids:
            bound_ids.append(bound_id)

    if product_id is not None:
        try:
            requested = int(product_id)
        except (TypeError, ValueError):
            return None
        return requested if requested in bound_ids else None
    return bound_ids[0] if len(bound_ids) == 1 else None


async def _load_product_detail_raw(product_id: int) -> Dict[str, Any]:
    """加载单个商品的主档 + SKU。

    Phase 1b 起分工：
    - **主档**（title/brand/price/description/tags/image/rating 等）从 **Milvus** 读，
      因为商品数据已从 pgvector 迁到 product_mm_collection。PG 主库暂时可能没有对应 row
      （合成 product_id 映射 100001~ 只写进了 Milvus）。
    - **SKU 列表**从 **PG** 读（如果表里有），供 focus=price/stock/sku 用；
      PG 里没这个商品的 SKU 就返回空列表 —— 上层根据 facts["skus"] 是否为空决定
      是否报"暂无 SKU"。
    """
    from app.infrastructure.vectorstores.product.active_store import (
        get_active_product_store as get_product_milvus_store,
    )

    # ── 1. 从 Milvus 拿主档 ──
    try:
        store = get_product_milvus_store()
        # Milvus query 走 filter 精确 lookup，用 product_id 主键
        from pymilvus import Collection
        collection = Collection(store.collection_name)
        collection.load()
        rows = collection.query(
            expr=f"product_id == {int(product_id)}",
            output_fields=[
                "product_id", "title", "brand", "image_url", "description",
                "category", "sub_category", "tags",
                "base_price", "rating", "sales_count", "review_count", "status",
            ],
            limit=1,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Milvus query 商品主档失败 product_id=%s", product_id, exc_info=True)
        rows = []

    if not rows:
        return {}

    r = rows[0]
    base_price = float(r.get("base_price") or 0)
    data: Dict[str, Any] = {
        "product_id": int(r.get("product_id") or product_id),
        "title": r.get("title") or "",
        "brand": r.get("brand") or "",
        "price": base_price,
        "base_price": base_price,
        "image_url": r.get("image_url") or "",
        "description": r.get("description") or "",
        "category": r.get("category") or "",
        "sub_category": r.get("sub_category") or "",
        "tags": r.get("tags") or "",
        "rating": float(r.get("rating") or 0),
        "sales_count": int(r.get("sales_count") or 0),
        "review_count": int(r.get("review_count") or 0),
        "status": int(r.get("status") or 0),
    }

    # ── 2. SKU 从 PG 读（有就带上，没有留空）──
    try:
        from sqlalchemy import select
        from app.infrastructure.persistence.database import get_session_factory
        from app.infrastructure.persistence.orm_models import ProductSkuORM

        session_factory = get_session_factory()
        async with session_factory() as session:
            sku_rows = (await session.execute(
                select(ProductSkuORM).where(ProductSkuORM.product_id == product_id)
            )).scalars().all()
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
    except Exception:  # noqa: BLE001
        logger.warning("PG SKU 查询失败 product_id=%s，SKU 留空", product_id, exc_info=True)
        data["skus"] = []

    return data


def _build_complete_facts(product: Dict[str, Any]) -> Dict[str, Any]:
    """Return all trusted fields so the Agent can answer open detail questions."""
    skus: List[Dict[str, Any]] = product.get("skus") or []
    prices = [sku["price"] for sku in skus if sku.get("price") is not None]
    total_stock = sum(int(sku.get("stock") or 0) for sku in skus)
    return {
        "price": product.get("price"),
        "base_price": product.get("base_price"),
        "sku_price_range": (min(prices), max(prices)) if prices else None,
        "skus": skus,
        "sku_count": len(skus),
        "total_stock": total_stock,
        "in_stock": total_stock > 0 if skus else None,
        "description": product.get("description") or "",
        "tags": product.get("tags") or "",
        "rating": product.get("rating"),
        "sales_count": product.get("sales_count"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "sub_category": product.get("sub_category"),
    }


class DetailCapability:
    async def run(
        self,
        query: str,
        context: ShoppingContext,
        product_id: Optional[int] = None,
    ) -> DetailToolResult:
        trace: List[Dict[str, Any]] = []

        pid = _resolve_product_id(query, product_id, context)
        del query  # The Agent understands the open detail question.
        trace.append({"step": "resolve_product", "output": {"product_id": pid}})
        if pid is None:
            return DetailToolResult(
                action="clarify",
                clarify_question=(
                    "你想了解哪个商品呢？可以告诉我商品名，或者说「第一个/第二个」，"
                    "我按上轮推荐给你查。"
                ),
                trace=trace,
            )

        product = await _load_product_detail_raw(pid)
        if not product or (product.get("status") is not None and int(product.get("status") or 0) != 1):
            return DetailToolResult(
                action="empty",
                empty_reason=f"商品 {pid} 不存在或已下架。",
                trace=trace,
            )
        trace.append({"step": "load_detail", "output": {"product_id": pid}})

        facts = _build_complete_facts(product)

        # Product focus is intentionally not persisted here.  Cross-turn
        # product references are resolved once by the Router from the rendered
        # card set, rather than reconstructed by a lower Shopping capability.
        card = build_product_card_from_detail(product)

        return DetailToolResult(
            action="detail",
            product=product,
            focus=None,
            facts=facts,
            product_cards=[card],
            trace=trace,
        )
