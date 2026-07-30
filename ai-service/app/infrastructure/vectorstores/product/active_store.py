"""Single source of truth for the product Collection active in Shopping.

Recommendation, comparison and product detail must query the same configured
product collection. This module never silently falls back across Collections:
an empty active collection remains an empty result instead of stale facts.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.infrastructure.config import config

logger = logging.getLogger("ai-service.shopping.active_product_store")


PRODUCT_FACT_FIELDS = [
    "product_id", "title", "brand", "image_url", "description",
    "category", "sub_category", "tags", "base_price", "rating",
    "sales_count", "review_count", "status",
]


def get_active_product_store():
    """Select the existing production three-path or legacy product store."""
    if config.SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION:
        from app.infrastructure.vectorstores.product.vector_store_three_path import (
            get_product_milvus_store_three_path,
        )

        return get_product_milvus_store_three_path()

    from app.infrastructure.vectorstores.product.vector_store import get_product_milvus_store

    return get_product_milvus_store()


def normalize_product_ids(values: Iterable[Any]) -> list[int]:
    """Normalize positive product ids while preserving caller order."""
    ids: list[int] = []
    for value in values:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in ids:
            ids.append(product_id)
    return ids


def load_active_products_by_ids(product_ids: Iterable[Any]) -> list[dict[str, Any]]:
    """Read on-sale product facts from the configured active Collection."""
    ids = normalize_product_ids(product_ids)
    if not ids:
        return []

    try:
        from pymilvus import Collection

        store = get_active_product_store()
        collection = Collection(store.collection_name)
        collection.load()
        id_expr = ", ".join(str(product_id) for product_id in ids)
        rows = collection.query(
            expr=f"product_id in [{id_expr}]",
            output_fields=PRODUCT_FACT_FIELDS,
            limit=len(ids),
        )
    except Exception:  # noqa: BLE001
        logger.warning("active product fact query failed product_ids=%s", ids, exc_info=True)
        return []

    by_id: dict[int, dict[str, Any]] = {}
    for row in rows or []:
        try:
            product_id = int(row.get("product_id") or 0)
        except (TypeError, ValueError):
            continue
        if product_id <= 0:
            continue
        status = row.get("status")
        if status is not None:
            try:
                if int(status) != 1:
                    continue
            except (TypeError, ValueError):
                continue
        price = _as_float(row.get("base_price"))
        by_id[product_id] = {
            "product_id": product_id,
            "title": str(row.get("title") or ""),
            "brand": str(row.get("brand") or ""),
            "price": price,
            "base_price": price,
            "image_url": str(row.get("image_url") or ""),
            "description": str(row.get("description") or ""),
            "category": str(row.get("category") or ""),
            "sub_category": str(row.get("sub_category") or ""),
            "tags": str(row.get("tags") or ""),
            "rating": _as_float(row.get("rating")),
            "sales_count": _as_int(row.get("sales_count")),
            "review_count": _as_int(row.get("review_count")),
            "status": 1,
        }
    return [by_id[product_id] for product_id in ids if product_id in by_id]


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
