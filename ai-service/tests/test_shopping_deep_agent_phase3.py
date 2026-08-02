"""Phase S3 DeepAgent integration tests for controlled Skill scripts."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.api.response_adapter import normalize_ai_response
from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent, _deep_agent_tools
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
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


@tool("recommend_products", description="Return deterministic S3 candidates.")
async def _recommend_products(query: str) -> dict:
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 1, "title": "S3 商品"}],
        "ranked_products": [{"product_id": 1, "title": "S3 商品"}],
        "returned_count": 1,
        "query": query,
    }


def test_controlled_mode_adds_only_the_narrow_script_tool(monkeypatch):
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "controlled")
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", [_recommend_products]
    )
    assert [tool.name for tool in _deep_agent_tools()] == [
        "recommend_products",
        "run_shopping_skill_script",
    ]

    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    assert [tool.name for tool in _deep_agent_tools()] == ["recommend_products"]


def test_deep_agent_runs_reviewed_script_after_reading_the_matching_skill(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "read-skill",
                {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
            ),
            _call(
                "recommend_products",
                "business",
                {"query": "推荐商品"},
            ),
            _call(
                "run_shopping_skill_script",
                "script",
                {
                    "skill_name": "discover-products",
                    "script_name": "validate-selection",
                    "payload": {
                        "candidates": [{"product_id": 1, "match_status": "exact"}],
                        "selected_indices": [1],
                    },
                },
            ),
            AIMessage(content="已根据真实商品结果完成。"),
        ])
        return await ShoppingAgent(model).run(
            question="推荐商品",
            messages=[],
            business_memory={},
            conversation_id="phase-s3-script",
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "controlled")
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", [_recommend_products]
    )

    result = asyncio.run(run())

    assert result["answer"] == "已根据真实商品结果完成。"
    assert result["skill_reads"] == ["discover-products"]
    assert result["script_calls"] == [{
        "tool_call_id": "script",
        "skill_name": "discover-products",
        "script_name": "validate-selection",
        "status": "success",
        "duration_ms": result["script_calls"][0]["duration_ms"],
        "error_code": None,
    }]
    assert [item["tool_name"] for item in result["tool_calls"]] == ["recommend_products"]
    assert result["product_cards"][0]["product_id"] == 1

    response = normalize_ai_response(result)
    assert response.script_calls[0]["script_name"] == "validate-selection"
