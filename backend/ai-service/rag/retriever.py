from __future__ import annotations

import logging
from typing import List

from core.config import config
from rag.models import RetrievalOutput, RetrievalPlan, SearchRequest, SearchResult, Source
from rag.vector_store import build_metadata_filter, create_vector_store

logger = logging.getLogger("ai-service.rag.retriever")


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
    """RAG 检索器。

    两阶段检索：
      1. 初始召回：Milvus hybrid_search 拿 initial_top_k（默认 20）个候选
      2. 精排：DashScope qwen3-rerank 把 20 → top_k（默认 5）
    rerank 失败自动降级为纯 hybrid 结果（不阻断主流程）。
    """

    def __init__(self, vector_store=None, reranker=None):
        # vector_store / reranker 都懒加载：__init__ 不去连外部服务，
        # 让 Milvus/DashScope 抖动不影响模块 import
        self._vector_store = vector_store
        self._reranker = reranker

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._vector_store = create_vector_store()
        return self._vector_store

    @property
    def reranker(self):
        if self._reranker is None:
            # 懒 import：不用 rerank 时不加载 httpx client
            from rag.reranker import get_reranker
            self._reranker = get_reranker()
        return self._reranker

    def retrieve(self, plan: RetrievalPlan) -> RetrievalOutput:
        metadata_filter = build_metadata_filter(plan)

        # ── 阶段 1：初始召回 ──
        # 开启 rerank 时召回 initial_top_k（比 top_k 多几倍），关闭时直接召 top_k
        final_top_k = plan.top_k
        if plan.use_rerank:
            initial = plan.initial_top_k or config.RAG_INITIAL_TOP_K
            # 至少召回和 top_k 一样多，防止用户传了 top_k=10 但 initial_top_k=5 这种反常参数
            recall_top_k = max(initial, final_top_k)
        else:
            recall_top_k = final_top_k

        request = SearchRequest(
            query=plan.query,
            top_k=recall_top_k,
            filter=metadata_filter,
            search_mode=plan.search_mode,
        )
        recall_results = self.vector_store.search(request)

        # ── 阶段 2：rerank 精排 ──
        if plan.use_rerank and len(recall_results) > 1:
            recall_results = self._apply_rerank(plan.query, recall_results, final_top_k)
        else:
            # 未开 rerank：按向量分数排序 + 截断
            recall_results = sorted(recall_results, key=lambda x: x.score or 0, reverse=True)[:final_top_k]

        return RetrievalOutput(
            plan=plan,
            results=recall_results,
            sources=build_sources(recall_results),
            knowledge_context=build_knowledge_context(recall_results),
        )

    def _apply_rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_k: int,
    ) -> List[SearchResult]:
        """把 rerank 分数写回 SearchResult，按新分数排序 + 截断。

        rerank 失败（返回全 0 分）时退回向量分数排序 —— DashScopeReranker
        已经处理了异常，这里再兜一层：如果所有 rerank score 都是 0，认为失败。
        """
        docs = [r.content or "" for r in candidates]
        pairs = self.reranker.rerank(query=query, documents=docs, top_n=top_k)

        # 检测"全 0"降级信号：DashScopeReranker 失败时返回 [(0, 0), (1, 0), ...]
        if pairs and all(score == 0.0 for _, score in pairs):
            logger.warning("rerank 未生效（全 0 分），退回向量分数排序")
            return sorted(candidates, key=lambda x: x.score or 0, reverse=True)[:top_k]

        # 按 rerank 结果重排 + 写分数
        reranked: list[SearchResult] = []
        for idx, score in pairs:
            if idx < 0 or idx >= len(candidates):
                continue
            item = candidates[idx]
            item.rerank_score = score
            # 主 score 也用 rerank_score 覆盖 —— 前端/日志按 score 排序即为最终 rerank 顺序
            item.score = score
            reranked.append(item)
            if len(reranked) >= top_k:
                break
        return reranked


# 懒加载单例：模块 import 时不去连 Milvus/DashScope，避免任一挂了整个服务起不来。
# 第一次调用 get_retriever() 才真正建 Retriever + 连 Milvus。
# 若 Milvus 抖动，也只影响 knowledge agent，不会拖垮 shopping/chitchat。
_retriever_instance: Retriever | None = None


def get_retriever() -> Retriever:
    """懒获取 Retriever 单例。首次调用触发 Milvus 连接。"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = Retriever()
    return _retriever_instance
