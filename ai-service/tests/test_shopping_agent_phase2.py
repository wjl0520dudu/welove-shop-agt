"""Phase 2 tests for the true LLM Tool Agent Shopping main path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.tools import tool

from app.domain.shopping.agent import ShoppingAgent
from app.infrastructure.config import config


@pytest.fixture(autouse=True)
def _use_phase2_legacy_runtime(monkeypatch):
    """Phase 2 tests isolate the explicit manual rollback implementation."""
    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", False)


class _FakeAgent:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[dict, dict]] = []

    async def ainvoke(self, state, config):
        self.calls.append((state, config))
        if self.error:
            raise self.error
        return self.result


class _FakeStreamingAgent(_FakeAgent):
    async def astream(self, state, config, stream_mode):
        self.calls.append((state, config))
        assert stream_mode == ["values", "messages"]
        yield "messages", (AIMessageChunk(content="逐"), {})
        yield "messages", (AIMessageChunk(content="字"), {})
        yield "messages", (AIMessageChunk(content="回答"), {})
        yield "values", self.result


class _ToolBoundFakeModel(FakeMessagesListChatModel):
    """LangChain's fake chat model with the tool-binding hook implemented."""

    def bind_tools(self, tools, **kwargs):
        del tools, kwargs
        return self


_REAL_LOOP_CALLS: list[str] = []


@tool("recommend_products", description="Return a test recommendation result.")
async def _real_loop_recommend(query: str) -> dict:
    _REAL_LOOP_CALLS.append(query)
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 31, "title": "真实循环测试耳机"}],
    }


def _tool_loop_result(*, tool_name: str, action: str, payload: dict | None = None):
    body = {"action": action, **(payload or {})}
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": tool_name, "args": {"query": "完整商品问题"}}],
            ),
            ToolMessage(content=json.dumps(body), tool_call_id="call-1", name=tool_name),
            AIMessage(content="这是基于工具真实结果的自然回答。"),
        ]
    }


def test_normal_turn_uses_create_agent_and_never_pre_dispatches_rules():
    async def run():
        fake_agent = _FakeAgent(_tool_loop_result(
            tool_name="recommend_products",
            action="recommend",
            payload={"product_cards": [{"product_id": 7, "title": "通勤耳机"}]},
        ))
        shopping = ShoppingAgent(llm=MagicMock())

        with patch("app.domain.shopping.agent.create_agent", return_value=fake_agent) as create, patch(
            "app.domain.shopping.agent.dispatch_shopping_capability",
        ) as dispatcher:
            result = await shopping.run(
                question="推荐一款适合通勤的耳机",
                messages=[
                    {"role": "user", "content": "上一轮说的第一款呢"},
                    {"role": "assistant", "content": "旧商品卡"},
                ],
                business_memory={"last_product_cards": [{"product_id": 999}]},
                selected_product_ids=[],
            )

        dispatcher.assert_not_called()
        assert create.call_args.kwargs["tools"]
        assert {tool.name for tool in create.call_args.kwargs["tools"]} == {
            "recommend_products", "compare_products", "answer_product_detail", "get_user_shopping_context",
        }
        state, config = fake_agent.calls[0]
        assert len(state["messages"]) == 1
        assert state["messages"][0].content == "推荐一款适合通勤的耳机"
        assert state["business_memory"] == {"selected_product_ids": [], "user_preferences": {}}
        assert config["recursion_limit"] == 12
        assert result["dispatch_source"] == "agent_tool_loop"
        assert result["capability"] == "recommend"
        assert result["product_cards"] == [{"product_id": 7, "title": "通勤耳机"}]
        assert result["model_call_count"] == 2

    asyncio.run(run())


def test_agent_streams_provider_chunks_when_token_sink_is_supplied():
    async def run():
        fake_agent = _FakeStreamingAgent(_tool_loop_result(
            tool_name="recommend_products",
            action="recommend",
            payload={"product_cards": [{"product_id": 7, "title": "通勤耳机"}]},
        ))
        shopping = ShoppingAgent(llm=MagicMock())
        received: list[str] = []

        with patch("app.domain.shopping.agent.create_agent", return_value=fake_agent):
            result = await shopping.run(
                question="推荐通勤耳机",
                messages=[],
                business_memory={},
                token_sink=received.append,
            )

        assert received == ["逐", "字", "回答"]
        assert result["answer"] == "这是基于工具真实结果的自然回答。"
        assert result["product_cards"] == [{"product_id": 7, "title": "通勤耳机"}]

    asyncio.run(run())


