"""Focused tests for the single-Judge recommendation pipeline."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.shopping.capabilities.recommend import RecommendCapability
from app.domain.shopping.schemas import RankedProduct, ShoppingContext


def _ctx(**kwargs):
    values = {"conversation_id": "c1", "user_id": "u1", "is_logged_in": True}
    values.update(kwargs)
    return ShoppingContext(**values)


def _candidate(product_id: int = 1):
    return {
        "product_id": product_id,
        "title": "示例耳机",
        "price": 699,
        "base_price": 699,
        "category": "数码家电",
        "sub_category": "真无线耳机",
        "status": 1,
        "score": 0.9,
        "recall_sources": ["hybrid"],
    }


def _remember_cards_patch():
    return patch(
        "app.domain.shopping.capabilities.recommend.remember_product_cards",
        new=AsyncMock(),
    )


def test_empty_text_without_image_clarifies_before_retrieval():
    retriever = MagicMock()
    retriever.retrieve = AsyncMock()
    result = asyncio.run(
        RecommendCapability(retriever=retriever).run("", _ctx())
    )

    assert result.action == "clarify"
    assert result.clarify_question
    retriever.retrieve.assert_not_awaited()


def test_complete_budget_query_reaches_retrieval_without_second_parse():
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=([_candidate()], [{"source": "hybrid", "status": "ok"}])
    )
    ranked = RankedProduct(
        product_id=1,
        title="示例耳机",
        price=699,
        base_price=699,
        category="数码家电",
        sub_category="真无线耳机",
        score=0.9,
    )
    judged = ranked.model_copy(
        update={
            "match_status": "alternative",
            "constraint_gaps": [{"name": "budget", "expected": "500", "actual": "699"}],
        }
    )
    judge = AsyncMock(return_value=[judged])

    async def run():
        with _remember_cards_patch(), patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=judge,
        ):
            return await RecommendCapability(retriever=retriever).run(
                "推荐几款 500 元以内的耳机",
                _ctx(),
            )

    result = asyncio.run(run())

    assert result.action == "recommend"
    assert result.product_cards[0]["match_status"] == "alternative"
    plan = retriever.retrieve.await_args.args[0]
    assert plan.primary_query == "推荐几款 500 元以内的耳机"
    assert "parse_need" not in [item["step"] for item in result.trace]
    judge.assert_awaited_once()


def test_retrieval_order_reaches_judge_without_legacy_reranking():
    unrelated = _candidate(10)
    unrelated.update({
        "title": "笔记本电脑",
        "sub_category": "笔记本电脑",
    })
    headphones = _candidate(11)
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=([unrelated, headphones], [{"source": "hybrid", "status": "ok"}])
    )

    async def judge(_query, ranked, _preferences):
        assert [item.product_id for item in ranked] == [10, 11]
        return [ranked[1].model_copy(update={"match_status": "alternative"})]

    async def run():
        with _remember_cards_patch(), patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=AsyncMock(side_effect=judge),
        ):
            return await RecommendCapability(retriever=retriever).run(
                "推荐几款 500 元以内的耳机",
                _ctx(),
            )

    result = asyncio.run(run())

    assert result.action == "recommend"
    assert [card["product_id"] for card in result.product_cards] == [11]
    assert result.product_cards[0]["match_status"] == "alternative"


def test_empty_retrieval_result_returns_empty_without_judge():
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=([], []))
    judge = AsyncMock()

    async def run():
        with patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=judge,
        ):
            return await RecommendCapability(retriever=retriever).run(
                "推荐不存在的商品类型",
                _ctx(),
            )

    result = asyncio.run(run())

    assert result.action == "empty"
    assert result.empty_reason
    judge.assert_not_awaited()
