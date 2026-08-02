"""Phase S5 tests for Skill-driven compare/detail fact loading."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent
from app.domain.shopping.capabilities.facts import BoundProductFactsCapability
from app.domain.shopping.high_level_tools import load_bound_product_facts
from app.domain.shopping.schemas import BoundProductFactsToolResult, ShoppingContext
from app.domain.shopping.tool_guard import (
    RequireMatchingShoppingSkillMiddleware,
    ShoppingToolGuardMiddleware,
)
from app.infrastructure.config import config


AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]


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


def _request(
    name: str,
    args: dict[str, Any],
    *,
    selected_product_ids: list[int],
    call_id: str = "phase-s5",
) -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": name, "args": args, "id": call_id},
        tool=SimpleNamespace(name=name),
        state={"selected_product_ids": selected_product_ids, "input_mode": "text"},
    )


def _tool_success(request: SimpleNamespace) -> ToolMessage:
    purpose = request.tool_call["args"]["purpose"]
    return ToolMessage(
        content=json.dumps({"action": f"{purpose}_facts", "products": []}),
        tool_call_id=request.tool_call["id"],
        name=request.tool_call["name"],
        status="success",
    )


def test_bound_facts_capability_loads_only_router_bound_products_without_semantic_focus():
    async def run():
        context = ShoppingContext(selected_product_ids=[7, 9])
        products = {
            7: {"product_id": 7, "title": "A", "price": 199, "status": 1, "skus": []},
            9: {"product_id": 9, "title": "B", "price": 299, "status": 1, "skus": []},
        }
        with patch(
            "app.domain.shopping.capabilities.facts._load_bound_product_details",
            new=AsyncMock(return_value=[products[7], products[9]]),
        ) as loader:
            result = await BoundProductFactsCapability().run(
                purpose="compare",
                context=context,
            )
        return result, loader

    result, loader = asyncio.run(run())
    assert result.action == "compare_facts"
    assert [item["product_id"] for item in result.products] == [7, 9]
    loader.assert_awaited_once_with([7, 9])
    assert "focus" not in result.model_dump()


def test_bound_facts_capability_rejects_unbound_or_ambiguous_targets():
    capability = BoundProductFactsCapability()
    compare = asyncio.run(capability.run(
        purpose="compare",
        context=ShoppingContext(selected_product_ids=[7]),
    ))
    detail = asyncio.run(capability.run(
        purpose="detail",
        context=ShoppingContext(selected_product_ids=[7, 9]),
    ))
    unbound = asyncio.run(capability.run(
        purpose="detail",
        context=ShoppingContext(selected_product_ids=[7]),
        product_ids=[99],
    ))
    assert compare.action == "clarify"
    assert detail.action == "clarify"
    assert unbound.action == "clarify"


def test_load_bound_product_facts_tool_delegates_without_query_or_focus():
    result = BoundProductFactsToolResult(
        action="detail_facts",
        purpose="detail",
        products=[{"product_id": 7, "title": "A", "status": 1}],
        product_cards=[{"product_id": 7, "title": "A"}],
    )

    async def run():
        with patch(
            "app.domain.shopping.high_level_tools.build_shopping_context_from_runtime",
            new=AsyncMock(return_value=ShoppingContext(selected_product_ids=[7])),
        ), patch(
            "app.domain.shopping.high_level_tools.BoundProductFactsCapability.run",
            new=AsyncMock(return_value=result),
        ) as capability:
            payload = await load_bound_product_facts.coroutine(
                runtime=MagicMock(),
                purpose="detail",
                product_ids=[7],
            )
        return payload, capability

    payload, capability = asyncio.run(run())
    assert payload["action"] == "detail_facts"
    assert set(load_bound_product_facts.args) == {"purpose", "product_ids"}
    assert "query" not in load_bound_product_facts.args
    assert "focus" not in load_bound_product_facts.args
    assert capability.await_args.kwargs["purpose"] == "detail"


def test_skill_contract_for_unified_fact_tool_depends_on_agent_selected_purpose():
    async def run():
        middleware = RequireMatchingShoppingSkillMiddleware()
        read_handler = AsyncMock(side_effect=lambda request: ToolMessage(
            content="skill",
            tool_call_id=request.tool_call["id"],
            name="read_file",
            status="success",
        ))
        await middleware.awrap_tool_call(
            _request(
                "read_file",
                {"file_path": "/skills/shopping-agent/compare-products/SKILL.md"},
                selected_product_ids=[7, 9],
                call_id="read",
            ),
            read_handler,
        )
        handler = AsyncMock(side_effect=_tool_success)
        allowed = await middleware.awrap_tool_call(
            _request(
                "load_bound_product_facts",
                {"purpose": "compare", "product_ids": [7, 9]},
                selected_product_ids=[7, 9],
            ),
            handler,
        )
        blocked = await middleware.awrap_tool_call(
            _request(
                "load_bound_product_facts",
                {"purpose": "detail", "product_ids": [7]},
                selected_product_ids=[7],
                call_id="wrong-skill",
            ),
            handler,
        )
        return allowed, blocked, handler

    allowed, blocked, handler = asyncio.run(run())
    assert allowed.status == "success"
    assert handler.await_count == 1
    assert blocked.status == "error"
    assert json.loads(blocked.content)["required_skill"] == "inspect-product"


def test_tool_guard_enforces_bound_ids_and_purpose_for_unified_fact_tool():
    async def run():
        guard = ShoppingToolGuardMiddleware()
        handler = AsyncMock(side_effect=_tool_success)
        valid = await guard.awrap_tool_call(
            _request(
                "load_bound_product_facts",
                {"purpose": "compare", "product_ids": [7, 9]},
                selected_product_ids=[7, 9],
                call_id="valid",
            ),
            handler,
        )
        invalid = await guard.awrap_tool_call(
            _request(
                "load_bound_product_facts",
                {"purpose": "detail", "product_ids": [99]},
                selected_product_ids=[7],
                call_id="invalid",
            ),
            handler,
        )
        return valid, invalid, guard, handler

    valid, invalid, guard, handler = asyncio.run(run())
    assert valid.status == "success"
    assert json.loads(invalid.content)["action"] == "clarify"
    assert handler.await_count == 1
    assert guard.records[0]["capability"] == "compare"
    assert guard.records[1]["status"] == "blocked"


@tool("load_bound_product_facts", description="Load Router-bound product facts.")
async def _load_bound_product_facts(purpose: str, product_ids: list[int]) -> dict:
    return {
        "action": f"{purpose}_facts",
        "purpose": purpose,
        "products": [
            {"product_id": product_id, "title": f"商品 {product_id}", "price": 100 + product_id}
            for product_id in product_ids
        ],
        "product_cards": [
            {"product_id": product_id, "title": f"商品 {product_id}"}
            for product_id in product_ids
        ],
    }


def test_deep_agent_compare_reads_skill_then_uses_unified_facts_tool(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "skill",
                {"file_path": "/skills/shopping-agent/compare-products/SKILL.md"},
            ),
            _call(
                "load_bound_product_facts",
                "facts",
                {"purpose": "compare", "product_ids": [7, 9]},
            ),
            AIMessage(content="两款相比，商品 7 更便宜，商品 9 价格更高。"),
        ])
        return await ShoppingAgent(model).run(
            question="比较第一款和第三款的价格",
            messages=[],
            business_memory={"selected_product_ids": [7, 9]},
            selected_product_ids=[7, 9],
            conversation_id="phase-s5-compare",
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    monkeypatch.setattr(
        shopping_agent_module,
        "_DEEP_AGENT_BUSINESS_TOOLS",
        [_load_bound_product_facts],
    )

    result = asyncio.run(run())
    assert result["capability"] == "compare"
    assert result["skill_reads"] == ["compare-products"]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "load_bound_product_facts",
    ]
    assert [item["product_id"] for item in result["product_cards"]] == [7, 9]


def test_deep_agent_detail_reads_skill_then_uses_same_facts_tool(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "skill",
                {"file_path": "/skills/shopping-agent/inspect-product/SKILL.md"},
            ),
            _call(
                "load_bound_product_facts",
                "facts",
                {"purpose": "detail", "product_ids": [7]},
            ),
            AIMessage(content="这款商品当前价格是 107 元。"),
        ])
        return await ShoppingAgent(model).run(
            question="第一款现在多少钱",
            messages=[],
            business_memory={"selected_product_ids": [7]},
            selected_product_ids=[7],
            conversation_id="phase-s5-detail",
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    monkeypatch.setattr(
        shopping_agent_module,
        "_DEEP_AGENT_BUSINESS_TOOLS",
        [_load_bound_product_facts],
    )

    result = asyncio.run(run())
    assert result["capability"] == "detail"
    assert result["skill_reads"] == ["inspect-product"]
    assert result["tool_calls"][0]["input_params"]["purpose"] == "detail"
    assert result["product_cards"][0]["product_id"] == 7


def test_compare_and_detail_skills_no_longer_name_legacy_monolithic_tools():
    compare_text = (
        AI_SERVICE_ROOT / "skills" / "shopping-agent" / "compare-products" / "SKILL.md"
    ).read_text(encoding="utf-8")
    detail_text = (
        AI_SERVICE_ROOT / "skills" / "shopping-agent" / "inspect-product" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "compare_products" not in compare_text
    assert "answer_product_detail" not in detail_text
    assert "load_bound_product_facts" in compare_text
    assert "load_bound_product_facts" in detail_text
