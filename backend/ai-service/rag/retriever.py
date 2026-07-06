from __future__ import annotations

from typing import List

from rag.models import RetrievalOutput, RetrievalPlan, SearchRequest, SearchResult, Source
from rag.vector_store import build_metadata_filter, create_vector_store


def build_sources(results: List[SearchResult]) -> List[Source]:
    sources: List[Source] = []
    seen = set()

    for item in results:
        key = (item.metadata.doc_id, item.metadata.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            Source(
                doc_id=item.metadata.doc_id,
                chunk_id=item.metadata.chunk_id,
                doc=item.metadata.title or item.metadata.source,
                page=item.metadata.page,
                chunk_index=item.metadata.chunk_index,
                score=item.score,
            )
        )
    return sources


def build_knowledge_context(results: List[SearchResult]) -> str:
    blocks = []
    for index, item in enumerate(results, start=1):
        title = item.metadata.title or item.metadata.source or "未知来源"
        blocks.append(f"[资料{index}] 来源：{title}\n{item.content}")
    return "\n\n".join(blocks)


class Retriever:
    """RAG 检索器。vector_store 懒加载，避免 __init__ 时就连 Milvus。"""

    def __init__(self, vector_store=None):
        # 只保留调用方传入的实例，不立刻 create_vector_store()。
        # 真正的 Milvus 连接推迟到 self.vector_store 属性首次被访问时。
        self._vector_store = vector_store

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._vector_store = create_vector_store()
        return self._vector_store

    def retrieve(self, plan: RetrievalPlan) -> RetrievalOutput:
        metadata_filter = build_metadata_filter(plan)
        request = SearchRequest(
            query=plan.query,
            top_k=plan.top_k,
            filter=metadata_filter,
            search_mode=plan.search_mode,
        )
        if plan.search_mode == "hybrid" and hasattr(self.vector_store, "hybrid_search"):
            results = self.vector_store.hybrid_search(request)
        else:
            results = self.vector_store.search(request)

        results = sorted(results, key=lambda item: item.score or 0, reverse=True)

        return RetrievalOutput(
            plan=plan,
            results=results,
            sources=build_sources(results),
            knowledge_context=build_knowledge_context(results),
        )


# 懒加载单例：模块 import 时不去连 Milvus，避免 Milvus 挂了整个服务起不来。
# 第一次调用 get_retriever() 才真正建 Retriever + 连 Milvus。
# 若 Milvus 抖动，也只影响 knowledge agent，不会拖垮 shopping/chitchat。
_retriever_instance: Retriever | None = None


def get_retriever() -> Retriever:
    """懒获取 Retriever 单例。首次调用触发 Milvus 连接。"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = Retriever()
    return _retriever_instance

