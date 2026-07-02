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
    def __init__(self, vector_store=None):
        self.vector_store = vector_store or create_vector_store()

    def retrieve(self, plan: RetrievalPlan) -> RetrievalOutput:
        metadata_filter = build_metadata_filter(plan)
        request = SearchRequest(
            query=plan.query,
            top_k=plan.top_k,
            filter=metadata_filter,
            search_mode=plan.search_mode,
        )
        results = self.vector_store.hybrid_search(request)

        # TODO: 后续加 rerank、score normalization、business score。

        return RetrievalOutput(
            plan=plan,
            results=results,
            sources=build_sources(results),
            knowledge_context=build_knowledge_context(results),
        )


# retriever = Retriever()