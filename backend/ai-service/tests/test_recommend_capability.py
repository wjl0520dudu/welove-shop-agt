"""RecommendCapability 全流程单测（parse_need + merge + clarify + retrieval + rank）。

不打真 LLM/PG：
- parse_need_llm 全程 mock；
- Retriever + Ranker 通过构造函数注入 mock/真实实例；
- Store（remember/get pending）全 mock。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from shopping.capabilities.recommend import (
    RecommendCapability,
    _looks_like_compare,
    _looks_like_detail,
    build_clarify_question,
    get_missing_required_slots,
    merge_shopping_need,
)
from shopping.ranking import ProductRanker
from shopping.schemas import ShoppingContext, ShoppingNeed


def _ctx(**kwargs):
    kw = {"conversation_id": "c1", "user_id": "u1", "is_logged_in": True}
    kw.update(kwargs)
    return ShoppingContext(**kw)


class TestMergeShoppingNeed:
    def test_new_overrides_scalar(self):
        old = ShoppingNeed(category="防晒", skin_type="油皮")
        new = ShoppingNeed(skin_type="干皮", budget_max=200)
        merged = merge_shopping_need(old, new)
        assert merged.category == "防晒"      # old 保留
        assert merged.skin_type == "干皮"      # new 覆盖
        assert merged.budget_max == 200        # new 新增

    def test_list_fields_dedupe_union(self):
        old = ShoppingNeed(preferences=["清爽", "保湿"], avoid=["油腻"])
        new = ShoppingNeed(preferences=["清爽", "便携"], avoid=["香味重"])
        merged = merge_shopping_need(old, new)
        assert set(merged.preferences) == {"清爽", "保湿", "便携"}
        assert set(merged.avoid) == {"油腻", "香味重"}

    def test_missing_slots_uses_new(self):
        old = ShoppingNeed(missing_slots=["category"])
        new = ShoppingNeed(category="防晒", missing_slots=[])
        merged = merge_shopping_need(old, new)
        assert merged.missing_slots == []


class TestClarifyGate:
    def test_missing_category(self):
        assert get_missing_required_slots(ShoppingNeed()) == ["category"]

    def test_category_present_no_missing(self):
        assert get_missing_required_slots(ShoppingNeed(category="防晒")) == []

    def test_gift_question_when_scenario_gift(self):
        need = ShoppingNeed(scenario=["礼物"], target_user="妈妈")
        q = build_clarify_question(need, ["category"])
        assert "妈妈" in q or "对方" in q

    def test_normal_category_question(self):
        q = build_clarify_question(ShoppingNeed(), ["category"])
        assert "哪类商品" in q


class TestWrongCapabilityCheck:
    def test_compare_detected(self):
        ctx = _ctx(last_product_cards=[{"product_id": 1}, {"product_id": 2}])
        assert _looks_like_compare("这两个对比一下", ctx) is True

    def test_no_compare_without_history(self):
        ctx = _ctx(last_product_cards=[])
        assert _looks_like_compare("这两个对比一下", ctx) is False

    def test_detail_detected(self):
        ctx = _ctx(last_focused_product={"product_id": 1, "title": "A"})
        assert _looks_like_detail("这个多少钱", ctx) is True

    def test_no_detail_without_history(self):
        ctx = _ctx()
        assert _looks_like_detail("这个多少钱", ctx) is False


class TestRecommendCapabilityRun:
    """RecommendCapability.run 主流程（parse + retrieve + rank + cards）。"""

    def _patch_llm(self, parsed_need):
        """把 parse_need_llm 替换成同步返回给定 ShoppingNeed。"""
        return patch(
            "shopping.capabilities.recommend._parse_need_llm",
            new=AsyncMock(return_value=parsed_need),
        )

    def _patch_pending(self, pending=None):
        return (
            patch(
                "shopping.capabilities.recommend.get_pending_shopping_need",
                new=AsyncMock(return_value=pending),
            ),
            patch(
                "shopping.capabilities.recommend.remember_pending_shopping_need",
                new=AsyncMock(),
            ),
            patch(
                "shopping.capabilities.recommend.clear_pending_shopping_need",
                new=AsyncMock(),
            ),
            patch(
                "shopping.capabilities.recommend.remember_product_cards",
                new=AsyncMock(),
            ),
        )

    def test_wrong_capability_compare(self):
        """query 明显是对比 + 有历史卡片 → 返回 WRONG_CAPABILITY。"""
        cap = RecommendCapability()
        ctx = _ctx(last_product_cards=[{"product_id": 1}, {"product_id": 2}])

        async def run():
            return await cap.run(query="这两个对比一下", context=ctx)

        result = asyncio.run(run())
        assert result.action == "empty"
        assert result.empty_reason and "compare_products" in result.empty_reason

    def test_wrong_capability_detail(self):
        cap = RecommendCapability()
        ctx = _ctx(last_focused_product={"product_id": 1, "title": "A"})

        async def run():
            return await cap.run(query="这个多少钱", context=ctx)

        result = asyncio.run(run())
        assert result.action == "empty"
        assert "answer_product_detail" in (result.empty_reason or "")

    def test_missing_category_triggers_clarify(self):
        """parse_need 返回空 category → clarify。"""
        parsed = ShoppingNeed(missing_slots=["category"])
        cap = RecommendCapability()

        p_pending, p_remember, p_clear, p_cards = self._patch_pending(pending=None)

        async def run():
            with self._patch_llm(parsed), p_pending, p_remember, p_clear, p_cards:
                return await cap.run(query="推荐一下", context=_ctx())

        result = asyncio.run(run())
        assert result.action == "clarify"
        assert result.clarify_question
        assert "哪类商品" in result.clarify_question

    def test_two_turn_merge_produces_recommend(self):
        """第一轮 clarify 后 pending 存了 target_user=妈妈，第二轮补 category=护肤 → 合并后可走 recommend。"""
        pending_dict = {
            "status": "clarifying",
            "need": ShoppingNeed(target_user="妈妈", scenario=["礼物"]).model_dump(),
            "missing_slots": ["category"],
            "last_clarify_question": "?",
            "turn_count": 1,
        }
        parsed_current = ShoppingNeed(category="护肤品", budget_max=300)

        # Phase 1b：主链路走 Milvus，注入 milvus_store mock（不再是 pg_vector_store）
        mock_milvus = MagicMock()
        candidates = [
            {"product_id": 1, "title": "面霜", "price": 250, "base_price": 250, "brand": "X",
             "tags": "护肤 保湿", "description": "适合成熟肌肤", "category": "护肤品",
             "sales_count": 500, "rating": 4.7, "score": 0.9, "recall_sources": []},
            {"product_id": 2, "title": "精华", "price": 280, "base_price": 280, "brand": "Y",
             "tags": "护肤 抗老", "description": "抗初老", "category": "护肤品",
             "sales_count": 300, "rating": 4.6, "score": 0.85, "recall_sources": []},
        ]
        mock_milvus.search = MagicMock(return_value=candidates)
        mock_milvus.hybrid_search = MagicMock(return_value=candidates)

        # rerank 直接把两个候选按原顺序返回（保持真实概率）
        mock_rerank = MagicMock()
        mock_rerank.rerank = MagicMock(return_value=[(0, 0.95), (1, 0.85)])

        from shopping.retrieval import ShoppingRetriever
        cap = RecommendCapability(
            retriever=ShoppingRetriever(milvus_store=mock_milvus, reranker=mock_rerank),
        )

        p_pending, p_remember, p_clear, p_cards = self._patch_pending(pending=pending_dict)

        async def run():
            with self._patch_llm(parsed_current), p_pending, p_remember, p_clear, p_cards:
                return await cap.run(query="护肤品，300 左右", context=_ctx(), limit=3)

        result = asyncio.run(run())
        assert result.action == "recommend"
        # merge 后 need 应该同时含 target_user 和 category
        assert result.need.target_user == "妈妈"
        assert result.need.category == "护肤品"
        assert result.need.budget_max == 300
        # 应该有 cards
        assert len(result.product_cards) >= 1
        # trace 应含 rank 步骤
        steps = [t["step"] for t in result.trace]
        assert "rank" in steps
        assert "retrieval" in steps

    def test_empty_candidates_returns_empty(self):
        """检索无结果 → action=empty。"""
        parsed = ShoppingNeed(category="不存在的品类")
        # Phase 1b：主链路 Milvus，注入空 milvus_store（不再是 pg_vector_store）
        mock_milvus = MagicMock()
        mock_milvus.search = MagicMock(return_value=[])
        mock_milvus.hybrid_search = MagicMock(return_value=[])
        from shopping.retrieval import ShoppingRetriever
        cap = RecommendCapability(
            retriever=ShoppingRetriever(milvus_store=mock_milvus, reranker=MagicMock()),
        )

        p_pending, p_remember, p_clear, p_cards = self._patch_pending(pending=None)

        async def run():
            with self._patch_llm(parsed), p_pending, p_remember, p_clear, p_cards:
                return await cap.run(query="推荐个不存在的品类", context=_ctx())

        result = asyncio.run(run())
        assert result.action == "empty"
        assert result.empty_reason
