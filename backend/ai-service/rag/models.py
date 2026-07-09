from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field


class ChunkMetadata(BaseModel):
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    product_id: Optional[int] = None
    category_id: Optional[int] = None
    source: str = ""
    title: str = ""
    doc_type: str = "text"
    chunk_type: str = "text"
    page: Optional[int] = None
    chunk_index: int = 0
    total_chunks: int = 0
    content_hash: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    content: str
    metadata: ChunkMetadata


class RetrievalPlan(BaseModel):
    """Agent/LLM 对用户问题的结构化理解。"""

    intent: str = "knowledge_qa"
    query: str
    search_targets: List[str] = Field(default_factory=lambda: ["knowledge"])

    category: Optional[str] = None
    category_id: Optional[int] = None
    product_id: Optional[int] = None
    brand: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None

    skin_type: Optional[str] = None
    season: Optional[str] = None
    positive_requirements: List[str] = Field(default_factory=list)
    negative_requirements: List[str] = Field(default_factory=list)

    doc_types: List[str] = Field(default_factory=list)
    # 默认空 = 不过滤 chunk_type。原来默认 ["text"] 会把 marketing/faq/review 全过滤掉，
    # 是历史 knowledge_doc 场景遗留（只有一种 chunk_type）。需要限制时由 agent 显式传入。
    chunk_types: List[str] = Field(default_factory=list)
    top_k: int = 5
    # 默认 hybrid：dense + BM25 融合几乎总是优于任何单路
    # dense / bm25 / hybrid —— bm25 也接受 "sparse" 作别名
    search_mode: str = "hybrid"
    # ── 两阶段检索（rerank）参数 ──
    # 默认开 rerank：多一次 DashScope HTTP 调用 (~300ms)，换来质量显著提升
    use_rerank: bool = True
    # 初始召回数（送给 rerank 的候选量）。None → 走 config.RAG_INITIAL_TOP_K（默认 20）
    initial_top_k: Optional[int] = None


class MetadataFilter(BaseModel):
    """给向量库使用的结构化 metadata 过滤条件。"""

    doc_ids: Optional[List[int]] = None
    category_ids: Optional[List[int]] = None
    product_id: Optional[int] = None
    doc_types: Optional[List[str]] = None
    chunk_types: Optional[List[str]] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filter: Optional[MetadataFilter] = None
    # 默认 hybrid，与 RetrievalPlan 对齐
    search_mode: str = "hybrid"
    similarity_threshold: float = 0.3


class SearchResult(BaseModel):
    content: str
    metadata: ChunkMetadata
    score: float = 0.0
    dense_score: Optional[float] = None
    sparse_score: Optional[float] = None
    rerank_score: Optional[float] = None


class Source(BaseModel):
    doc_id: Optional[int] = None
    chunk_id: Optional[int] = None
    doc: str = ""
    page: Optional[int] = None
    chunk_index: Optional[int] = None
    score: float = 0.0


class RetrievalOutput(BaseModel):
    plan: RetrievalPlan
    results: List[SearchResult] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    knowledge_context: str = ""


class ParseRequest(BaseModel):
    file_path: str
    doc_id: int
    title: str = ""
    doc_type: str = "text"
    category_id: Optional[int] = None


class VectorStore(Protocol):
    def upsert_chunks(self, chunks: List[DocumentChunk]) -> int:
        ...

    def search(self, request: SearchRequest) -> List[SearchResult]:
        ...

    def delete_by_doc_id(self, doc_id: int) -> int:
        ...

    def stats(self) -> Dict[str, Any]:
        ...