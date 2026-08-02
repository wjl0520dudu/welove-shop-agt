"""Phase S4 tests for Skill-orchestrated narrow recommendation tools."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent
from app.domain.shopping.capabilities.recommend import RecommendCapability
from app.domain.shopping.high_level_tools import (
    finalize_product_recommendation,
    search_product_candidates,
    shopping_candidate_session,
)
from app.domain.shopping.schemas import (
    CandidateSearchToolResult,
    CandidateSet,
    RankedProduct,
    RecommendToolResult,
    ShoppingContext,
)
from app.infrastructure.config import config


class _RecordingToolModel(FakeMessagesListChatModel):
    _tool_bindings: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self._tool_bindings.append({
            "names": tuple(str(getattr(value, "name", "") or "") for value in tools),
            "tool_choice": kwargs.get("tool_choice"),
        })
        return self


def _call(name: str, call_id: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "id": call_id,
        "name": name,
        "args": args,
    }])


class _Retriever:
    async def retrieve(self, _plan, _need):
        return ([{
            "product_id": 43,
            "title": "通勤降噪耳机",
            "brand": "Test",
            "price": 699,
            "category": "数码",
            "sub_category": "耳机",
            "score": 0.9,
        }], {"mode": "fake"})


def test_recommend_capability_search_and_finalize_are_separate_steps():
    async def run():
        capability = RecommendCapability(retriever=_Retriever())
        context = ShoppingContext(conversation_id="s4", user_id=1)
        with patch(
            "app.domain.shopping.capabilities.recommend._judge_ranked_candidates",
            new=AsyncMock(return_value=[RankedProduct(
                product_id=43,
                title="通勤降噪耳机",
                brand="Test",
                price=699,
                category="数码",
                sub_category="耳机",
                match_status="exact",
            )]),
        ) as judge, patch(
            "app.domain.shopping.capabilities.recommend.remember_product_cards",
            new=AsyncMock(),
        ):
            search = await capability.search_candidates(
                query="推荐通勤耳机",
                context=context,
                limit=3,
            )
            assert search.action == "candidates"
            assert len(search.candidate_set.candidates) == 1
            judge.assert_not_awaited()

            final = await capability.finalize_candidates(
                query="推荐通勤耳机",
                context=context,
                candidate_set=search.candidate_set,
                limit=3,
                need=search.need,
                trace=search.trace,
            )
            judge.assert_awaited_once()
            assert final.action == "recommend"
            assert final.product_cards[0]["product_id"] == 43

    asyncio.run(run())


def test_finalize_uses_server_owned_candidate_set_instead_of_model_payload():
    async def run():
        search_result = CandidateSearchToolResult(
            action="candidates",
            candidate_set=CandidateSet(
                input_mode="text",
                query_text="推荐耳机",
                candidates=[RankedProduct(
                    product_id=43,
                    title="真实耳机",
                    price=699,
                ).model_dump()],
            ),
        )
        final_result = RecommendToolResult(
            action="recommend",
            ranked_products=[RankedProduct(
                product_id=43,
                title="真实耳机",
                price=699,
                match_status="exact",
            )],
            product_cards=[{"product_id": 43, "title": "真实耳机", "price": 699}],
        )
        with shopping_candidate_session(), patch(
            "app.domain.shopping.high_level_tools.build_shopping_context_from_runtime",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "app.domain.shopping.high_level_tools.RecommendCapability.search_candidates",
            new=AsyncMock(return_value=search_result),
        ), patch(
            "app.domain.shopping.high_level_tools.RecommendCapability.finalize_candidates",
            new=AsyncMock(return_value=final_result),
        ) as finalize:
            search_payload = await asyncio.create_task(
                search_product_candidates.coroutine(
                    runtime=MagicMock(),
                    query="推荐耳机",
                    limit=3,
                )
            )
            # 模型能看到的 JSON 即使被改写，也不会成为终结 Tool 的事实输入。
            search_payload["candidate_set"]["candidates"][0]["price"] = 1
            final_payload = await asyncio.create_task(
                finalize_product_recommendation.coroutine(
                    runtime=MagicMock(),
                    candidate_set_id=search_payload["candidate_set_id"],
                )
            )

        server_candidate_set = finalize.await_args.kwargs["candidate_set"]
        assert server_candidate_set.candidates[0]["price"] == 699
        assert final_payload["product_cards"][0]["price"] == 699

    asyncio.run(run())


def test_finalize_rejects_unknown_candidate_set_id():
    async def run():
        with shopping_candidate_session():
            return await finalize_product_recommendation.coroutine(
                runtime=MagicMock(),
                candidate_set_id="unknown",
            )

    result = asyncio.run(run())
    assert result["action"] == "empty"
    assert result["error_code"] == "SHOPPING_CANDIDATE_SET_EXPIRED"


@tool("search_product_candidates", description="Return deterministic candidates.")
async def _search_product_candidates(query: str, limit: int = 3) -> dict:
    return {
        "action": "candidates",
        "candidate_set_id": "candidate-set-1",
        "candidate_count": 1,
        "requested_limit": limit,
        "candidate_set": {
            "input_mode": "text",
            "query_text": query,
            "candidates": [{"candidate_index": 1, "title": "通勤耳机"}],
        },
    }


@tool("finalize_product_recommendation", description="Finalize deterministic candidates.")
async def _finalize_product_recommendation(candidate_set_id: str) -> dict:
    assert candidate_set_id == "candidate-set-1"
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 43, "title": "通勤耳机", "price": 699}],
        "ranked_products": [{
            "product_id": 43,
            "title": "通勤耳机",
            "price": 699,
            "match_status": "exact",
        }],
        "returned_count": 1,
    }


def test_deep_agent_must_search_then_finalize_before_answering(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "skill",
                {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
            ),
            _call(
                "search_product_candidates",
                "search",
                {"query": "推荐通勤耳机", "limit": 3},
            ),
            _call(
                "finalize_product_recommendation",
                "finalize",
                {"candidate_set_id": "candidate-set-1"},
            ),
            AIMessage(content="为你找到一款适合通勤的耳机。"),
        ])
        return model, await ShoppingAgent(model).run(
            question="推荐通勤耳机",
            messages=[],
            business_memory={},
            conversation_id="phase-s4",
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    monkeypatch.setattr(
        shopping_agent_module,
        "_DEEP_AGENT_BUSINESS_TOOLS",
        [_search_product_candidates, _finalize_product_recommendation],
    )

    model, result = asyncio.run(run())

    assert result["answer"] == "为你找到一款适合通勤的耳机。"
    assert result["capability"] == "recommend"
    assert result["product_cards"][0]["product_id"] == 43
    assert result["skill_reads"] == ["discover-products"]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "search_product_candidates",
        "finalize_product_recommendation",
    ]
    assert [item["tool_choice"] for item in model._tool_bindings][:4] == [
        "required",
        "required",
        "required",
        None,
    ]