def test_agent_failure_uses_observable_restricted_fallback_only_after_loop_attempt():
    async def run():
        fake_agent = _FakeAgent(error=RuntimeError("provider unavailable"))
        shopping = ShoppingAgent(llm=MagicMock())
        fallback = {
            "answer": "受限降级结果",
            "task_type": "shopping",
            "dispatch_source": "restricted_rule_fallback",
            "tool_calls": [],
            "error": False,
        }
        with patch("app.domain.shopping.agent.create_agent", return_value=fake_agent), patch.object(
            shopping,
            "_run_restricted_fallback",
            new=AsyncMock(return_value=fallback),
        ) as fallback_call:
            result = await shopping.run(
                question="推荐耳机",
                messages=[],
                business_memory={},
            )

        assert fake_agent.calls
        fallback_call.assert_awaited_once()
        assert result["dispatch_source"] == "restricted_rule_fallback"

    asyncio.run(run())


def test_agent_without_a_high_level_tool_never_returns_an_ungrounded_recommendation():
    async def run():
        fake_agent = _FakeAgent({
            "messages": [AIMessage(content="我已经为你挑了三款耳机。")],
        })
        shopping = ShoppingAgent(llm=MagicMock())
        with patch("app.domain.shopping.agent.create_agent", return_value=fake_agent):
            result = await shopping.run(
                question="推荐通勤耳机",
                messages=[],
                business_memory={},
            )

        assert result["error"] is True
        assert result["error_code"] == "AI_SHOPPING_ERROR"
        assert result["product_cards"] == []
        assert result["tool_calls"] == []
        assert "查询商城的实时商品信息" in result["answer"]

    asyncio.run(run())


def test_prompt_is_a_short_role_contract_without_embedded_operation_manuals():
    prompt = ShoppingAgent(MagicMock())._build_system_prompt(
        selected_product_ids=[11, 13],
        image_url="https://cdn.example.test/p.png",
        input_mode="multimodal",
    )

    assert "你的职责" in prompt
    assert "不要再读取或猜测会话历史" in prompt
    assert "11, 13" in prompt
    assert "操作手册 A" not in prompt
    assert "操作手册 B" not in prompt
    assert "操作手册 C" not in prompt
    assert "Plan-and-Execute" not in prompt
    assert "Few-shot" not in prompt


def test_detailed_recommendation_result_rules_live_in_the_discovery_skill():
    prompt = ShoppingAgent(MagicMock())._build_system_prompt(
        selected_product_ids=[],
        image_url=None,
        input_mode="text",
    )

    skill_text = Path(
        "skills/shopping-agent/discover-products/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "returned_count" not in prompt
    assert "returned_count" in skill_text
    assert "product_cards" in skill_text
    assert "不要从历史或常识补齐" in skill_text


def test_real_create_agent_tool_loop_executes_the_high_level_tool_once():
    async def run():
        _REAL_LOOP_CALLS.clear()
        model = _ToolBoundFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "id": "real-call", "name": "recommend_products",
                "args": {"query": "推荐通勤耳机"},
            }]),
            AIMessage(content="这款更适合日常通勤。"),
        ])
        shopping = ShoppingAgent(model)
        with patch("app.domain.shopping.agent._ALL_TOOLS", [_real_loop_recommend]):
            result = await shopping.run(
                question="推荐通勤耳机",
                messages=[],
                business_memory={},
            )

        assert _REAL_LOOP_CALLS == ["推荐通勤耳机"]
        assert result["dispatch_source"] == "agent_tool_loop"
        assert result["capability"] == "recommend"
        assert result["product_cards"] == [{"product_id": 31, "title": "真实循环测试耳机"}]
        assert result["answer"] == "这款更适合日常通勤。"

    asyncio.run(run())
