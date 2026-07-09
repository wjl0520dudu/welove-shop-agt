"""ShoppingRetriever —— Capability 面对的检索抽象层。

## Phase 1b（本次）
- 内部从 PgVectorStore 切成 ProductMilvusStore（三路 + rerank 两阶段）；
- 对外接口和 Phase 1a 一致 —— Capability 完全零改动；
- pgvector 保留作为**降级路径**：Milvus 挂了自动 fallback，线上不中断。

## 两阶段检索
```
hybrid_search(top_k=initial_top_k=20)
    ↓
qwen3-rerank(query, docs, top_n=final_top_k)
    ↓
final top_k
```
失败降级：rerank 返回全 0 → 走 recall 阶段的向量分数排序。

## 三路开关
`ShoppingRetrievalPlan.search_mode` = "hybrid" | "dense" | "bm25"，
Capability 层可以显式指定；MVP 默认 hybrid。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.config import config
from shopping.schemas import ShoppingNeed, ShoppingRetrievalPlan

logger = logging.getLogger("ai-service.shopping.retrieval")


class ShoppingRetriever:
    """Capability 依赖的检索器。

    Phase 1b：内部 Milvus 三路 + qwen3-rerank；
    Milvus 不可用时降级到 pgvector 单路 dense。
    """

    def __init__(
        self,
        milvus_store=None,
        pg_vector_store=None,
        reranker=None,
    ):
        # 支持三种注入（都可 mock 单测）
        self._milvus_store = milvus_store
        self._pg_vector_store = pg_vector_store
        self._reranker = reranker

    # ── 懒加载单例 ──────────────────────────────────────────

    def _get_milvus_store(self):
        if self._milvus_store is None:
            from shopping.vector_store import get_product_milvus_store
            self._milvus_store = get_product_milvus_store()
        return self._milvus_store

    def _get_pg_store(self):
        if self._pg_vector_store is None:
            from pg_search.pgvector_store import PgVectorStore
            self._pg_vector_store = PgVectorStore()
        return self._pg_vector_store

    def _get_reranker(self):
        if self._reranker is None:
            from rag.reranker import get_reranker
            self._reranker = get_reranker()
        return self._reranker

    # ── 主入口 ──────────────────────────────────────────────
    async def retrieve(
        self,
        plan: ShoppingRetrievalPlan,
        need: ShoppingNeed,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """按 plan 检索商品，返回 (candidates, trace)。

        Pipeline:
        1. 主链路：Milvus dense/bm25/hybrid（按 plan.search_mode）+ 服务端 filter；
        2. 若 plan.use_rerank：qwen3-rerank 两阶段精排；
        3. 若 candidates < 5：走 relaxed 兜底（去掉部分 filter 重新召回）；
        4. Milvus 不可用：整体降级到 pgvector 单路 dense（Phase 1a 的老路径）。
        """
        trace: List[Dict[str, Any]] = []
        candidates: List[Dict[str, Any]] = []

        # ── 主链路：Milvus 三路 + rerank ──
        try:
            candidates = await self._milvus_recall(plan, need, trace)
        except Exception as e:  # noqa: BLE001
            logger.warning("Milvus recall failed, fallback to pgvector: %s", e, exc_info=True)
            trace.append({"source": "milvus", "status": "error", "message": str(e)})
            # ── 降级：pgvector 单路 ──
            try:
                candidates = await self._pgvector_fallback(plan, need)
                _tag_recall_source(candidates, "pgvector_fallback")
                trace.append({"source": "pgvector_fallback", "status": "ok", "count": len(candidates)})
            except Exception as e2:  # noqa: BLE001
                logger.warning("pgvector fallback also failed: %s", e2, exc_info=True)
                trace.append({"source": "pgvector_fallback", "status": "error", "message": str(e2)})
                candidates = []

        # ── relaxed 兜底：候选过少时放宽 filter 再来一次 ──
        if len(candidates) < 5 and plan.relaxed_filters:
            try:
                relaxed = await self._milvus_relaxed_recall(plan, need)
                if relaxed:
                    _tag_recall_source(relaxed, "relaxed")
                    # 去重合并：Milvus 主召回和 relaxed 可能重叠
                    candidates = _dedupe_by_product_id(candidates + relaxed)
                    trace.append({"source": "relaxed", "status": "ok", "count": len(relaxed)})
            except Exception as e:  # noqa: BLE001
                logger.warning("relaxed recall failed: %s", e)
                trace.append({"source": "relaxed", "status": "error", "message": str(e)})

        return candidates, trace

    # ── Milvus 主召回（含 rerank）──────────────────────────
    async def _milvus_recall(
        self,
        plan: ShoppingRetrievalPlan,
        need: ShoppingNeed,
        trace: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        store = self._get_milvus_store()
        query = plan.primary_query or (need.category or "")

        # rerank 开启时，第一阶段要多召回一些候选
        final_top_k = plan.top_k
        recall_top_k = max(plan.initial_top_k or config.RAG_INITIAL_TOP_K, final_top_k) \
            if plan.use_rerank else final_top_k

        filters = _plan_to_milvus_filters(plan, need)

        # Phase 1b 支持三路开关（默认 hybrid）
        mode = _pick_search_mode(plan, need)
        results = store.search(
            query=query,
            mode=mode,
            filters=filters,
            top_k=recall_top_k,
        )
        _tag_recall_source(results, mode)
        trace.append({"source": f"milvus_{mode}", "status": "ok", "count": len(results),
                      "filters": filters, "query": query})

        # ── category 兜底：filter 里带了 category 但零命中 → 去掉 category 再来一次 ──
        # 场景：LLM 抽出的 category 词跟库里两级类目都对不上（如 "护肤品" vs 库里
        # "美妆护肤/面霜"）。语义 hybrid 本身对 "护肤品" 的召回能力是好的，只是被
        # 死板的 filter 拦掉了 —— 松掉 filter 让 hybrid 语义救场。
        if not results and filters.get("category"):
            no_cat_filters = {k: v for k, v in filters.items() if k not in ("category", "sub_category")}
            fallback_results = store.search(
                query=query,
                mode=mode,
                filters=no_cat_filters,
                top_k=recall_top_k,
            )
            if fallback_results:
                _tag_recall_source(fallback_results, f"{mode}_no_cat")
                trace.append({"source": f"milvus_{mode}_no_cat", "status": "ok",
                              "count": len(fallback_results), "filters": no_cat_filters,
                              "note": "category 精确匹配失败，走无 category filter 语义召回兜底"})
                results = fallback_results

        if not results:
            return []

        # ── rerank 两阶段 ──
        if plan.use_rerank and len(results) > 1:
            reranked = self._apply_rerank(query, results, final_top_k)
            trace.append({"source": "rerank", "status": "ok",
                          "in": len(results), "out": len(reranked)})
            return reranked

        # 不 rerank：按向量分数排序截 top_k
        return sorted(results, key=lambda r: r.get("score", 0), reverse=True)[:final_top_k]

    def _apply_rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        final_top_k: int,
    ) -> List[Dict[str, Any]]:
        """qwen3-rerank 精排。失败时退回向量分数排序。"""
        try:
            reranker = self._get_reranker()
        except Exception as e:  # noqa: BLE001
            logger.warning("Reranker not available, skip: %s", e)
            return sorted(candidates, key=lambda r: r.get("score", 0), reverse=True)[:final_top_k]

        docs = [_build_rerank_doc(c) for c in candidates]
        pairs = reranker.rerank(query, docs, top_n=final_top_k)

        # 全 0 分（客户端降级信号）→ 退回向量分数
        if pairs and all(score == 0.0 for _, score in pairs):
            return sorted(candidates, key=lambda r: r.get("score", 0), reverse=True)[:final_top_k]

        out: List[Dict[str, Any]] = []
        for idx, score in pairs:
            if 0 <= idx < len(candidates):
                item = dict(candidates[idx])
                item["rerank_score"] = float(score)
                item["score"] = float(score)   # 覆盖成 rerank 分数供 Ranker 参考
                # 打标：这个候选经过 rerank
                srcs = item.setdefault("recall_sources", [])
                if "rerank" not in srcs:
                    srcs.append("rerank")
                out.append(item)
        return out

    # ── Milvus relaxed 兜底 ─────────────────────────────────
    async def _milvus_relaxed_recall(
        self,
        plan: ShoppingRetrievalPlan,
        need: ShoppingNeed,
    ) -> List[Dict[str, Any]]:
        """按 plan.relaxed_filters 依次放宽，取第一个能出 5+ 结果的档。"""
        store = self._get_milvus_store()
        query = plan.primary_query or (need.category or "")

        for relaxed in plan.relaxed_filters:
            filters = _relaxed_to_milvus_filters(relaxed)
            try:
                results = store.hybrid_search(query, filters=filters, top_k=plan.top_k)
                if results:
                    return results
            except Exception as e:  # noqa: BLE001
                logger.warning("relaxed recall step failed (%s): %s", filters, e)
                continue
        return []

    # ── pgvector 降级路径 ───────────────────────────────────
    async def _pgvector_fallback(
        self,
        plan: ShoppingRetrievalPlan,
        need: ShoppingNeed,
    ) -> List[Dict[str, Any]]:
        """Milvus 挂时的最后一道防线：pgvector 单路 dense。"""
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


# ---- helper functions ----------------------------------------------------


def _pick_search_mode(plan: ShoppingRetrievalPlan, need: ShoppingNeed) -> str:
    """选检索模式。

    - plan.search_mode 明确指定时按它走（供 A/B 测试）；
    - 否则默认 hybrid。
    """
    mode = getattr(plan, "search_mode", None)
    if mode in ("dense", "bm25", "sparse", "hybrid"):
        return mode
    return "hybrid"


def _plan_to_milvus_filters(
    plan: ShoppingRetrievalPlan, need: ShoppingNeed
) -> Dict[str, Any]:
    """把 plan + need 翻译成 ProductMilvusStore.search 的 filters dict。

    优先用 plan.filters（Capability 可能自定义），缺失字段从 need 补。
    """
    filters: Dict[str, Any] = dict(plan.filters or {})
    if need.category and not filters.get("category"):
        filters["category"] = need.category
    if need.brand and not filters.get("brand"):
        filters["brand"] = need.brand
    if need.budget_min is not None and "budget_min" not in filters:
        filters["budget_min"] = need.budget_min
    if need.budget_max is not None and "budget_max" not in filters:
        filters["budget_max"] = need.budget_max
    return filters


def _relaxed_to_milvus_filters(relaxed: Dict[str, Any]) -> Dict[str, Any]:
    """把 relaxed_filters 的一条翻译成 Milvus filters。

    支持字段和 _plan_to_milvus_filters 一致。
    """
    out: Dict[str, Any] = {}
    for key in ("category", "sub_category", "brand"):
        v = relaxed.get(key)
        if v:
            out[key] = v
    if "budget_max" in relaxed and relaxed["budget_max"] is not None:
        out["budget_max"] = relaxed["budget_max"]
    if "budget_min" in relaxed and relaxed["budget_min"] is not None:
        out["budget_min"] = relaxed["budget_min"]
    return out


def _build_rerank_doc(item: Dict[str, Any]) -> str:
    """为 rerank 拼一条 doc：title + tags + description。

    rerank 模型只看文本，商品数值字段（price/rating）它不理解，别塞进去。
    """
    title = str(item.get("title") or "")
    brand = str(item.get("brand") or "")
    tags = str(item.get("tags") or "")
    desc = str(item.get("description") or "")
    return " ".join([title, brand, tags, desc[:400]]).strip()


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
        pid = int(item.get("product_id") or 0)
        if pid == 0:
            continue
        if pid in seen:
            for s in item.get("recall_sources") or []:
                if s not in seen[pid].setdefault("recall_sources", []):
                    seen[pid]["recall_sources"].append(s)
        else:
            seen[pid] = item
            order.append(pid)
    return [seen[pid] for pid in order]


# ---- build_retrieval_plan（供 Capability 用）------------------------------

def build_retrieval_plan(need: ShoppingNeed, top_k: int = 5) -> ShoppingRetrievalPlan:
    """把 ShoppingNeed 翻译成 ShoppingRetrievalPlan（Phase 1b 版）。

    - top_k：最终返回给排序器的候选数（默认 5）
    - initial_top_k：hybrid 一路的召回数（默认 config.RAG_INITIAL_TOP_K=20）
    - use_rerank：默认 True，走两阶段精排
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
    if need.brand:
        parts.append(need.brand)
    primary = " ".join(parts) if parts else (need.category or "")

    semantic_queries = [primary]
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
        relaxed.append({**filters, "budget_max": need.budget_max * 1.2})
    if need.category:
        relaxed.append({"category": need.category})

    # 召回数：rerank 需要更多候选（默认 20）；不 rerank 直接按 top_k
    initial_top_k = config.RAG_INITIAL_TOP_K

    return ShoppingRetrievalPlan(
        primary_query=primary,
        semantic_queries=[q for q in semantic_queries if q],
        keyword_queries=[need.brand] if need.brand else [],
        filters=filters,
        relaxed_filters=[r for r in relaxed if r],
        top_k=top_k,
        initial_top_k=initial_top_k,
        use_rerank=True,   # Phase 1b：默认开 rerank
    )
