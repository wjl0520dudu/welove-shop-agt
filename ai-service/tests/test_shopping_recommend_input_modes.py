"""All recommendation input modes return the common CandidateSet contract."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.shopping.capabilities.recommend import RecommendCapability
from app.domain.shopping.schemas import ShoppingContext


def _candidate(product_id: int = 7):
    return {
        "product_id": product_id,
        "title": "示例跑鞋",
        "base_price": 399,
        "price": 399,
        "category": "运动户外",
        "sub_category": "跑步鞋",
        "status": 1,
        "recall_sources": ["image_vector"],
    }


def _patch_turn_dependencies():
    return patch(
        "app.domain.shopping.capabilities.recommend.remember_product_cards",
        new=AsyncMock(),
    )


def test_pure_image_recommendation_does_not_fail_missing_text_category():
    async def run():
        cap = RecommendCapability()
        context = ShoppingContext(image_url="https://cdn.example.test/shoe.png", input_mode="image")
        with _patch_turn_dependencies(), patch(
            "app.domain.shopping.multimodal_search.search_multimodal_v1",
            new=AsyncMock(return_value=[_candidate()]),
        ), patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=AsyncMock(),
        ) as judge:
            result = await cap.run("根据图片找相似商品", context)

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "image"
        assert result.candidate_set.query_text == "根据图片找相似商品"
        assert result.product_cards
        assert result.product_cards[0]["match_status"] == "exact"
        judge.assert_not_awaited()

    asyncio.run(run())


def test_image_and_text_use_multimodal_candidate_set():
    async def run():
        cap = RecommendCapability()
        context = ShoppingContext(image_url="https://cdn.example.test/shoe.png", input_mode="multimodal")
        judge = AsyncMock(side_effect=lambda query, ranked, preferences: ranked)
        with _patch_turn_dependencies(), patch(
            "app.domain.shopping.multimodal_search.search_multimodal_v1",
            new=AsyncMock(return_value=[_candidate()]),
        ) as search, patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=judge,
        ):
            result = await cap.run("找类似跑鞋，预算 500 元以内", context)

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "multimodal"
        assert set(result.candidate_set.retrieval_channels) >= {"dense", "bm25", "image_vector"}
        assert search.await_args.kwargs["query_text"] == "找类似跑鞋，预算 500 元以内"
        judge.assert_awaited_once()

    asyncio.run(run())


def test_text_recommendation_uses_text_candidate_set():
    async def run():
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(return_value=([_candidate(8)], [{"source": "bm25", "status": "ok"}]))
        cap = RecommendCapability(retriever=retriever)
        judge = AsyncMock(side_effect=lambda query, ranked, preferences: ranked)
        with _patch_turn_dependencies(), patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=judge,
        ):
            result = await cap.run(
                "推荐通勤耳机",
                ShoppingContext(
                    input_mode="text",
                    user_preferences={"skin_type": "油皮", "preference_tags": ["清爽"]},
                ),
            )

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "text"
        assert result.candidate_set.candidates[0]["product_id"] == 8
        plan = retriever.retrieve.await_args.args[0]
        assert plan.primary_query == "推荐通勤耳机"
        judge.assert_awaited_once()
        assert judge.await_args.args[2] == {
            "skin_type": "油皮",
            "preference_tags": ["清爽"],
        }

    asyncio.run(run())
