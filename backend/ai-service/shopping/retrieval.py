"""ShoppingRetriever —— Capability 面对的检索抽象层。

## Phase 1a（本次）
内部继续用 PgVectorStore，多路降级为单路 dense（跟旧 shopping_tools.search_products 一致），
但对外暴露的接口和 Phase 1b（Milvus 三路）完全一致，切换时零改动 Capability。

## Phase 1b（下个 commit）
把 `_dense_recall` 换成 ProductMilvusStore.dense_search，
加上 `_bm25_recall` / `_hybrid_recall` / rerank 两阶段。

## 返回契约
retrieve() → (candidates: list[dict], trace: list[dict])
- candidates 每个 dict 至少含 product_id/title/brand/price/base_price/image_url/
  rating/sales_count/review_count/category/sub_category/tags/description，
  且带 `recall_sources: List[str]` 记录哪些召回路径找到了它（未来多路时用）。
- trace 供上层观测：[{"source":"dense","status":"ok","count":N}, ...]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from shopping.schemas import ShoppingNeed, ShoppingRetrievalPlan

logger = logging.getLogger("ai-service.shopping.retrieval")


class ShoppingRetriever:
    """Capability 依赖的检索器接口。

    Phase 1a 内部单路 pgvector，Phase 1b 切三路 Milvus + rerank。
    """

    def __init__(self, pg_vector_store=None):
        self._pg_vector_store = pg_vector_store  # 允许注入 mock 单测

    def _get_pg_store(self):
        """懒加载 PgVectorStore（pgvector 未安装时 ImportError，让上游降级）。"""
        if self._pg_vector_store is None:
            from pg_search.pgvector_store import PgVectorStore
            self._pg_vector_store = PgVectorStore()
        return self._pg_vector_store

    async def retrieve(
        self,
        plan: ShoppingRetrievalPlan,
        need: ShoppingNeed,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """按 plan 检索商品，返回 (candidates, trace)。

        Phase 1a 只跑 dense 一路，plan.semantic_queries 里的多个 query 依次跑，
        结果按 product_id 去重。
        """
        candidates: List[Dict[str, Any]] = []
        trace: List[Dict[str, Any]] = []

        # ── 稠密语义召回（唯一一路，MVP）──
        try:
            dense_results = await self._dense_recall(plan, need)
            _tag_recall_source(dense_results, "dense")
            candidates.extend(dense_results)
            trace.append({"source": "dense", "status": "ok", "count": len(dense_results)})
        except Exception as e:  # noqa: BLE001
            logger.warning("dense recall failed", exc_info=True)
            trace.append({"source": "dense", "status": "error", "message": str(e)})

        # ── 候选过少时的兜底：放宽 filter 再来一次 ──
        if len(candidates) < 5 and plan.relaxed_filters:
            try:
                relaxed_results = await self._relaxed_recall(plan, need)
                _tag_recall_source(relaxed_results, "relaxed")
                candidates.extend(relaxed_results)
                trace.append({"source": "relaxed", "status": "ok", "count": len(relaxed_results)})
            except Exception as e:  # noqa: BLE001
                logger.warning("relaxed recall failed", exc_info=True)
                trace.append({"source": "relaxed", "status": "error", "message": str(e)})

        # 按 product_id 去重，合并 recall_sources
        return _dedupe_by_product_id(candidates), trace

    # ---- 私有：具体召回路径 ----------------------------------------------

    async def _dense_recall(
        self, plan: ShoppingRetrievalPlan, need: ShoppingNeed
    ) -> List[Dict[str, Any]]:
        """pgvector 稠密召回。

        Phase 1b 切 Milvus 时，这个方法整体换成 milvus.dense_search，
        参数保持一样（query, filters, top_k）。
        """
        pg = self._get_pg_store()
        query = plan.primary_query or " ".join(plan.semantic_queries[:3]) or (need.category or "")
        results = await pg.search(
            query=query,
            top_k=max(plan.top_k, plan.initial_top_k),
            category=need.category,
            brand=need.brand,
            budget_min=need.budget_min,
            budget_max=need.budget_max,
            preferences=need.preferences,
            avoid=need.avoid,
            limit=plan.top_k,
        )
        return results or []

    async def _relaxed_recall(
        self, plan: ShoppingRetrievalPlan, need: ShoppingNeed
    ) -> List[Dict[str, Any]]:
        """按 plan.relaxed_filters 依次尝试，直到取到 5+ 个候选。

        Phase 1a 简单实现：只放宽预算和偏好；Milvus 阶段会做多档阶梯。
        """
        pg = self._get_pg_store()
        query = plan.primary_query or (need.category or "")
        # 只保留 category，最宽松一档
        results = await pg.search(
            query=query,
            top_k=plan.top_k,
            category=need.category,
            limit=plan.top_k,
        )
        return results or []


# ---- helper: 打标 + 去重 --------------------------------------------------


def _tag_recall_source(items: List[Dict[str, Any]], source: str) -> None:
    """给每个候选打上召回来源标签（去重时合并）。"""
    for item in items:
        srcs = item.setdefault("recall_sources", [])
        if source not in srcs:
            srcs.append(source)


def _dedupe_by_product_id(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 product_id 去重，保留首次出现顺序，合并 recall_sources。"""
    seen: Dict[int, Dict[str, Any]] = {}
    order: List[int] = []
    for item in items:
        pid = int(item.get("product_id") or item.get("id") or 0)
        if pid == 0:
            continue
        if pid in seen:
            # 合并 recall_sources
            for s in item.get("recall_sources") or []:
                if s not in seen[pid].setdefault("recall_sources", []):
                    seen[pid]["recall_sources"].append(s)
        else:
            seen[pid] = item
            order.append(pid)
    return [seen[pid] for pid in order]


