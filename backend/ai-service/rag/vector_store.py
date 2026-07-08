"""Milvus 2.5 向量库封装。

**本次改造重点**：
1. 稀疏向量真正落地：用 Milvus 2.5 内置 `Function(BM25)`，插入时**只写 text**，
   Milvus 服务端自动生成 `sparse_vector`。历史版本这里塞的是 `[{} for _ in chunks]`，
   BM25 名存实亡；这一版才是真正的混合检索。
2. Embedding 换成 DashScope text-embedding-v4（1024 维），走 rag/embeddings.py。
3. 对外暴露三个接口：`search`（默认走 hybrid） / `dense_search` / `bm25_search` / `hybrid_search`，
   方便压测对比。

对齐 Milvus BM25 API（2.5+）：
- schema 里 text 字段必须 `enable_analyzer=True`；sparse 字段类型 SPARSE_FLOAT_VECTOR
- schema.add_function(Function(FunctionType.BM25, input=[text], output=[sparse]))
- 稀疏索引 metric_type="BM25"，稠密索引 metric_type="IP"（也能选 "COSINE"，IP 更快）
- 查询稀疏时直接把 query 文本传进 data=["查询语句"]，anns_field="sparse_vector"；
  Milvus 自动 tokenize + 生成稀疏 query 向量
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from langchain_core.documents import Document

from core.config import config
from rag.embeddings import get_embeddings
from rag.models import DocumentChunk, MetadataFilter, SearchRequest, SearchResult

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

logger = logging.getLogger("ai-service.rag.vector_store")


def build_metadata_filter(plan) -> MetadataFilter:
    return MetadataFilter(
        category_ids=[plan.category_id] if plan.category_id else None,
        product_id=plan.product_id,
        doc_types=plan.doc_types or None,
        chunk_types=plan.chunk_types or None,
    )


def build_milvus_expr(filter_: Optional[MetadataFilter]) -> Optional[str]:
    if filter_ is None:
        return None
    parts: list[str] = []
    if filter_.doc_ids:
        parts.append(f"doc_id in {filter_.doc_ids}")
    if filter_.category_ids:
        parts.append(f"category_id in {filter_.category_ids}")
    if filter_.product_id is not None:
        parts.append(f"product_id == {int(filter_.product_id)}")
    if filter_.doc_types:
        values = ", ".join([f'"{v}"' for v in filter_.doc_types])
        parts.append(f"doc_type in [{values}]")
    if filter_.chunk_types:
        values = ", ".join([f'"{v}"' for v in filter_.chunk_types])
        parts.append(f"chunk_type in [{values}]")
    return " and ".join(parts) if parts else None


def chunk_to_document(chunk: DocumentChunk) -> Document:
    return Document(page_content=chunk.content, metadata=chunk.metadata.dict())


def document_to_result(doc: Document, score: float = 0.0) -> SearchResult:
    from rag.models import ChunkMetadata
    return SearchResult(
        content=doc.page_content,
        metadata=ChunkMetadata(**doc.metadata),
        score=float(score or 0.0),
        dense_score=float(score or 0.0),
    )


# ── schema 构建 ──────────────────────────────────────────────
# text 字段必须 enable_analyzer=True，否则 Milvus 不知道怎么切词做 BM25。
# analyzer 默认是 "standard"（英文友好）；中文需要指定 analyzer_params，
# 用 jieba 分词器（Milvus 2.5 内置支持）。
_ANALYZER_PARAMS = {"type": "chinese"}


def _build_fields(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(
            name="text",
            dtype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
            analyzer_params=_ANALYZER_PARAMS,
        ),
        FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="doc_id", dtype=DataType.INT64),
        FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="category_id", dtype=DataType.INT64),
        FieldSchema(name="product_id", dtype=DataType.INT64),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
    ]


# 插入时**不写 sparse_vector**（Milvus BM25 Function 自动生成），
# 也**不写 pk**（auto_id）。以下就是插入端可控字段。
INSERT_FIELDS = [
    "text", "dense_vector",
    "doc_id", "doc_type", "chunk_type",
    "category_id", "product_id",
    "source", "title", "chunk_index",
]

# search / hybrid_search 用的 output_fields（不含向量本身）
SCALAR_FIELDS = [
    "text", "doc_id", "doc_type", "chunk_type",
    "category_id", "product_id",
    "source", "title", "chunk_index",
]


class MilvusVectorStore:
    """Milvus 2.5 混合检索封装。

    三条检索路径（对外暴露）：
      - `dense_search(request)`：纯稠密（DashScope 向量近邻）
      - `bm25_search(request)`：纯 BM25（Milvus 内置稀疏）
      - `hybrid_search(request)`：稠密 + BM25 双路 + RRFRanker 融合

    `search(request)` 是"按 search_mode 自动路由"的对外接口，SearchRequest.search_mode
    决定实际走哪条路（不指定就走 hybrid，因为混合几乎总是更好）。
    """

    def __init__(self, collection_name: str | None = None):
        self.collection_name = collection_name or config.MILVUS_COLLECTION
        self.embeddings = get_embeddings()
        self.milvus_url = config.MILVUS_URL
        self.store: MilvusClient | None = None
        self._embedding_dim: int = config.MILVUS_DENSE_DIM
        self._connect()

    # ── 属性：embedding 维度直接读 config，不做懒探测 ───────────
    # 好处：不会因为 embedding API 抖动而阻塞 Milvus 连接
    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    @staticmethod
    def _prepare_metadata(chunk: DocumentChunk) -> dict:
        m = chunk.metadata if hasattr(chunk, "metadata") else {}
        if hasattr(m, "dict"):
            d = m.dict()
        elif hasattr(m, "model_dump"):
            d = m.model_dump()
        else:
            d = m if isinstance(m, dict) else {}
        return {k: v for k, v in d.items() if v is not None}

    # ── 连接 + 建表 + 建索引 ─────────────────────────────────
    def _connect(self) -> None:
        connections.connect(uri=self.milvus_url)
        milvus_client = MilvusClient(uri=self.milvus_url)
        self.store = milvus_client

        # 已存在就跳过建表（清库单独走 scripts/drop_milvus_collection.py）
        if milvus_client.has_collection(self.collection_name):
            logger.info("Milvus collection %s 已存在，跳过建表", self.collection_name)
            Collection(self.collection_name).load()
            return

        fields = _build_fields(dim=self.embedding_dim)
        schema = CollectionSchema(fields, description="混合检索 (dense + BM25) collection")

        # ── 核心：注册 BM25 Function ──
        # 让 Milvus 在插入 text 时自动生成 sparse_vector；查询时也能从纯文本 query 自动生成稀疏 query 向量。
        # input_field_names 必须是 VARCHAR 且 enable_analyzer=True，output_field_names 必须是 SPARSE_FLOAT_VECTOR。
        bm25_function = Function(
            name="bm25_text_to_sparse",
            input_field_names=["text"],
            output_field_names=["sparse_vector"],
            function_type=FunctionType.BM25,
        )
        schema.add_function(bm25_function)

        collection = Collection(name=self.collection_name, schema=schema, consistency_level="Strong")

        # ── 建索引 ──
        # 稠密：AUTOINDEX + IP（内积；如需余弦相似度改 COSINE）
        collection.create_index(
            "dense_vector",
            {"index_type": "AUTOINDEX", "metric_type": "IP"},
        )
        # 稀疏：SPARSE_INVERTED_INDEX + BM25，params 可调 k1/b（BM25 经典参数）
        # DAAT_MAXSCORE 是 Milvus 推荐的 top-k 加速算法，比 WAND 更稳
        collection.create_index(
            "sparse_vector",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
            },
        )
        collection.load()
        logger.info("Milvus collection %s 建表成功（dense_dim=%d + BM25）", self.collection_name, self.embedding_dim)

    # ── Milvus hit → SearchResult ───────────────────────────
    @staticmethod
    def _results_to_search_results(results, *, score_field: str = "dense") -> list[SearchResult]:
        """
        score_field 表示这一批结果里 `distance` 是哪种得分：
        - "dense"  → 填 dense_score
        - "sparse" → 填 sparse_score
        - "hybrid" → 填 rerank_score（RRF 融合后的分数）
        """
        out: list[SearchResult] = []
        for hit in results:
            meta = {
                "doc_id":      hit.entity.get("doc_id", 0),
                "doc_type":    hit.entity.get("doc_type", ""),
                "chunk_type":  hit.entity.get("chunk_type", ""),
                "category_id": hit.entity.get("category_id", 0),
                "product_id":  hit.entity.get("product_id", 0),
                "source":      hit.entity.get("source", ""),
                "title":       hit.entity.get("title", ""),
                "chunk_index": hit.entity.get("chunk_index", 0),
            }
            text = hit.entity.get("text", "")
            score = float(getattr(hit, "distance", 0.0) or 0.0)
            doc = Document(page_content=text, metadata=meta)
            sr = document_to_result(doc, score=score)
            # 覆盖精细化的分数字段，方便后续观察哪一路命中
            if score_field == "dense":
                sr.dense_score = score
            elif score_field == "sparse":
                sr.sparse_score = score
                sr.dense_score = None
            elif score_field == "hybrid":
                sr.rerank_score = score
            sr.score = score
            out.append(sr)
        return out

    # ── 1. 写入 chunks ──────────────────────────────────────
    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        """插入分块。**不再写 sparse_vector**——由 Milvus BM25 Function 自动生成。"""
        if not chunks:
            return 0

        collection = Collection(self.collection_name)
        meta_list = [self._prepare_metadata(c) for c in chunks]

        texts = [c.content for c in chunks]
        dense_vectors = self.embeddings.embed_documents(texts)

        # 按 INSERT_FIELDS 的顺序组装列
        rows = {
            "text":         texts,
            "dense_vector": dense_vectors,
            "doc_id":       [int(m.get("doc_id", 0)) for m in meta_list],
            "doc_type":     [str(m.get("doc_type", "")) for m in meta_list],
            "chunk_type":   [str(m.get("chunk_type", "")) for m in meta_list],
            "category_id":  [int(m.get("category_id", 0)) for m in meta_list],
            "product_id":   [int(m.get("product_id", 0)) for m in meta_list],
            "source":       [str(m.get("source", "")) for m in meta_list],
            "title":        [str(m.get("title", "")) for m in meta_list],
            "chunk_index":  [int(m.get("chunk_index", 0)) for m in meta_list],
        }
        collection.insert([rows[f] for f in INSERT_FIELDS])
        collection.flush()
        return len(chunks)

    # ── 2. 检索：按 search_mode 路由 ─────────────────────────
    def search(self, request: SearchRequest) -> list[SearchResult]:
        """按 search_mode 路由到实际检索方法。默认 hybrid。"""
        mode = getattr(request, "search_mode", "hybrid") or "hybrid"
        if mode == "dense":
            return self.dense_search(request)
        if mode == "sparse" or mode == "bm25":
            return self.bm25_search(request)
        # 默认走 hybrid（包括 mode == "hybrid" 或未知值）
        return self.hybrid_search(request)

    # ── 2a. 纯稠密检索 ──────────────────────────────────────
    def dense_search(self, request: SearchRequest) -> list[SearchResult]:
        collection = Collection(self.collection_name)
        collection.load()

        top_k = getattr(request, "top_k", 5)
        expr = build_milvus_expr(request.filter)
        query_vec = self.embeddings.embed_query(request.query)

        results = collection.search(
            [query_vec],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=SCALAR_FIELDS,
        )[0]
        return self._results_to_search_results(results, score_field="dense")

    # ── 2b. 纯 BM25 检索 ────────────────────────────────────
    def bm25_search(self, request: SearchRequest) -> list[SearchResult]:
        """纯 BM25 稀疏检索。

        关键点：`data` 直接传原始文本字符串，Milvus 服务端会：
        1. 调用 BM25 Function 关联的 analyzer 对 query 分词
        2. 生成 query 稀疏向量
        3. 走 BM25 倒排索引找 top-k
        我们本地什么都不用算。
        """
        collection = Collection(self.collection_name)
        collection.load()

        top_k = getattr(request, "top_k", 5)
        expr = build_milvus_expr(request.filter)

        results = collection.search(
            [request.query],  # 原始文本，不是向量！
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=SCALAR_FIELDS,
        )[0]
        return self._results_to_search_results(results, score_field="sparse")

    # ── 2c. 混合检索：dense + BM25 + RRFRanker ───────────────
    def hybrid_search(self, request: SearchRequest) -> list[SearchResult]:
        """稠密 + BM25 双路召回，RRFRanker 融合。

        RRFRanker(k=60) 是 Milvus 官方推荐默认值：稳、不用调参、对分数分布不敏感。
        以后要偏一路（比如 knowledge 场景更依赖语义相似）可以换 WeightedRanker(0.7, 0.3)，
        但目前 k=60 就够——先跑起来看效果，再谈调参。
        """
        collection = Collection(self.collection_name)
        collection.load()

        top_k = getattr(request, "top_k", 5)
        expr = build_milvus_expr(request.filter) or ""
        query_vec = self.embeddings.embed_query(request.query)

        # 双路 AnnSearchRequest：dense 传向量，sparse 传原始文本
        dense_req = AnnSearchRequest(
            data=[query_vec],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {}},
            limit=top_k,
            expr=expr or None,
        )
        sparse_req = AnnSearchRequest(
            data=[request.query],
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {}},
            limit=top_k,
            expr=expr or None,
        )

        results = collection.hybrid_search(
            [dense_req, sparse_req],
            rerank=RRFRanker(k=60),
            limit=top_k,
            output_fields=SCALAR_FIELDS,
        )[0]
        return self._results_to_search_results(results, score_field="hybrid")

    # ── 3. 按 doc_id 删除 ───────────────────────────────────
    def delete_by_doc_id(self, doc_id: int) -> int:
        collection = Collection(self.collection_name)
        collection.load()
        result = collection.delete(expr=f"doc_id == {int(doc_id)}")
        collection.flush()
        return result.delete_count if hasattr(result, "delete_count") else len(result) if result else 0

    # ── 4. 统计 ─────────────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        return {"provider": "milvus", "collection": self.collection_name, "dense_dim": self.embedding_dim}


def create_vector_store():
    return MilvusVectorStore()
