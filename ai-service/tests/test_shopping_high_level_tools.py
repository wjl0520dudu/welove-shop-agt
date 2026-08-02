"""高层 Tool（recommend/compare/detail/user_context）+ agent 结果抽取的单测。

- 每个 @tool 的 name / description / args_schema 合规
- build_shopping_context_from_runtime 从 runtime.state + Store 读取
- _extract_high_level_tool_result 只挑高层 Tool 返回的 dict
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage

from app.domain.shopping.agent import _extract_high_level_tool_result
from app.domain.shopping.context import build_shopping_context_from_runtime
from app.domain.shopping.high_level_tools import SHOPPING_HIGH_LEVEL_TOOLS
from app.domain.shopping.schemas import RecommendToolResult


class TestToolCatalog:
    def test_only_four_tools(self):
        assert len(SHOPPING_HIGH_LEVEL_TOOLS) == 4

    def test_tool_names(self):
        names = {t.name for t in SHOPPING_HIGH_LEVEL_TOOLS}
        assert names == {
            "recommend_products",
            "compare_products",
            "answer_product_detail",
            "get_user_shopping_context",
        }

    def test_each_has_description(self):
        for t in SHOPPING_HIGH_LEVEL_TOOLS:
            assert t.description
            assert len(t.description) > 30   # 有实质内容，让 LLM 有依据挑

    def test_tools_publish_concise_boundaries_and_delegate_workflows_to_skills(self):
        """Phase S2 后 Tool 只说明接口，固定工作方法由 Skill 按需加载。"""
        for tool in SHOPPING_HIGH_LEVEL_TOOLS:
            assert "固定执行闭环" not in tool.description
            assert "典型示例" not in tool.description
            assert "Skill" in tool.description
            assert len(tool.description) < 220

    def test_recommend_args_schema(self):
        """LLM 应该看到 query / limit，但不该看到 runtime。"""
        tool = next(t for t in SHOPPING_HIGH_LEVEL_TOOLS if t.name == "recommend_products")
        # tool.args 是 LangChain 暴露给 LLM 的参数 map
        args = tool.args
        assert "query" in args
        assert "limit" in args
        # runtime 由 LangGraph 自动注入，不能出现在 LLM 可见 args 里
        assert "runtime" not in args


class TestBuildShoppingContextFromRuntime:
    def test_reads_only_router_injected_memory(self):
        runtime = MagicMock()
        runtime.state = {
            "conversation_id": "c1",
            "user_id": 42,
            "jwt_token": "tk",
            "run_id": "r1",
            "selected_product_ids": [7, "9", "invalid", 7],
            "image_url": "https://cdn.example.test/p.png",
            "input_mode": "multimodal",
            "business_memory": {
                "last_product_cards": [{"product_id": 1}],
                "last_focused_product": {"product_id": 1, "title": "A"},
                "user_preferences": {"skin_type": "油皮"},
            },
        }
        ctx = asyncio.run(build_shopping_context_from_runtime(runtime))
        assert ctx.conversation_id == "c1"
        assert ctx.user_id == 42
        assert ctx.jwt_token == "tk"
        assert ctx.is_logged_in is True
        assert ctx.selected_product_ids == [7, 9]
        assert ctx.last_product_cards == []
        assert ctx.last_focused_product is None
        assert ctx.user_preferences == {"skin_type": "油皮"}
        assert ctx.image_url == "https://cdn.example.test/p.png"
        assert ctx.input_mode == "multimodal"

    def test_no_user_means_not_logged_in(self):
        runtime = MagicMock()
        runtime.state = {"conversation_id": "c1"}
        ctx = asyncio.run(build_shopping_context_from_runtime(runtime))
        assert ctx.is_logged_in is False
        assert ctx.user_id is None

    def test_malformed_injected_memory_falls_back_to_empty(self):
        runtime = MagicMock()
        runtime.state = {"conversation_id": "c1", "user_id": 1, "business_memory": "bad"}
        ctx = asyncio.run(build_shopping_context_from_runtime(runtime))
        assert ctx.business_memory == {}
        assert ctx.last_product_cards == []


class TestExtractHighLevelToolResult:
    def _tm(self, payload):
        return ToolMessage(content=json.dumps(payload), tool_call_id="tc1")

    def test_picks_latest_action_dict(self):
        messages = [
            AIMessage(content="thinking"),
            self._tm({"action": "recommend", "product_cards": [{"id": 1}]}),
            AIMessage(content="answer"),
        ]
        result = _extract_high_level_tool_result(messages)
        assert result["action"] == "recommend"
        assert result["product_cards"] == [{"id": 1}]

    def test_ignores_non_action_dicts(self):
        """非高层 tool 返回（没 action 字段）应该被跳过。"""
        messages = [
            self._tm({"result": "old low-level tool output"}),   # 老工具残留
            self._tm({"action": "detail", "facts": {"price": 100}}),
        ]
        result = _extract_high_level_tool_result(messages)
        assert result["action"] == "detail"

    def test_returns_empty_when_no_tool_message(self):
        messages = [AIMessage(content="just chat")]
        assert _extract_high_level_tool_result(messages) == {}

    def test_ignores_invalid_json(self):
        # 用非法 JSON 内容构造 ToolMessage
        bad = ToolMessage(content="not-json-content", tool_call_id="tc1")
        good = ToolMessage(content=json.dumps({"action": "compare"}), tool_call_id="tc2")
        result = _extract_high_level_tool_result([bad, good])
        assert result.get("action") == "compare"

    def test_takes_last_high_level_result(self):
        """多个高层 Tool 返回时取最近一个（倒序找）。"""
        m1 = self._tm({"action": "recommend", "product_cards": [{"id": 1}]})
        m2 = self._tm({"action": "compare", "product_cards": [{"id": 2}]})
        result = _extract_high_level_tool_result([m1, m2])
        assert result["action"] == "compare"


def test_recommend_tool_hides_internal_and_rejected_candidates_from_agent():
    async def run():
        tool = next(
            item for item in SHOPPING_HIGH_LEVEL_TOOLS
            if item.name == "recommend_products"
        )
        capability_result = RecommendToolResult(
            action="recommend",
            candidate_set={
                "input_mode": "text",
                "candidates": [
                    {"product_id": 11, "title": "visible headphones"},
                    {"product_id": 99, "title": "rejected tablet"},
                ],
            },
            ranked_products=[{
                "product_id": 11,
                "title": "visible headphones",
                "score": 0.9,
            }],
            product_cards=[{"product_id": 11, "title": "visible headphones"}],
            trace=[{"stage": "judge", "rejected_product_ids": [99]}],
        )
        with patch(
            "app.domain.shopping.high_level_tools.build_shopping_context_from_runtime",
            new=AsyncMock(return_value=MagicMock()),
        ), patch(
            "app.domain.shopping.high_level_tools.RecommendCapability.run",
            new=AsyncMock(return_value=capability_result),
        ):
            payload = await tool.coroutine(
                runtime=MagicMock(),
                query="recommend five headphones",
                limit=5,
            )

        assert payload["requested_limit"] == 5
        assert payload["returned_count"] == 1
        assert payload["product_cards"] == [
            {"product_id": 11, "title": "visible headphones"},
        ]
        assert "candidate_set" not in payload
        assert "trace" not in payload
        assert "need" not in payload
        assert "99" not in str(payload)

    asyncio.run(run())
