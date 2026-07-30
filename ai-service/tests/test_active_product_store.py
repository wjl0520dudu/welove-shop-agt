"""The active Collection selector is shared by retrieval and fact lookups."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.infrastructure.config import config
from app.infrastructure.vectorstores.product.active_store import (
    get_active_product_store,
    load_active_products_by_ids,
)


def test_active_store_uses_existing_three_path_switch():
    three_path = object()
    legacy = object()
    with patch.object(config, "SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION", True), patch(
        "app.infrastructure.vectorstores.product.vector_store_three_path.get_product_milvus_store_three_path",
        return_value=three_path,
    ):
        assert get_active_product_store() is three_path

    with patch.object(config, "SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION", False), patch(
        "app.infrastructure.vectorstores.product.vector_store.get_product_milvus_store",
        return_value=legacy,
    ):
        assert get_active_product_store() is legacy


def test_active_fact_lookup_preserves_id_order_and_excludes_inactive_rows():
    collection = MagicMock()
    collection.query.return_value = [
        {"product_id": 13, "title": "P13", "base_price": 130, "status": 1},
        {"product_id": 7, "title": "P7", "base_price": 70, "status": 1},
        {"product_id": 11, "title": "Off", "base_price": 110, "status": 0},
    ]
    store = MagicMock(collection_name="product_multimodal_prod_v1")
    with patch(
        "app.infrastructure.vectorstores.product.active_store.get_active_product_store",
        return_value=store,
    ), patch("pymilvus.Collection", return_value=collection):
        rows = load_active_products_by_ids([13, 7, 11, 7, "invalid"])

    assert [row["product_id"] for row in rows] == [13, 7]
    assert collection.query.call_args.kwargs["limit"] == 3
    assert "13, 7, 11" in collection.query.call_args.kwargs["expr"]
    assert rows[0]["price"] == 130.0
