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
    chunk_types: List[str] = Field(default_factory=lambda: ["text"])
    top_k: int = 5
    search_mode: str = "dense"  # dense | sparse | hybrid


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
    search_mode: str = "dense"
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