def build_retrieval_plan(need: ShoppingNeed, top_k: int = 20) -> ShoppingRetrievalPlan:
    """把 ShoppingNeed 翻译成 ShoppingRetrievalPlan。

    独立函数好单测（不依赖 Retriever 实例）。
    """
    parts: List[str] = []
    if need.preferences:
        parts.extend(need.preferences[:3])
    if need.skin_type:
        parts.append(need.skin_type)
    if need.target_user:
        parts.append(need.target_user)
    if need.scenario:
        parts.extend(need.scenario[:2])
    if need.category:
        parts.append(need.category)
    primary = " ".join(parts) if parts else (need.category or "")

    semantic_queries = [primary]
    # 派生 query：category 单独一条兜底（当 primary 里塞了很多词时）
    if need.category and need.category not in semantic_queries:
        semantic_queries.append(need.category)
    if need.skin_type and need.category:
        semantic_queries.append(f"适合{need.skin_type}的{need.category}")

    filters: Dict[str, Any] = {}
    if need.category:
        filters["category"] = need.category
    if need.brand:
        filters["brand"] = need.brand
    if need.budget_min is not None:
        filters["budget_min"] = need.budget_min
    if need.budget_max is not None:
        filters["budget_max"] = need.budget_max

    relaxed: List[Dict[str, Any]] = []
    if need.budget_max is not None:
        # 预算 * 1.2 兜底
        relaxed.append({**filters, "budget_max": need.budget_max * 1.2})
    relaxed.append({"category": need.category} if need.category else {})

    return ShoppingRetrievalPlan(
        primary_query=primary,
        semantic_queries=[q for q in semantic_queries if q],
        keyword_queries=[need.brand] if need.brand else [],
        filters=filters,
        relaxed_filters=[r for r in relaxed if r],
        top_k=top_k,
        initial_top_k=top_k,
        use_rerank=False,   # Phase 1a pgvector 没有 rerank；1b Milvus 时切 True
    )
