"""Request-local invariants for the LLM-driven ShoppingAgent tool loop."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.domain.shopping.tool_guard import (
    RequireInitialShoppingToolMiddleware,
    ShoppingToolGuardMiddleware,
)


def _request(
    name: str,
    args: dict,
    *,
    call_id: str = "tc-1",
    selected_product_ids: list[int] | None = None,
    input_mode: str = "text",
):
    return SimpleNamespace(
        tool_call={"id": call_id, "name": name, "args": args},
        tool=SimpleNamespace(name=name),
        state={
            "selected_product_ids": selected_product_ids or [],
            "input_mode": input_mode,
            "image_url": "https://img.example.test/a.png" if input_mode != "text" else "",
        },
    )


def _success(*, call_id: str, action: str = "recommend") -> ToolMessage:
    return ToolMessage(
        content=json.dumps({"action": action, "product_cards": [{"product_id": 1}]}),
        tool_call_id=call_id,
        name="recommend_products",
    )


def test_identical_successful_recommendation_is_reused_within_one_run():
    async def run():
        guard = ShoppingToolGuardMiddleware()
        handler = AsyncMock(side_effect=lambda request: _success(call_id=request.tool_call["id"]))

        first = await guard.awrap_tool_call(
            _request("recommend_products", {"query": "通勤耳机", "limit": 3}, call_id="a"),
            handler,
        )
        second = await guard.awrap_tool_call(
            _request("recommend_products", {"limit": 3, "query": "通勤耳机"}, call_id="b"),
            handler,
        )

        assert handler.await_count == 1
        assert first.content == second.content
        assert second.tool_call_id == "b"
        assert guard.records[-1]["status"] == "deduplicated"
        assert guard.records[-1]["deduplicated"] is True

    asyncio.run(run())


def test_first_model_turn_requires_a_high_level_tool_but_final_answer_does_not():
    async def run():
        middleware = RequireInitialShoppingToolMiddleware()
        observed: list[object] = []

        async def handler(request):
            observed.append(request.tool_choice)
            return ModelResponse(result=[AIMessage(content="ok")])

        initial = ModelRequest(
            model=AsyncMock(),
            messages=[HumanMessage(content="推荐耳机")],
        )
        after_tool = ModelRequest(
            model=AsyncMock(),
            messages=[
                HumanMessage(content="推荐耳机"),
                ToolMessage(content='{"action":"recommend"}', tool_call_id="tc", name="recommend_products"),
            ],
        )
        await middleware.awrap_model_call(initial, handler)
        await middleware.awrap_model_call(after_tool, handler)

        assert observed == ["required", None]

    asyncio.run(run())


def test_main_capability_cannot_switch_after_successful_tool_result():
    async def run():
        guard = ShoppingToolGuardMiddleware()
        handler = AsyncMock(side_effect=lambda request: _success(call_id=request.tool_call["id"]))
        await guard.awrap_tool_call(
            _request("recommend_products", {"query": "通勤耳机"}, call_id="recommend"),
            handler,
        )
        blocked = await guard.awrap_tool_call(
            _request("compare_products", {"query": "对比", "product_ids": [1, 2]}, call_id="compare", selected_product_ids=[1, 2]),
            handler,
        )

        assert handler.await_count == 1
        assert json.loads(blocked.content)["action"] == "clarify"
        assert guard.records[-1]["status"] == "limited"
        assert guard.records[-1]["error_code"] == "SHOPPING_TOOL_GUARD_BLOCKED"

    asyncio.run(run())


def test_compare_and_detail_can_only_consume_router_bound_ids():
    async def run():
        guard = ShoppingToolGuardMiddleware()
        handler = AsyncMock()

        compare = await guard.awrap_tool_call(
            _request("compare_products", {"query": "对比", "product_ids": [7, 99]}, selected_product_ids=[7, 9]),
            handler,
        )
        detail = await guard.awrap_tool_call(
            _request("answer_product_detail", {"query": "多少钱", "product_id": 99}, selected_product_ids=[7]),
            handler,
        )

        assert handler.await_count == 0
        assert json.loads(compare.content)["action"] == "clarify"
        assert json.loads(detail.content)["action"] == "clarify"
        assert [record["status"] for record in guard.records] == ["blocked", "blocked"]

    asyncio.run(run())


def test_empty_tool_result_is_observable_and_still_ends_main_capability():
    async def run():
        guard = ShoppingToolGuardMiddleware()
        handler = AsyncMock(side_effect=lambda request: _success(call_id=request.tool_call["id"], action="empty"))
        await guard.awrap_tool_call(
            _request("recommend_products", {"query": "不存在的商品"}),
            handler,
        )
        blocked = await guard.awrap_tool_call(
            _request("answer_product_detail", {"query": "详情", "product_id": 1}, selected_product_ids=[1]),
            handler,
        )

        assert guard.records[0]["status"] == "empty"
        assert handler.await_count == 1
        assert guard.records[1]["status"] == "limited"
        assert json.loads(blocked.content)["action"] == "clarify"

    asyncio.run(run())
