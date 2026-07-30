"""All recommendation input modes return the common CandidateSet contract."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.shopping.capabilities.recommend import RecommendCapability
from app.domain.shopping.schemas import RankedProduct, ShoppingContext, ShoppingNeed


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
    return (
        patch(
            "app.domain.shopping.capabilities.recommend.get_pending_shopping_need",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.domain.shopping.capabilities.recommend.clear_pending_shopping_need",
            new=AsyncMock(),
        ),
        patch(
            "app.domain.shopping.capabilities.recommend.remember_product_cards",
            new=AsyncMock(),
        ),
    )


def test_pure_image_recommendation_does_not_fail_missing_text_category():
    async def run():
        cap = RecommendCapability()
        context = ShoppingContext(image_url="https://cdn.example.test/shoe.png", input_mode="image")
        dependencies = _patch_turn_dependencies()
        with dependencies[0], dependencies[1], dependencies[2], patch(
            "app.domain.shopping.capabilities.recommend._parse_need_llm",
            new=AsyncMock(return_value=ShoppingNeed()),
        ), patch(
            "app.domain.shopping.multimodal_search.search_multimodal_v1",
            new=AsyncMock(return_value=[_candidate()]),
        ):
            result = await cap.run("根据图片找相似商品", context)

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "image"
        assert result.candidate_set.query_text == "根据图片找相似商品"
        assert result.product_cards

    asyncio.run(run())


def test_image_and_text_use_multimodal_candidate_set():
    async def run():
        cap = RecommendCapability()
        context = ShoppingContext(image_url="https://cdn.example.test/shoe.png", input_mode="multimodal")
        dependencies = _patch_turn_dependencies()
        with dependencies[0], dependencies[1], dependencies[2], patch(
            "app.domain.shopping.capabilities.recommend._parse_need_llm",
            new=AsyncMock(return_value=ShoppingNeed(category="跑步鞋", budget_max=500)),
        ), patch(
            "app.domain.shopping.multimodal_search.search_multimodal_v1",
            new=AsyncMock(return_value=[_candidate()]),
        ) as search:
            result = await cap.run("找类似跑鞋，预算 500 元以内", context)

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "multimodal"
        assert set(result.candidate_set.retrieval_channels) >= {"dense", "bm25", "image_vector"}
        assert search.await_args.kwargs["query_text"] == "找类似跑鞋，预算 500 元以内"

    asyncio.run(run())


def test_text_recommendation_uses_text_candidate_set():
    async def run():
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(return_value=([_candidate(8)], [{"source": "bm25", "status": "ok"}]))
        ranker = MagicMock()
        ranker.rank.return_value = [
            RankedProduct(product_id=8, title="通勤耳机", price=299, base_price=299, score=0.9),
        ]
        cap = RecommendCapability(retriever=retriever, ranker=ranker)
        dependencies = _patch_turn_dependencies()
        with dependencies[0], dependencies[1], dependencies[2], patch(
            "app.domain.shopping.capabilities.recommend._parse_need_llm",
            new=AsyncMock(return_value=ShoppingNeed(category="耳机")),
        ):
            result = await cap.run("推荐通勤耳机", ShoppingContext(input_mode="text"))

        assert result.action == "recommend"
        assert result.candidate_set is not None
        assert result.candidate_set.input_mode == "text"
        assert result.candidate_set.candidates[0]["product_id"] == 8

    asyncio.run(run())
