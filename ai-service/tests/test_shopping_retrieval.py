"""ShoppingRetriever + build_retrieval_plan 的单测（Phase 1b 版）。

Phase 1b 起 Retriever 内部走 Milvus 三路 + qwen3-rerank 两阶段；
Milvus/reranker 全 mock，pgvector 只在测降级路径时用。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.shopping.retrieval import (
    ShoppingRetriever,
    _dedupe_by_product_id,
    _pick_search_mode,
    _plan_to_milvus_filters,
    _relaxed_to_milvus_filters,
    _tag_recall_source,
    build_retrieval_plan,
)
from app.domain.shopping.schemas import ShoppingNeed, ShoppingRetrievalPlan
from app.infrastructure.config import config


# ---- build_retrieval_plan ------------------------------------------------

class TestBuildRetrievalPlan:
    def test_primary_query_contains_category(self):
        need = ShoppingNeed(category="防晒", skin_type="油皮", preferences=["清爽"])
        plan = build_retrieval_plan(need)
        assert "防晒" in plan.primary_query
        assert "油皮" in plan.primary_query
        assert "清爽" in plan.primary_query

    def test_filters_only_include_given_fields(self):
        need = ShoppingNeed(category="防晒", budget_max=200)
        plan = build_retrieval_plan(need)
        assert plan.filters["status"] == 1
        assert set(plan.filters) == {"status"}

    def test_user_constraints_are_left_for_candidate_judge(self):
        need = ShoppingNeed(category="防晒", budget_max=200)
        plan = build_retrieval_plan(need)
        assert plan.relaxed_filters == []
        assert plan.hard_filters == {"status": 1}

    def test_no_relaxed_pass_for_unknown_category(self):
        plan = build_retrieval_plan(ShoppingNeed(category="提神饮品", budget_max=200))
        assert plan.relaxed_filters == []

    def test_alias_category_is_normalized_before_filtering(self):
        plan = build_retrieval_plan(ShoppingNeed(category="抗初老精华"))
        assert plan.filters == {"status": 1}
        assert plan.hard_filters == {"status": 1}

    def test_unknown_category_remains_semantic_only(self):
        plan = build_retrieval_plan(ShoppingNeed(category="提神饮品"))
        assert plan.filters == {"status": 1}
        assert plan.hard_filters == {"status": 1}

    def test_use_rerank_true_in_phase_1b(self):
        """Phase 1b 默认走 rerank 两阶段。"""
        plan = build_retrieval_plan(ShoppingNeed(category="防晒"))
        assert plan.use_rerank is True

    def test_default_mode_is_hybrid(self):
        plan = build_retrieval_plan(ShoppingNeed(category="防晒"))
        assert plan.search_mode == "hybrid"


# ---- helper functions -----------------------------------------------------

class TestTagAndDedupe:
    def test_tag_recall_source_appends(self):
        items = [{"product_id": 1}, {"product_id": 2, "recall_sources": ["existing"]}]
        _tag_recall_source(items, "dense")
        assert items[0]["recall_sources"] == ["dense"]
        assert items[1]["recall_sources"] == ["existing", "dense"]

    def test_tag_recall_source_no_dup(self):
        items = [{"product_id": 1, "recall_sources": ["dense"]}]
        _tag_recall_source(items, "dense")
        assert items[0]["recall_sources"] == ["dense"]

    def test_dedupe_merges_recall_sources(self):
        items = [
            {"product_id": 1, "recall_sources": ["dense"], "title": "A"},
            {"product_id": 1, "recall_sources": ["bm25"], "title": "A2"},
            {"product_id": 2, "recall_sources": ["dense"], "title": "B"},
        ]
        out = _dedupe_by_product_id(items)
        assert len(out) == 2
        first = next(x for x in out if x["product_id"] == 1)
        assert first["title"] == "A"
        assert set(first["recall_sources"]) == {"dense", "bm25"}


class TestPickSearchMode:
    def test_explicit_mode_respected(self):
        plan = ShoppingRetrievalPlan(search_mode="dense")
        assert _pick_search_mode(plan, ShoppingNeed()) == "dense"

    def test_default_hybrid(self):
        plan = ShoppingRetrievalPlan()   # default hybrid
        assert _pick_search_mode(plan, ShoppingNeed()) == "hybrid"


class TestPlanToMilvusFilters:
    def test_from_need_defaults(self):
        need = ShoppingNeed(category="防晒", brand="X", budget_max=200)
        plan = ShoppingRetrievalPlan()
        f = _plan_to_milvus_filters(plan, need)
        assert f == {}

    def test_plan_filters_override_need(self):
        need = ShoppingNeed(category="防晒")
        plan = ShoppingRetrievalPlan(filters={"category": "面霜"})
        f = _plan_to_milvus_filters(plan, need)
        # Natural-language category filters are intentionally ignored by the
        # datastore adapter; only system-owned availability is filterable.
        assert f == {}


class TestRelaxedToMilvusFilters:
    def test_basic(self):
        f = _relaxed_to_milvus_filters({"category": "防晒", "budget_max": 240})
        assert f == {"category": "防晒", "budget_max": 240}

    def test_skip_none(self):
        f = _relaxed_to_milvus_filters({"category": "防晒", "budget_max": None})
        assert f == {"category": "防晒"}


# ---- ShoppingRetriever ---------------------------------------------------

class TestShoppingRetriever:
    def _milvus_mock(self, results):
        """构造一个 mock ProductMilvusStore，各路都返回同一批。"""
        store = MagicMock()
        store.search = MagicMock(return_value=results)
        store.hybrid_search = MagicMock(return_value=results)
        store.dense_search = MagicMock(return_value=results)
        store.bm25_search = MagicMock(return_value=results)
        return store

    def _rerank_mock(self, pairs):
        r = MagicMock()
        r.rerank = MagicMock(return_value=pairs)
        return r

    def test_hybrid_recall_with_rerank(self):
        candidates = [
            {"product_id": i, "title": f"P{i}", "score": 0.5 - i * 0.01,
             "recall_sources": []}
            for i in range(20)
        ]
        # rerank 把 idx=3 的顶到最前
        pairs = [(3, 0.99), (7, 0.87), (1, 0.75), (12, 0.63), (5, 0.51)]

        milvus = self._milvus_mock(candidates)
        rerank = self._rerank_mock(pairs)
        retriever = ShoppingRetriever(milvus_store=milvus, reranker=rerank)

        plan = ShoppingRetrievalPlan(top_k=5, initial_top_k=20, use_rerank=True)
        need = ShoppingNeed(category="防晒")
        out, trace = asyncio.run(retriever.retrieve(plan, need))

        assert len(out) == 5
        # 顺序按 rerank
        assert [r["product_id"] for r in out] == [3, 7, 1, 12, 5]
        assert out[0]["rerank_score"] == 0.99
        assert "rerank" in out[0]["recall_sources"]
        # trace 应该有 milvus_hybrid + rerank
        sources = [t.get("source") for t in trace]
        assert "milvus_hybrid" in sources
        assert "rerank" in sources

    def test_rerank_all_zero_falls_back_to_score(self):
        candidates = [
            {"product_id": 1, "title": "A", "score": 0.3, "recall_sources": []},
            {"product_id": 2, "title": "B", "score": 0.9, "recall_sources": []},
            {"product_id": 3, "title": "C", "score": 0.5, "recall_sources": []},
        ]
        milvus = self._milvus_mock(candidates)
        rerank = self._rerank_mock([(0, 0.0), (1, 0.0), (2, 0.0)])
        retriever = ShoppingRetriever(milvus_store=milvus, reranker=rerank)

        plan = ShoppingRetrievalPlan(top_k=3, use_rerank=True)
        out, _ = asyncio.run(retriever.retrieve(plan, ShoppingNeed(category="防晒")))
        # 按 score 降序
        assert [r["product_id"] for r in out] == [2, 3, 1]

    def test_rerank_off_returns_vector_order(self):
        candidates = [
            {"product_id": i, "title": f"P{i}", "score": 0.5 - i * 0.01, "recall_sources": []}
            for i in range(5)
        ]
        milvus = self._milvus_mock(candidates)
        retriever = ShoppingRetriever(milvus_store=milvus, reranker=MagicMock())

        plan = ShoppingRetrievalPlan(top_k=3, use_rerank=False)
        out, _ = asyncio.run(retriever.retrieve(plan, ShoppingNeed(category="防晒")))
        assert len(out) == 3
        # score 最高的三个
        assert [r["product_id"] for r in out] == [0, 1, 2]

    def test_milvus_failure_falls_back_to_pgvector(self):
        """Milvus 挂 → 降级 pgvector 单路。"""
        milvus = MagicMock()
        milvus.search = MagicMock(side_effect=RuntimeError("milvus down"))

        pg = MagicMock()
        pg.search = AsyncMock(return_value=[
            {"product_id": 100, "title": "PG 兜底商品", "price": 100},
        ])
        retriever = ShoppingRetriever(
            milvus_store=milvus, pg_vector_store=pg, reranker=MagicMock(),
        )

        plan = ShoppingRetrievalPlan(top_k=3, use_rerank=True)
        out, trace = asyncio.run(retriever.retrieve(plan, ShoppingNeed(category="防晒")))

        assert len(out) == 1
        assert out[0]["product_id"] == 100
        assert "pgvector_fallback" in out[0]["recall_sources"]
        # trace 应包含 milvus error + pgvector_fallback ok
        assert any(t["source"] == "milvus" and t["status"] == "error" for t in trace)
        assert any(t["source"] == "pgvector_fallback" and t["status"] == "ok" for t in trace)

    def test_relaxed_triggers_when_candidates_short(self):
        # 主召回只 1 个，relaxed 补 5 个
        main_results = [{"product_id": 1, "title": "A", "score": 0.5, "recall_sources": []}]
        relaxed_results = [
            {"product_id": i, "title": f"P{i}", "score": 0.3, "recall_sources": []}
            for i in range(2, 7)
        ]
        milvus = MagicMock()
        milvus.search = MagicMock(return_value=main_results)
        milvus.hybrid_search = MagicMock(return_value=relaxed_results)

        rerank = self._rerank_mock([(i, 0.5 - i * 0.05) for i in range(6)])
        retriever = ShoppingRetriever(milvus_store=milvus, reranker=rerank)

        need = ShoppingNeed(category="防晒", budget_max=200)
        plan = ShoppingRetrievalPlan(
            top_k=5,
            initial_top_k=20,
            use_rerank=True,
            relaxed_filters=[{"category": "防晒"}],
        )
        out, trace = asyncio.run(retriever.retrieve(plan, need))

        # 有 relaxed 补量
        assert any(t.get("source") == "relaxed" for t in trace)
        # 合并 + rerank 后应该有多个候选
        assert len(out) >= 1

    def test_search_mode_dense_is_respected(self):
        candidates = [{"product_id": 1, "title": "A", "score": 0.5, "recall_sources": []}]
        milvus = self._milvus_mock(candidates)
        rerank = self._rerank_mock([(0, 0.99)])
        retriever = ShoppingRetriever(milvus_store=milvus, reranker=rerank)

        plan = ShoppingRetrievalPlan(top_k=1, use_rerank=True, search_mode="dense")
        asyncio.run(retriever.retrieve(plan, ShoppingNeed(category="防晒")))

        # search 被调用时 mode=dense
        assert milvus.search.call_args.kwargs["mode"] == "dense"

    def test_three_path_hybrid_uses_text_dense_and_bm25_before_rerank(self):
        store = MagicMock()
        store.is_three_path_collection = True
        store.dense_search.return_value = [
            {"product_id": 1, "title": "A", "score": 0.9, "recall_sources": ["text_dense"]},
            {"product_id": 2, "title": "B", "score": 0.8, "recall_sources": ["text_dense"]},
        ]
        store.bm25_search.return_value = [
            {"product_id": 2, "title": "B", "score": 9.0, "recall_sources": ["bm25"]},
            {"product_id": 1, "title": "A", "score": 8.0, "recall_sources": ["bm25"]},
        ]
        rerank = self._rerank_mock([(1, 0.9), (0, 0.8)])
        retriever = ShoppingRetriever(milvus_store=store, reranker=rerank)

        with patch.object(config, "SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION", True):
            out, trace = asyncio.run(retriever.retrieve(
                ShoppingRetrievalPlan(top_k=2, initial_top_k=2, use_rerank=True),
                ShoppingNeed(category="防晒"),
            ))

        assert [item["product_id"] for item in out] == [2, 1]
        assert set(out[0]["recall_sources"]) >= {"text_dense", "bm25", "rerank"}
        store.dense_search.assert_called_once()
        store.bm25_search.assert_called_once()
        assert any(item["source"] == "milvus_three_path_hybrid" for item in trace)

    def test_category_fallback_is_removed(self):
        milvus = MagicMock()
        # 第一次带 category="护肤品" filter 返回空
        # 第二次无 category filter 返回 3 条
        fallback_hits = [
            {"product_id": i, "title": f"P{i}", "score": 0.5 - i * 0.01, "recall_sources": []}
            for i in range(3)
        ]
        milvus.search = MagicMock(side_effect=[[], fallback_hits])
        rerank = MagicMock()
        rerank.rerank = MagicMock(return_value=[(0, 0.9), (1, 0.8), (2, 0.7)])

        retriever = ShoppingRetriever(milvus_store=milvus, reranker=rerank)

        plan = ShoppingRetrievalPlan(
            top_k=3, use_rerank=True, filters={"category": "护肤品"},
        )
        need = ShoppingNeed(category="护肤品", budget_max=300)
        out, trace = asyncio.run(retriever.retrieve(plan, need))

        assert len(milvus.search.call_args_list) == 1
        assert milvus.search.call_args.kwargs["filters"] == {}
        assert out == []
