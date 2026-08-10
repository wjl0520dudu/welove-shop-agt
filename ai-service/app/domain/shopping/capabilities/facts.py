"""Router-bound product fact loading for Skill-driven compare/detail tasks.

This module deliberately performs no natural-language classification.  The
ShoppingAgent understands the user's requested dimensions after reading the
matching Skill; code only validates Router bindings and loads real product/SKU
facts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from app.domain.shopping.cards import build_product_card_from_detail
from app.domain.shopping.schemas import BoundProductFactsToolResult, ShoppingContext


logger = logging.getLogger("ai-service.shopping.bound_facts")


def _normalise_product_ids(values: Optional[List[int]]) -> List[int]:
    product_ids: List[int] = []
    for value in values or []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in product_ids:
            product_ids.append(product_id)
    return product_ids


class BoundProductFactsCapability:
    """Load facts for one detail target or multiple comparison targets."""

    async def run(
        self,
        *,
        purpose: Literal["compare", "detail"],
        context: ShoppingContext,
        product_ids: Optional[List[int]] = None,
    ) -> BoundProductFactsToolResult:
        trace: List[Dict[str, Any]] = []
        bound_ids = _normalise_product_ids(context.selected_product_ids)
        requested_ids = (
            _normalise_product_ids(product_ids)
            if product_ids is not None
            else list(bound_ids)
        )

        invalid_binding = (
            not bound_ids
            or not requested_ids
            or any(product_id not in bound_ids for product_id in requested_ids)
        )
        invalid_count = (
            purpose == "compare" and len(requested_ids) < 2
        ) or (
            purpose == "detail" and len(requested_ids) != 1
        )
        if invalid_binding or invalid_count:
            question = (
                "你想比较哪几款商品？请明确至少两件商品。"
                if purpose == "compare"
                else "你想了解哪一件商品？请明确商品名或序号。"
            )
            return BoundProductFactsToolResult(
                action="clarify",
                purpose=purpose,
                clarify_question=question,
                trace=trace,
            )

        products = await _load_bound_product_details(requested_ids)
        loaded_ids = {
            int(product.get("product_id") or 0)
            for product in products
            if product.get("product_id")
        }
        missing_product_ids = [
            product_id for product_id in requested_ids
            if product_id not in loaded_ids
        ]

        trace.append({
            "step": "load_bound_product_facts",
            "output": {
                "purpose": purpose,
                "requested_count": len(requested_ids),
                "loaded_count": len(products),
                "missing_count": len(missing_product_ids),
            },
        })

        minimum = 2 if purpose == "compare" else 1
        if len(products) < minimum:
            return BoundProductFactsToolResult(
                action="empty",
                purpose=purpose,
                missing_product_ids=missing_product_ids,
                empty_reason=(
                    "已确认的商品不存在、已下架或实时事实不足，暂时无法完成比较。"
                    if purpose == "compare"
                    else "已确认的商品不存在或已下架，暂时无法查询详情。"
                ),
                trace=trace,
            )

        return BoundProductFactsToolResult(
            action="compare_facts" if purpose == "compare" else "detail_facts",
            purpose=purpose,
            products=products,
            product_cards=[build_product_card_from_detail(product) for product in products],
            missing_product_ids=missing_product_ids,
            trace=trace,
        )


async def _load_bound_product_details(product_ids: List[int]) -> List[Dict[str, Any]]:
    """Batch-load active product facts and attach SKU rows in one PG query."""
    from app.infrastructure.vectorstores.product.active_store import (
        load_active_products_by_ids,
    )

    products = load_active_products_by_ids(product_ids)
    if not products:
        return []

    sku_by_product: dict[int, list[dict[str, Any]]] = {
        int(product["product_id"]): [] for product in products
    }
    try:
        from sqlalchemy import select

        from app.infrastructure.persistence.database import get_session_factory
        from app.infrastructure.persistence.orm_models import ProductSkuORM

        session_factory = get_session_factory()
        async with session_factory() as session:
            sku_rows = (await session.execute(
                select(ProductSkuORM).where(ProductSkuORM.product_id.in_(product_ids))
            )).scalars().all()
        for sku in sku_rows:
            product_id = int(sku.product_id or 0)
            if product_id not in sku_by_product:
                continue
            sku_by_product[product_id].append({
                "id": sku.id,
                "skuCode": sku.sku_code or "",
                "properties": sku.properties or {},
                "price": float(sku.price) if sku.price is not None else None,
                "stock": sku.stock,
                "isDefault": sku.is_default,
            })
    except Exception:  # noqa: BLE001
        # SKU storage is an optional enrichment. Main product facts remain
        # usable for price, rating, description and other comparisons.
        logger.warning("bound product SKU query failed product_ids=%s", product_ids, exc_info=True)
        for product in products:
            product["skus"] = []
        return products

    for product in products:
        product["skus"] = sku_by_product.get(int(product["product_id"]), [])
    return products


__all__ = ["BoundProductFactsCapability"]
