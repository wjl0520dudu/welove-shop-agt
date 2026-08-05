"""Focused contracts for the ShoppingAgent multimodal consistency Skill."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent, _deep_agent_tools
from app.application.assistant.nodes import make_nodes
from app.domain.shopping.high_level_tools import (
    _apply_multimodal_consistency_strategy,
    check_multimodal_consistency,
    shopping_candidate_session,
)
from app.domain.shopping.multimodal_consistency import (
    MultimodalConsistencyResult,
    _call_dashscope_multimodal,
    assess_multimodal_consistency,
)
from app.domain.shopping.schemas import ShoppingContext
from app.domain.shopping.tool_guard import RequireMultimodalConsistencyMiddleware
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


@tool("check_multimodal_consistency", description="Return one visual consistency decision.")
async def _check_multimodal_consistency(query: str) -> dict:
    return {
        "action": "consistency",
        "decision": "consistent",
        "image_subject": "跑鞋",
        "text_target": "跑鞋",
    }


@tool("search_product_candidates", description="Return a request-local candidate set.")
async def _search_product_candidates(query: str, limit: int = 3) -> dict:
    return {
        "action": "candidates",
        "candidate_set_id": "running-shoes",
        "candidate_count": 1,
        "requested_limit": limit,
    }


@tool("finalize_product_recommendation", description="Finalize the request-local candidate set.")
async def _finalize_product_recommendation(candidate_set_id: str) -> dict:
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 7, "title": "轻盈跑鞋", "price": 399}],
        "ranked_products": [{"product_id": 7, "title": "轻盈跑鞋", "price": 399}],
    }


def _request(name: str, *, input_mode: str = "multimodal", call_id: str = "tool-1"):
    return SimpleNamespace(
        tool_call={"name": name, "args": {"query": "推荐降噪耳机"}, "id": call_id},
        tool=SimpleNamespace(name=name),
        state={
            "input_mode": input_mode,
            "image_url": "https://img.example.test/running-shoes.jpg" if input_mode == "multimodal" else "",
        },
    )


def _tool_message(request, payload: dict, *, status: str = "success") -> ToolMessage:
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=request.tool_call["id"],
        name=request.tool_call["name"],
        status=status,
    )


def test_visual_conflict_without_both_labels_downgrades_to_uncertain(monkeypatch):
    def caller(**_kwargs):
        return SimpleNamespace(
            status_code=200,
            output=SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=[{
                    "text": '{"decision":"conflict","image_subject":"跑鞋","text_target":"","reason":"缺少文字目标"}'
                }])
            )]),
        )

    monkeypatch.setattr(config, "SHOPPING_MULTIMODAL_CONSISTENCY_ENABLED", True)
    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "test-key")
    result = asyncio.run(assess_multimodal_consistency(
        query="推荐耳机",
        image_url="https://img.example.test/shoe.jpg",
        caller=caller,
    ))

    assert result.decision == "uncertain"
    assert result.fallback_used is False


def test_non_multimodal_turn_hides_consistency_tool_from_deep_agent(monkeypatch):
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    names = [
        tool.name
        for tool in _deep_agent_tools(include_multimodal_consistency=False)
    ]
    assert "check_multimodal_consistency" not in names


def test_visual_preflight_uses_native_dashscope_multimodal_conversation(monkeypatch):
    import dashscope

    captured: dict[str, Any] = {}

    def call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(config, "DASHSCOPE_API_KEY", "dashscope-test-key")
    monkeypatch.setattr(config, "DASHSCOPE_MAAS_BASE_URL", "https://example.test/api/v1")
    monkeypatch.setattr(config, "SHOPPING_MULTIMODAL_CONSISTENCY_MODEL", "qwen3.5-flash")
    monkeypatch.setattr(dashscope.MultiModalConversation, "call", call)

    _call_dashscope_multimodal(
        query="找和图中类似的跑鞋，预算 500 元以内",
        image_url="https://img.example.test/shoe.jpg",
    )

    assert dashscope.base_http_api_url == "https://example.test/api/v1"
    assert captured["api_key"] == "dashscope-test-key"
    assert captured["model"] == "qwen3.5-flash"
    content = captured["messages"][0]["content"]
    assert content[0] == {"image": "https://img.example.test/shoe.jpg"}
    assert "用户文字：找和图中类似的跑鞋" in content[1]["text"]


def test_consistency_tool_returns_direct_clarification_for_verified_conflict():
    assessment = MultimodalConsistencyResult(
        decision="conflict",
        image_subject="跑鞋",
        text_target="降噪耳机",
        reason="商品目标不同",
        model="qwen3.5-flash",
        duration_ms=12,
    )

    async def run():
        with patch(
            "app.domain.shopping.high_level_tools.build_shopping_context_from_runtime",
            new=AsyncMock(return_value=ShoppingContext(
                image_url="https://img.example.test/shoe.jpg",
                input_mode="multimodal",
            )),
        ), patch(
            "app.domain.shopping.high_level_tools.assess_multimodal_consistency",
            new=AsyncMock(return_value=assessment),
        ):
            return await check_multimodal_consistency.coroutine(
                runtime=MagicMock(), query="推荐降噪耳机"
            )

    payload = asyncio.run(run())
    assert payload["action"] == "clarify"
    assert payload["decision"] == "conflict"
    assert payload["product_cards"] == []
    assert "按图片" in payload["clarify_question"]
    assert "按文字" in payload["clarify_question"]


def test_consistency_tool_keeps_uncertain_non_terminal():
    assessment = MultimodalConsistencyResult(
        decision="uncertain",
        reason="图片存在多个商品主体",
        model="qwen3.5-flash",
        fallback_used=False,
        duration_ms=8,
    )

    async def run():
        with patch(
            "app.domain.shopping.high_level_tools.build_shopping_context_from_runtime",
            new=AsyncMock(return_value=ShoppingContext(
                image_url="https://img.example.test/shoe.jpg",
                input_mode="multimodal",
            )),
        ), patch(
            "app.domain.shopping.high_level_tools.assess_multimodal_consistency",
            new=AsyncMock(return_value=assessment),
        ):
            return await check_multimodal_consistency.coroutine(
                runtime=MagicMock(), query="推荐通勤耳机"
            )

    payload = asyncio.run(run())
    assert payload["action"] == "consistency"
    assert payload["decision"] == "uncertain"
    assert "clarify_question" not in payload


def test_multimodal_guard_automatically_preflights_then_allows_uncertain_discovery(monkeypatch):
    async def run():
        middleware = RequireMultimodalConsistencyMiddleware()
        search_handler = AsyncMock(side_effect=lambda request: _tool_message(
            request, {"action": "candidates", "candidate_set_id": "set-1"}
        ))
        discovered = await middleware.awrap_tool_call(
            _request("search_product_candidates", call_id="before-check"), search_handler
        )
        checked = await middleware.awrap_tool_call(
            _request("check_multimodal_consistency", call_id="check"),
            AsyncMock(side_effect=lambda request: _tool_message(
                request, {"action": "consistency", "decision": "uncertain"}
            )),
        )
        allowed = await middleware.awrap_tool_call(
            _request("search_product_candidates", call_id="after-check"), search_handler
        )
        return discovered, checked, allowed, search_handler, middleware

    monkeypatch.setattr(
        "app.domain.shopping.tool_guard.assess_multimodal_consistency",
        AsyncMock(return_value=MultimodalConsistencyResult(
            decision="uncertain",
            text_target="降噪耳机",
            model="qwen3.5-flash",
        )),
    )
    discovered, checked, allowed, search_handler, middleware = asyncio.run(run())
    assert json.loads(discovered.content)["action"] == "candidates"
    assert json.loads(checked.content)["decision"] == "uncertain"
    assert json.loads(allowed.content)["action"] == "candidates"
    assert search_handler.await_count == 2
    assert middleware.records[0]["tool_name"] == "check_multimodal_consistency"
    assert middleware.records[0]["decision"] == "uncertain"


def test_multimodal_guard_blocks_retrieval_after_conflict_and_text_mode_bypasses_it():
    async def run():
        middleware = RequireMultimodalConsistencyMiddleware()
        await middleware.awrap_tool_call(
            _request("check_multimodal_consistency", call_id="check"),
            AsyncMock(side_effect=lambda request: _tool_message(request, {
                "action": "clarify",
                "decision": "conflict",
                "clarify_question": "请确认按图片找跑鞋，还是按文字找耳机？",
            })),
        )
        search_handler = AsyncMock(side_effect=lambda request: _tool_message(
            request, {"action": "candidates"}
        ))
        conflict = await middleware.awrap_tool_call(
            _request("search_product_candidates", call_id="blocked-search"), search_handler
        )
        text = await RequireMultimodalConsistencyMiddleware().awrap_tool_call(
            _request("search_product_candidates", input_mode="text", call_id="text-search"), search_handler
        )
        return conflict, text, search_handler

    conflict, text, search_handler = asyncio.run(run())
    assert json.loads(conflict.content)["action"] == "clarify"
    assert json.loads(text.content)["action"] == "candidates"
    assert search_handler.await_count == 1


def test_uncertain_visual_result_uses_text_first_only_for_a_concrete_text_target():
    context = ShoppingContext(
        image_url="https://img.example.test/shoe.jpg",
        input_mode="multimodal",
    )
    with shopping_candidate_session():
        # The Tool writes this private request-local record before discovery.
        from app.domain.shopping import high_level_tools
        high_level_tools._candidate_registry()["__multimodal_consistency__"] = {
            "decision": "uncertain",
            "text_target": "降噪耳机",
        }
        text_context, text_strategy = _apply_multimodal_consistency_strategy(context)
        high_level_tools._candidate_registry()["__multimodal_consistency__"] = {
            "decision": "uncertain",
            "text_target": "",
        }
        image_context, image_strategy = _apply_multimodal_consistency_strategy(context)

    assert text_strategy == "text_first"
    assert text_context.input_mode == "text"
    assert text_context.image_url is None
    assert image_strategy == "multimodal"
    assert image_context.input_mode == "multimodal"
    assert image_context.image_url


def test_deep_agent_reads_consistency_skill_before_multimodal_discovery(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call("read_file", "discover-skill", {
                "file_path": "/skills/shopping-agent/discover-products/SKILL.md",
            }),
            _call("read_file", "consistency-skill", {
                "file_path": "/skills/shopping-agent/multimodal-consistency/SKILL.md",
            }),
            _call("check_multimodal_consistency", "check", {
                "query": "找和图中类似的跑鞋，预算 500 元以内",
            }),
            _call("search_product_candidates", "search", {
                "query": "找和图中类似的跑鞋，预算 500 元以内", "limit": 3,
            }),
            _call("finalize_product_recommendation", "finalize", {
                "candidate_set_id": "running-shoes",
            }),
            AIMessage(content="这款轻盈跑鞋适合日常跑步，价格也在你的预算内。"),
        ])
        result = await ShoppingAgent(model).run(
            question="找和图中类似的跑鞋，预算 500 元以内",
            messages=[],
            business_memory={},
            conversation_id="multimodal-skill",
            image_url="https://img.example.test/shoe.jpg",
            input_mode="multimodal",
        )
        return result

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    monkeypatch.setattr(
        shopping_agent_module,
        "_DEEP_AGENT_BUSINESS_TOOLS",
        [_check_multimodal_consistency, _search_product_candidates, _finalize_product_recommendation],
    )

    result = asyncio.run(run())
    assert result["answer"].startswith("这款轻盈跑鞋")
    assert result["product_cards"][0]["product_id"] == 7
    assert result["skill_reads"] == ["discover-products", "multimodal-consistency"]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "check_multimodal_consistency",
        "search_product_candidates",
        "finalize_product_recommendation",
    ]


def test_shopping_node_does_not_forward_router_unused_image_to_shopping_agent():
    class _Shopping:
        received: dict[str, Any] = {}

        async def run(self, **kwargs):
            self.received = kwargs
            return {
                "answer": "已按文字查询。",
                "product_cards": [],
                "tool_calls": [],
                "error": False,
            }

    async def run():
        shopping = _Shopping()
        nodes = make_nodes(MagicMock(), shopping_agent=shopping)
        await nodes["shopping_node"]({
            "question": "推荐通勤耳机",
            "image_url": "https://img.example.test/unrelated-shoe.jpg",
            "input_mode": "text",
            "business_memory": {},
        })
        return shopping.received

    received = asyncio.run(run())
    assert received["image_url"] is None
    assert received["input_mode"] == "text"
