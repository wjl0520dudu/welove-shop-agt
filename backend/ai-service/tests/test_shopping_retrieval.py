"""ShoppingRetriever + build_retrieval_plan 的单测。

不打真库；PgVectorStore.search 全 mock。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from shopping.retrieval import (
    ShoppingRetriever,
    _dedupe_by_product_id,
    _tag_recall_source,
    build_retrieval_plan,
)
from shopping.schemas import ShoppingNeed, ShoppingRetrievalPlan


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
        assert plan.filters["category"] == "防晒"
        assert plan.filters["budget_max"] == 200
        assert "budget_min" not in plan.filters
        assert "brand" not in plan.filters

    def test_relaxed_filters_include_budget_relaxed(self):
        need = ShoppingNeed(category="防晒", budget_max=200)
        plan = build_retrieval_plan(need)
        # 第一档：预算 * 1.2 = 240
        assert any(r.get("budget_max") == 240.0 for r in plan.relaxed_filters)
        # 最后一档：只保 category
        assert plan.relaxed_filters[-1] == {"category": "防晒"}

    def test_use_rerank_false_in_phase_1a(self):
        # Phase 1a pgvector 无 rerank
        plan = build_retrieval_plan(ShoppingNeed(category="防晒"))
        assert plan.use_rerank is False


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
        # 保留首个
        first = next(x for x in out if x["product_id"] == 1)
        assert first["title"] == "A"
        assert set(first["recall_sources"]) == {"dense", "bm25"}


class TestShoppingRetriever:
    def test_dense_recall_success(self):
        """Retriever 应从 PgVectorStore 拿结果并打上 dense 标签。"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(return_value=[
            {"product_id": 1, "title": "A"},
            {"product_id": 2, "title": "B"},
        ])
        retriever = ShoppingRetriever(pg_vector_store=mock_store)

        need = ShoppingNeed(category="防晒")
        plan = build_retrieval_plan(need)

        candidates, trace = asyncio.run(retriever.retrieve(plan, need))
        assert len(candidates) == 2
        assert all("dense" in c["recall_sources"] for c in candidates)
        # trace 应该有 dense ok
        dense_step = next(t for t in trace if t["source"] == "dense")
        assert dense_step["status"] == "ok"

    def test_dense_recall_failure_falls_back(self):
        """PG 抛错时 Retriever 返回空且 trace 记录 error，不炸。"""
        mock_store = MagicMock()
        mock_store.search = AsyncMock(side_effect=RuntimeError("pgvector down"))
        retriever = ShoppingRetriever(pg_vector_store=mock_store)

        need = ShoppingNeed(category="防晒")
        plan = build_retrieval_plan(need)

        candidates, trace = asyncio.run(retriever.retrieve(plan, need))
        # dense 失败 + relaxed 也用同一 store 会失败 → candidates 应该为空
        assert candidates == []
        assert any(t["source"] == "dense" and t["status"] == "error" for t in trace)

    def test_relaxed_recall_triggers_when_short(self):
        """dense 只返回 1 个 → 触发 relaxed_recall。"""
        mock_store = MagicMock()
        # 第一次调用返回 1 个，第二次（relaxed）返回 5 个
        mock_store.search = AsyncMock(side_effect=[
            [{"product_id": 1, "title": "A"}],
            [{"product_id": i, "title": f"P{i}"} for i in range(2, 7)],
        ])
        retriever = ShoppingRetriever(pg_vector_store=mock_store)

        need = ShoppingNeed(category="防晒", budget_max=200)
        plan = build_retrieval_plan(need)

        candidates, trace = asyncio.run(retriever.retrieve(plan, need))
        assert len(candidates) == 6   # 1 + 5，去重后仍为 6（id 不重复）
        # trace 里应该有 relaxed 一档
        assert any(t["source"] == "relaxed" for t in trace)
