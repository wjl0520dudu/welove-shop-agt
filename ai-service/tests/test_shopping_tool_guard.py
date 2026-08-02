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
    RequireMatchingShoppingSkillMiddleware,
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
        after_skill_contract_error = ModelRequest(
            model=AsyncMock(),
            messages=[
                HumanMessage(content="推荐耳机"),
                ToolMessage(
                    content='{"error":true,"error_code":"SHOPPING_SKILL_REQUIRED"}',
                    tool_call_id="blocked",
                    name="recommend_products",
                    status="error",
                ),
            ],
        )
        await middleware.awrap_model_call(initial, handler)
        await middleware.awrap_model_call(after_skill_contract_error, handler)
        await middleware.awrap_model_call(after_tool, handler)

        assert observed == ["required", "required", None]

    asyncio.run(run())


def test_matching_skill_is_required_before_a_business_tool_executes():
    async def run():
        middleware = RequireMatchingShoppingSkillMiddleware()
        business_handler = AsyncMock(side_effect=lambda request: _success(
            call_id=request.tool_call["id"],
        ))

        blocked = await middleware.awrap_tool_call(
            _request("recommend_products", {"query": "通勤耳机"}, call_id="blocked"),
            business_handler,
        )
        assert business_handler.await_count == 0
        assert blocked.status == "error"
        assert json.loads(blocked.content)["required_skill"] == "discover-products"

        async def read_handler(request):
            return ToolMessage(
                content="# discover-products",
                tool_call_id=request.tool_call["id"],
                name="read_file",
            )

        await middleware.awrap_tool_call(
            _request(
                "read_file",
                {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
                call_id="read",
            ),
            read_handler,
        )
        executed = await middleware.awrap_tool_call(
            _request("recommend_products", {"query": "通勤耳机"}, call_id="executed"),
            business_handler,
        )

        assert executed.status != "error"
        assert business_handler.await_count == 1
        assert middleware.read_skills == ["discover-products"]
        assert middleware.records[0]["error_code"] == "SHOPPING_SKILL_REQUIRED"

    asyncio.run(run())


def test_reading_an_unrelated_skill_does_not_authorize_the_selected_tool():
    async def run():
        middleware = RequireMatchingShoppingSkillMiddleware()

        async def read_handler(request):
            return ToolMessage(
                content="# compare-products",
                tool_call_id=request.tool_call["id"],
                name="read_file",
            )

        await middleware.awrap_tool_call(
            _request(
                "read_file",
                {"file_path": "/skills/shopping-agent/compare-products/SKILL.md"},
                call_id="read-wrong",
            ),
            read_handler,
        )
        business_handler = AsyncMock()
        blocked = await middleware.awrap_tool_call(
            _request("recommend_products", {"query": "推荐耳机"}, call_id="wrong"),
            business_handler,
        )

        assert middleware.read_skills == ["compare-products"]
        assert business_handler.await_count == 0
        assert blocked.status == "error"
        assert json.loads(blocked.content)["required_skill"] == "discover-products"

    asyncio.run(run())


def test_script_runner_requires_the_skill_declared_in_its_arguments():
    async def run():
        middleware = RequireMatchingShoppingSkillMiddleware()

        async def read_handler(request):
            return ToolMessage(
                content="# compare-products",
                tool_call_id=request.tool_call["id"],
                name="read_file",
            )

        await middleware.awrap_tool_call(
            _request(
                "read_file",
                {"file_path": "/skills/shopping-agent/compare-products/SKILL.md"},
                call_id="read-compare",
            ),
            read_handler,
        )
        handler = AsyncMock()
        blocked = await middleware.awrap_tool_call(
            _request(
                "run_shopping_skill_script",
                {
                    "skill_name": "discover-products",
                    "script_name": "validate-selection",
                    "payload": {},
                },
                call_id="script-wrong-skill",
            ),
            handler,
        )

        assert handler.await_count == 0
        assert blocked.status == "error"
        assert json.loads(blocked.content)["required_skill"] == "discover-products"

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
