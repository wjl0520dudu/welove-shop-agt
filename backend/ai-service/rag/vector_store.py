from __future__ import annotations
import os
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from core.config import config
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
)


def get_embeddings():
    return OpenAIEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OPENAI_BASE_URL,
        api_key=config.OPENAI_API_KEY,
    )


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


# 字段构建函数：每次返回新的 FieldSchema 列表，dim 由调用方传入
def _build_fields(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="pk",            dtype=DataType.INT64,              is_primary=True, auto_id=True),
        FieldSchema(name="dense_vector",  dtype=DataType.FLOAT_VECTOR,       dim=dim),
        FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="text",          dtype=DataType.VARCHAR,            max_length=65535),
        FieldSchema(name="doc_id",        dtype=DataType.INT64),
        FieldSchema(name="doc_type",      dtype=DataType.VARCHAR,            max_length=16),
        FieldSchema(name="chunk_type",    dtype=DataType.VARCHAR,            max_length=16),
        FieldSchema(name="category_id",   dtype=DataType.INT64),
        FieldSchema(name="source",        dtype=DataType.VARCHAR,            max_length=512),
        FieldSchema(name="title",         dtype=DataType.VARCHAR,            max_length=256),
        FieldSchema(name="chunk_index",   dtype=DataType.INT64),
    ]


# insert / output_fields 用的标量字段名列表
SCALAR_FIELDS = [
    "text", "doc_id", "doc_type", "chunk_type",
    "category_id", "source", "title", "chunk_index",
]


class MilvusVectorStore:
    def __init__(self, collection_name: str | None = None):
        self.collection_name = collection_name or config.MILVUS_COLLECTION
        self.embeddings = get_embeddings()
        self.milvus_url = config.MILVUS_URL
        self.store: MilvusClient | None = None
        self._embedding_dim: int | None = None
        self._connect()

    # ── 动态检测 embedding 维度 ──────────────────────
    @property
    def embedding_dim(self) -> int:
        self._embedding_dim = 1536
        # if self._embedding_dim is None:
        #     sample = self.embeddings.embed_query("dim")
        #     self._embedding_dim = len(sample)
        #     print(f"--> 检测到 embedding 维度: {self._embedding_dim}")
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

    # ── connection + schema ─────────────────────────
    def _connect(self) -> None:
        connections.connect(uri=self.milvus_url)
        milvus_client = MilvusClient(uri=self.milvus_url)

        # if milvus_client.has_collection(self.collection_name):
        #     milvus_client.drop_collection(self.collection_name)

        # _build_fields 直接接收真实维度
        fields = _build_fields(dim=self.embedding_dim)

        schema = CollectionSchema(fields, description="混合检索 collection")
        collection = Collection(name=self.collection_name, schema=schema, consistency_level="Strong")
        collection.create_index("sparse_vector", {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"})
        collection.create_index("dense_vector",  {"index_type": "AUTOINDEX", "metric_type": "IP"})
        collection.load()
        self.store = milvus_client

    # ── Milvus hit → SearchResult ───────────────────
    @staticmethod
    def _results_to_search_results(results) -> list[SearchResult]:
        out: list[SearchResult] = []
        for hit in results:
            meta = {
                "doc_id":      hit.entity.get("doc_id", 0),
                "doc_type":    hit.entity.get("doc_type", ""),
                "chunk_type":  hit.entity.get("chunk_type", ""),
                "category_id": hit.entity.get("category_id", 0),
                "source":      hit.entity.get("source", ""),
                "title":       hit.entity.get("title", ""),
                "chunk_index": hit.entity.get("chunk_index", 0),
            }
            text = hit.entity.get("text", "")
            score = getattr(hit, "distance", 0.0) or 0.0
            doc = Document(page_content=text, metadata=meta)
            out.append(document_to_result(doc, score=float(score)))
        return out

    # ── 1. 写入 chunks ──────────────────────────────
    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0

        collection = Collection(self.collection_name)
        meta_list = [self._prepare_metadata(c) for c in chunks]

        texts = [c.content for c in chunks]
        dense_vectors = self.embeddings.embed_documents(texts)

        col_text        = [m.get("text", c.content) for c, m in zip(chunks, meta_list)]
        col_doc_id      = [int(m.get("doc_id", 0)) for m in meta_list]
        col_doc_type    = [m.get("doc_type", "") for m in meta_list]
        col_chunk_type  = [m.get("chunk_type", "") for m in meta_list]
        col_category_id = [int(m.get("category_id", 0)) for m in meta_list]
        col_source      = [m.get("source", "") for m in meta_list]
        col_title       = [m.get("title", "") for m in meta_list]
        col_chunk_index = [int(m.get("chunk_index", 0)) for m in meta_list]

        sparse_vectors = [{} for _ in chunks]

        collection.insert([
            dense_vectors,
            sparse_vectors,
            col_text,
            col_doc_id,
            col_doc_type,
            col_chunk_type,
            col_category_id,
            col_source,
            col_title,
            col_chunk_index,
        ])
        collection.flush()
        return len(chunks)

    # ── 2. 搜索（hybrid ready）──────────────────────
    def search(self, request: SearchRequest) -> list[SearchResult]:
        collection = Collection(self.collection_name)
        collection.load()

        top_k = getattr(request, "top_k", 5)
        expr = build_milvus_expr(request.filter)
        search_params = {"metric_type": "IP", "params": {}}

        query_vec = self.embeddings.embed_query(request.query)

        results = collection.search(
            [query_vec],
            anns_field="dense_vector",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=SCALAR_FIELDS,
        )[0]

        return self._results_to_search_results(results)

    def hybrid_search(self, request: SearchRequest) -> list[SearchResult]:
        collection = Collection(self.collection_name)
        collection.load()

        top_k = getattr(request, "top_k", 5)
        expr = build_milvus_expr(request.filter) or ""
        search_params = {"metric_type": "IP", "params": {}}

        query_vec = self.embeddings.embed_query(request.query)

        # ── expr 移进 AnnSearchRequest ──
        # expr 移进 AnnSearchRequest
        dense_req = AnnSearchRequest(
            [query_vec], "dense_vector", search_params,
            limit=top_k, expr=expr or "",
        )
        # 稀疏暂时没有真实向量，先不传
        # sparse_req = AnnSearchRequest(...)

        results = collection.hybrid_search(
            [dense_req],  # 只用 dense
            rerank=RRFRanker(k=60),
            limit=top_k,
            # ← 不放 expr
            output_fields=SCALAR_FIELDS,
        )[0]

        return self._results_to_search_results(results)

    # ── 3. 按 doc_id 删除 ──────────────────────────
    def delete_by_doc_id(self, doc_id: int) -> int:
        collection = Collection(self.collection_name)
        collection.load()
        result = collection.delete(expr=f"doc_id == {int(doc_id)}")
        collection.flush()
        return result.delete_count if hasattr(result, "delete_count") else len(result) if result else 0

    # ── 4. 统计 ─────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        return {"provider": "milvus", "collection": self.collection_name}


def create_vector_store():
    return MilvusVectorStore()


# if __name__ == "__main__":
#     create_vector_store()
