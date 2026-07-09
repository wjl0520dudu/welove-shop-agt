"""ProductMilvusStore —— 商品多模态向量库。

## 设计对齐 rag/vector_store.py（KnowledgeAgent 那套）
- 同样用 Milvus 2.5 内置 `Function(BM25)` 生成稀疏向量，插入端**只写 text**；
- 同样暴露 `dense_search / bm25_search / hybrid_search` 三路 + `search(request)` 分派；
- 同样 dense 索引走 IP，稀疏 SPARSE_INVERTED_INDEX + BM25 + DAAT_MAXSCORE。

## 和知识 collection 的**关键差异**
1. **collection 独立** —— `MILVUS_PRODUCT_COLLECTION` 而非 `MILVUS_COLLECTION`；
2. **schema 多一个 `multimodal_vector` 字段**（Phase 2 图+文融合用，MVP 灌零向量、不建索引）；
3. **展示 + filter 字段冗余进 Milvus**（title/brand/base_price/rating/…），
   推荐/对比/overview 类追问零回 PG；仅 focus=price/stock/sku 时才回 PG 拿实时 SKU/库存；
4. **filter 支持结构化表达式**（category/base_price/status/brand），
   Milvus 服务端过滤，不用回 PG 再筛。

## 为什么用 pymilvus 底层 API 而不是 langchain_milvus
- langchain_milvus 抽象层不够薄，hybrid_search + Function BM25 + 自定义 filter 表达式
  它都要绕；KnowledgeAgent 也是直用 pymilvus 的 Collection API，风格统一。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pymilvus import (
    connections,
    MilvusClient,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    AnnSearchRequest,
    RRFRanker,
    Function,
    FunctionType,
)

from core.config import config
from rag.embeddings import get_embeddings

logger = logging.getLogger("ai-service.shopping.vector_store")


# 中文分词参数：Milvus 2.5 内置 jieba，跟知识库一致
_ANALYZER_PARAMS = {"type": "chinese"}

# 服务端过滤时能用的字段（product_id / category / brand / base_price / status / sub_category）
# —— 都必须是 schema 里的标量字段，不能过滤 text 本身。
_FILTERABLE_FIELDS = {
    "product_id", "category", "sub_category", "brand",
    "base_price", "rating", "sales_count", "review_count", "status",
}


def _build_fields(text_dim: int, multimodal_dim: int) -> list[FieldSchema]:
    """商品 collection schema。

    text_dim：文本 dense（MVP 用 DashScope v4 = 1024，Phase 2 若切 tongyi 需同步改）；
    multimodal_dim：Phase 2 图+文融合向量维度。MVP 灌零向量占位；预留字段避免 Phase 2 清库重建。
    """
    return [
        # 主键：直接用商品 id，避免 auto_id → 让 upsert 有意义（同 id 覆盖）
        FieldSchema(name="product_id", dtype=DataType.INT64, is_primary=True),
        # BM25 用的分词文本（title + brand + category + tags + description 拼接）
        FieldSchema(
            name="text",
            dtype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
            analyzer_params=_ANALYZER_PARAMS,
        ),
        # ── 三向量字段 ──
        FieldSchema(name="text_dense_vector", dtype=DataType.FLOAT_VECTOR, dim=text_dim),
        FieldSchema(name="text_sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
        # Phase 2 图+文融合向量。MVP 插零向量占位、不建索引 → 不占内存、不影响启动。
        FieldSchema(name="multimodal_vector", dtype=DataType.FLOAT_VECTOR, dim=multimodal_dim),
        # ── 展示字段（build_product_cards 直接用，避免回 PG）──
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="brand", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="image_url", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=2048),
        # ── 服务端 filter + 排序字段 ──
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="sub_category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="base_price", dtype=DataType.FLOAT),
        FieldSchema(name="rating", dtype=DataType.FLOAT),
        FieldSchema(name="sales_count", dtype=DataType.INT64),
        FieldSchema(name="review_count", dtype=DataType.INT64),
        # status：1=在售 0=下架；filter 默认过滤 status==1
        FieldSchema(name="status", dtype=DataType.INT8),
    ]


# 插入时可写字段（不含 text_sparse_vector—— Function 自动生成；不含 multimodal_vector—— 插入端由上层控制是否写）
INSERT_FIELDS = [
    "product_id", "text",
    "text_dense_vector", "multimodal_vector",
    "title", "brand", "image_url", "description",
    "category", "sub_category", "tags",
    "base_price", "rating", "sales_count", "review_count", "status",
]

# 检索返回给上层的标量字段（不含向量本身）
OUTPUT_FIELDS = [
    "product_id",
    "title", "brand", "image_url", "description",
    "category", "sub_category", "tags",
    "base_price", "rating", "sales_count", "review_count", "status",
]


def build_milvus_filter_expr(
    filters: Optional[Dict[str, Any]],
    include_status_default: bool = True,
) -> Optional[str]:
    """把 dict 形式的 filter 翻译成 Milvus expr 字符串。

    支持字段（见 _FILTERABLE_FIELDS）：
    - product_id: int → `product_id == 42`
    - product_ids: List[int] → `product_id in [1,2,3]`
    - category: str → `(category == "防晒" || sub_category == "防晒")`
                       ★ 关键：LLM 抽出的品类词可能是顶级类目（"美妆护肤"）
                       也可能是子类目（"防晒" / "面霜" / "速干 T 恤"）。
                       统一做 OR 匹配，两级都试，避免 "防晒" 命中 category（顶级）失败。
    - sub_category: str → `sub_category == "..."`  显式子类目（跳过 OR，精确匹配）
    - brand: str → `brand == "Nike"`
    - budget_min / budget_max: float → `base_price >= 100 && base_price <= 200`
    - min_rating: float → `rating >= 4.5`
    - status: int → `status == 1`（默认加，除非显式传 status=None）
    """
    parts: List[str] = []
    filters = filters or {}

    # product_id / product_ids
    if "product_id" in filters and filters["product_id"] is not None:
        parts.append(f"product_id == {int(filters['product_id'])}")
    if "product_ids" in filters and filters["product_ids"]:
        ids = ", ".join(str(int(x)) for x in filters["product_ids"])
        parts.append(f"product_id in [{ids}]")

    # category：两级 OR 匹配（顶级 || 子类目）
    cat = filters.get("category")
    if cat:
        cat_esc = str(cat).replace('"', '\\"')
        parts.append(f'(category == "{cat_esc}" || sub_category == "{cat_esc}")')

    # sub_category 显式传时精确匹配（供高级场景，比如 Capability 内部想强制子类）
    sub_cat = filters.get("sub_category")
    if sub_cat:
        sub_esc = str(sub_cat).replace('"', '\\"')
        parts.append(f'sub_category == "{sub_esc}"')

    # brand
    brand = filters.get("brand")
    if brand:
        brand_esc = str(brand).replace('"', '\\"')
        parts.append(f'brand == "{brand_esc}"')

    # 预算区间
    bmin = filters.get("budget_min")
    bmax = filters.get("budget_max")
    if bmin is not None:
        parts.append(f"base_price >= {float(bmin)}")
    if bmax is not None:
        parts.append(f"base_price <= {float(bmax)}")

    # 最低评分
    mr = filters.get("min_rating")
    if mr is not None:
        parts.append(f"rating >= {float(mr)}")

    # status：默认过滤在售，除非显式传 status
    if "status" in filters:
        s = filters.get("status")
        if s is not None:
            parts.append(f"status == {int(s)}")
    elif include_status_default:
        parts.append("status == 1")

    return " && ".join(parts) if parts else None


class ProductMilvusStore:
    """商品多模态向量库封装。

    三路检索接口对齐 KnowledgeAgent：
    - `dense_search(query, filters, top_k)` 文本 dense
    - `bm25_search(query, filters, top_k)`  Milvus BM25 稀疏
    - `hybrid_search(query, filters, top_k)` 双路 + RRFRanker
    - `search(mode, query, filters, top_k)` 按 mode 分派（默认 hybrid）

    Phase 2 追加：
    - `multimodal_search(image, text=None)` 以图搜图 / 图+文
    - `hybrid_search(..., include_multimodal=True)` 三路 RRF
    """

    def __init__(self, collection_name: Optional[str] = None):
        self.collection_name = collection_name or config.MILVUS_PRODUCT_COLLECTION
        self.embeddings = get_embeddings()
        self.milvus_url = config.MILVUS_URL
        self.text_dim = config.MILVUS_DENSE_DIM
        # Phase 2 图+文融合默认按 tongyi-vision-flash 的 1024 维预留（跟 v4 对齐，
        # 未来若模型 dim 变化需要清库重建，改这里即可）
        self.multimodal_dim = int(config.MILVUS_DENSE_DIM)
        self.store: MilvusClient | None = None
        self._connect()

    # ── 连接 + 建表 + 建索引 ─────────────────────────────────
    def _connect(self) -> None:
        connections.connect(uri=self.milvus_url)
        milvus_client = MilvusClient(uri=self.milvus_url)
        self.store = milvus_client

        if milvus_client.has_collection(self.collection_name):
            logger.info("商品 collection %s 已存在，跳过建表", self.collection_name)
            Collection(self.collection_name).load()
            return

        fields = _build_fields(text_dim=self.text_dim, multimodal_dim=self.multimodal_dim)
        schema = CollectionSchema(
            fields,
            description="商品多模态向量库（text_dense + BM25 + multimodal 预留）",
        )

        # BM25 Function：把 text 字段自动喂给 text_sparse_vector
        schema.add_function(Function(
            name="bm25_text_to_sparse",
            input_field_names=["text"],
            output_field_names=["text_sparse_vector"],
            function_type=FunctionType.BM25,
        ))

        collection = Collection(
            name=self.collection_name, schema=schema, consistency_level="Strong",
        )

        # 稠密文本向量：AUTOINDEX + IP（跟知识库一致）
        collection.create_index(
            "text_dense_vector",
            {"index_type": "AUTOINDEX", "metric_type": "IP"},
        )
        # BM25 稀疏
        collection.create_index(
            "text_sparse_vector",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
            },
        )
        # multimodal_vector：MVP 阶段用零向量占位。
        # ⚠️ Milvus 2.5 要求 collection.load() 时所有向量字段都必须有索引，
        # 所以哪怕不用也得建一个 —— FLAT + COSINE 最省资源（不用 HNSW 那套）。
        # Phase 2 图片就绪时：drop_index → 重新灌真向量 → 换 HNSW/AUTOINDEX，不需要清库。
        collection.create_index(
            "multimodal_vector",
            {"index_type": "FLAT", "metric_type": "COSINE"},
        )
        collection.load()
        logger.info(
            "商品 collection %s 建表成功（text_dense_dim=%d + BM25 + multimodal 占位 dim=%d FLAT）",
            self.collection_name, self.text_dim, self.multimodal_dim,
        )

    # ── 结果转换：Milvus hit → 上层可消费的 dict ─────────────
    @staticmethod
    def _hit_to_dict(hit, score_field: str) -> Dict[str, Any]:
        """把 Milvus hit 转成 shopping 内部通用 dict。

        字段命名对齐 pgvector_store.search 返回的 shape：
        product_id / title / brand / price / base_price / image_url / rating /
        review_count / sales_count / category / sub_category / tags / description
        + distance / recall_sources（供 Ranker 用）+ score / dense_score / sparse_score / rerank_score
        """
        entity = hit.entity
        base_price = float(entity.get("base_price") or 0)
        score = float(getattr(hit, "distance", 0.0) or 0.0)
        item: Dict[str, Any] = {
            "product_id": int(entity.get("product_id") or 0),
            "title": entity.get("title", "") or "",
            "brand": entity.get("brand", "") or "",
            "price": base_price,
            "base_price": base_price,
            "image_url": entity.get("image_url", "") or "",
            "rating": float(entity.get("rating") or 0),
            "review_count": int(entity.get("review_count") or 0),
            "sales_count": int(entity.get("sales_count") or 0),
            "category": entity.get("category", "") or "",
            "sub_category": entity.get("sub_category", "") or "",
            "tags": entity.get("tags", "") or "",
            "description": entity.get("description", "") or "",
            "status": int(entity.get("status") or 0),
            "score": score,
            "distance": score,
            "recall_sources": [],
        }
        # 记录哪一路命中的分数
        if score_field == "dense":
            item["dense_score"] = score
        elif score_field == "sparse":
            item["sparse_score"] = score
        elif score_field == "hybrid":
            item["hybrid_score"] = score
        return item

    # ── 写入商品 ────────────────────────────────────────────
    def upsert_products(self, products: List[Dict[str, Any]]) -> int:
        """批量写入商品（同 product_id 覆盖）。

        products 里每个 dict 至少要有 product_id + title；其他字段缺失填空/0/1（status）。
        `text` 字段由本方法拼接（用户不用管），保证 BM25 分词内容一致。
        `multimodal_vector` MVP 阶段填零向量占位。
        """
        if not products:
            return 0

        collection = Collection(self.collection_name)

        # 拼 text（BM25 用）
        texts = [_build_search_text(p) for p in products]

        # dense 向量
        dense_vectors = self.embeddings.embed_documents(texts)

        # multimodal 占位零向量（Phase 2 换成真图+文向量）
        zero_vec = [0.0] * self.multimodal_dim
        multimodal_vectors = [zero_vec for _ in products]

        rows = {
            "product_id":         [int(p["product_id"]) for p in products],
            "text":               texts,
            "text_dense_vector":  dense_vectors,
            "multimodal_vector":  multimodal_vectors,
            "title":              [str(p.get("title") or "")[:256] for p in products],
            "brand":              [str(p.get("brand") or "")[:64] for p in products],
            "image_url":          [str(p.get("image_url") or "")[:512] for p in products],
            "description":        [str(p.get("description") or "")[:2048] for p in products],
            "category":           [str(p.get("category") or "")[:64] for p in products],
            "sub_category":       [str(p.get("sub_category") or "")[:64] for p in products],
            "tags":               [str(p.get("tags") or "")[:512] for p in products],
            "base_price":         [float(p.get("base_price") or p.get("price") or 0) for p in products],
            "rating":             [float(p.get("rating") or 0) for p in products],
            "sales_count":        [int(p.get("sales_count") or 0) for p in products],
            "review_count":       [int(p.get("review_count") or 0) for p in products],
            "status":             [int(p.get("status") if p.get("status") is not None else 1) for p in products],
        }
        # upsert：主键相同则覆盖（跟 insert 不同——不会重复）
        collection.upsert([rows[f] for f in INSERT_FIELDS])
        collection.flush()
        return len(products)

    def delete_by_product_id(self, product_id: int) -> int:
        collection = Collection(self.collection_name)
        collection.load()
        result = collection.delete(expr=f"product_id == {int(product_id)}")
        collection.flush()
        return result.delete_count if hasattr(result, "delete_count") else 0

    def stats(self) -> Dict[str, Any]:
        return {
            "provider": "milvus",
            "collection": self.collection_name,
            "text_dense_dim": self.text_dim,
            "multimodal_dim": self.multimodal_dim,
        }

    # ── 检索：按 mode 分派 ──────────────────────────────────
    def search(
        self,
        query: str,
        mode: str = "hybrid",
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        m = (mode or "hybrid").lower()
        if m == "dense":
            return self.dense_search(query, filters=filters, top_k=top_k)
        if m in ("bm25", "sparse"):
            return self.bm25_search(query, filters=filters, top_k=top_k)
        # 默认 hybrid（含未知值兜底）
        return self.hybrid_search(query, filters=filters, top_k=top_k)

    # ── dense 单路 ──────────────────────────────────────────
    def dense_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        collection = Collection(self.collection_name)
        collection.load()
        expr = build_milvus_filter_expr(filters)
        query_vec = self.embeddings.embed_query(query)
        results = collection.search(
            [query_vec],
            anns_field="text_dense_vector",
            param={"metric_type": "IP", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=OUTPUT_FIELDS,
        )[0]
        return [self._hit_to_dict(h, "dense") for h in results]

    # ── BM25 单路 ───────────────────────────────────────────
    def bm25_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        collection = Collection(self.collection_name)
        collection.load()
        expr = build_milvus_filter_expr(filters)
        results = collection.search(
            [query],  # 传原始文本，Milvus 服务端分词
            anns_field="text_sparse_vector",
            param={"metric_type": "BM25", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=OUTPUT_FIELDS,
        )[0]
        return [self._hit_to_dict(h, "sparse") for h in results]

    # ── hybrid：dense + BM25 + RRFRanker ────────────────────
    def hybrid_search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        collection = Collection(self.collection_name)
        collection.load()
        expr = build_milvus_filter_expr(filters)
        query_vec = self.embeddings.embed_query(query)

        dense_req = AnnSearchRequest(
            data=[query_vec],
            anns_field="text_dense_vector",
            param={"metric_type": "IP", "params": {}},
            limit=top_k,
            expr=expr or None,
        )
        sparse_req = AnnSearchRequest(
            data=[query],
            anns_field="text_sparse_vector",
            param={"metric_type": "BM25", "params": {}},
            limit=top_k,
            expr=expr or None,
        )
        results = collection.hybrid_search(
            [dense_req, sparse_req],
            rerank=RRFRanker(k=60),
            limit=top_k,
            output_fields=OUTPUT_FIELDS,
        )[0]
        return [self._hit_to_dict(h, "hybrid") for h in results]


def _build_search_text(p: Dict[str, Any]) -> str:
    """拼接商品的 BM25 分词文本。

    顺序：title(权重最高，重复一次) + brand + category + sub_category + tags + description。
    重复 title 让 BM25 更看重命名匹配；description 保留全文供语义关键词匹配。
    """
    title = str(p.get("title") or "").strip()
    brand = str(p.get("brand") or "").strip()
    category = str(p.get("category") or "").strip()
    sub_category = str(p.get("sub_category") or "").strip()
    tags = str(p.get("tags") or "").strip()
    description = str(p.get("description") or "").strip()

    parts = [title, title, brand, category, sub_category, tags, description]
    return " ".join(part for part in parts if part)


# ── 单例访问 ─────────────────────────────────────────────
_product_store_instance: ProductMilvusStore | None = None


def get_product_milvus_store() -> ProductMilvusStore:
    """懒加载单例 ProductMilvusStore。"""
    global _product_store_instance
    if _product_store_instance is None:
        _product_store_instance = ProductMilvusStore()
    return _product_store_instance
