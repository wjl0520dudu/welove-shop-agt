"""生产三路商品检索 collection：text dense + BM25 + image vector。

该 schema 是 ``product_mm_v2`` 的严格子集，刻意不保存
``multimodal_vector``，避免生产导入产生未被最终方案使用的融合 embedding 成本。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymilvus import Collection, CollectionSchema, Function, FunctionType, MilvusClient, connections

from app.infrastructure.config import config
from app.infrastructure.vectorstores.product.vector_store_v2 import (
    OUTPUT_FIELDS_V2, ProductMilvusStoreV2, _build_fields_v2, _fit_vector,
)

logger = logging.getLogger("ai-service.shopping.vector_store_three_path")

INSERT_FIELDS_THREE_PATH = [
    "product_id", "text", "text_dense_vector", "image_vector",
    "title", "brand", "image_url", "description", "category", "sub_category", "tags",
    "base_price", "rating", "sales_count", "review_count", "status",
]


class ProductMilvusThreePathStore(ProductMilvusStoreV2):
    """复用 v2 的 dense/BM25/image 检索实现，仅替换 schema 与写入字段。"""

    is_three_path_collection = True

    def __init__(self, collection_name: Optional[str] = None):
        self.collection_name = collection_name or config.MILVUS_PRODUCT_THREE_PATH_COLLECTION
        self.milvus_url = config.MILVUS_URL
        self.text_dim = int(config.MILVUS_DENSE_DIM)
        self.image_dim = int(config.MILVUS_IMAGE_DIM)
        self.multimodal_dim = 0  # 防御性占位：该生产 store 不支持第四路融合检索。
        self.store: MilvusClient | None = None
        self._connect()

    def _connect(self) -> None:
        kwargs: Dict[str, str] = {"uri": self.milvus_url}
        if config.MILVUS_TOKEN:
            kwargs["token"] = config.MILVUS_TOKEN
        connections.connect(**kwargs)
        self.store = MilvusClient(**kwargs)
        if self.store.has_collection(self.collection_name):
            Collection(self.collection_name).load()
            return

        fields = [field for field in _build_fields_v2(self.text_dim, self.image_dim, self.image_dim)
                  if field.name != "multimodal_vector"]
        schema = CollectionSchema(fields, description="生产商品三路检索：text dense + BM25 + image")
        schema.add_function(Function(
            name="bm25_text_to_sparse", input_field_names=["text"],
            output_field_names=["text_sparse_vector"], function_type=FunctionType.BM25,
        ))
        collection = Collection(self.collection_name, schema=schema, consistency_level="Strong")
        collection.create_index("text_dense_vector", {"index_type": "AUTOINDEX", "metric_type": "IP"})
        collection.create_index("text_sparse_vector", {
            "index_type": "SPARSE_INVERTED_INDEX", "metric_type": "BM25",
            "params": {"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
        })
        collection.create_index("image_vector", {"index_type": "AUTOINDEX", "metric_type": "IP"})
        collection.load()
        logger.info("生产三路商品 collection %s 已创建（text=%d image=%d）", self.collection_name, self.text_dim, self.image_dim)

    def upsert_rows(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        payload = {
            "product_id": [int(row["product_id"]) for row in rows],
            "text": [str(row.get("text") or "")[:65535] for row in rows],
            "text_dense_vector": [_fit_vector(row.get("text_dense_vector"), self.text_dim) for row in rows],
            "image_vector": [_fit_vector(row.get("image_vector"), self.image_dim) for row in rows],
            "title": [str(row.get("title") or "")[:256] for row in rows],
            "brand": [str(row.get("brand") or "")[:64] for row in rows],
            "image_url": [str(row.get("image_url") or "")[:512] for row in rows],
            "description": [str(row.get("description") or "")[:2048] for row in rows],
            "category": [str(row.get("category") or "")[:64] for row in rows],
            "sub_category": [str(row.get("sub_category") or "")[:64] for row in rows],
            "tags": [str(row.get("tags") or "")[:512] for row in rows],
            "base_price": [float(row.get("base_price") or 0) for row in rows],
            "rating": [float(row.get("rating") or 0) for row in rows],
            "sales_count": [int(row.get("sales_count") or 0) for row in rows],
            "review_count": [int(row.get("review_count") or 0) for row in rows],
            "status": [int(row.get("status") if row.get("status") is not None else 1) for row in rows],
        }
        collection = Collection(self.collection_name)
        collection.upsert([payload[field] for field in INSERT_FIELDS_THREE_PATH])
        collection.flush()
        return len(rows)

    def multimodal_vector_search(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("生产三路 collection 不包含 multimodal_vector；请使用 dense/BM25/image 三路检索")

    def stats(self) -> Dict[str, Any]:
        return {"provider": "milvus", "collection": self.collection_name, "text_dense_dim": self.text_dim, "image_dim": self.image_dim, "paths": ["text_dense", "bm25", "image"]}


_instance: ProductMilvusThreePathStore | None = None


def get_product_milvus_store_three_path() -> ProductMilvusThreePathStore:
    global _instance
    if _instance is None:
        _instance = ProductMilvusThreePathStore()
    return _instance
