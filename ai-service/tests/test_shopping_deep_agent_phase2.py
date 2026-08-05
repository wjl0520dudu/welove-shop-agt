"""Phase S2 tests for progressive Shopping Skill loading."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent
from app.domain.shopping.high_level_tools import SHOPPING_HIGH_LEVEL_TOOLS
from app.domain.shopping.tool_guard import SHOPPING_TOOL_SKILL_REQUIREMENTS
from app.infrastructure.config import config
from app.prompts.prompts import (
    SHOPPING_AGENT_PROMPT,
    SHOPPING_SKILL_BOOTSTRAP_PROMPT,
)


AI_SERVICE_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SKILL = (
    AI_SERVICE_ROOT / "skills" / "shopping-agent" / "discover-products"
)
_EXECUTIONS: list[str] = []


class _RecordingToolModel(FakeMessagesListChatModel):
    _tool_bindings: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def tool_bindings(self) -> list[dict[str, Any]]:
        return self._tool_bindings

    def bind_tools(self, tools, **kwargs):
        self._tool_bindings.append({
            "names": tuple(str(getattr(value, "name", "") or "") for value in tools),
            "tool_choice": kwargs.get("tool_choice"),
        })
        return self


def _call(name: str, call_id: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": name, "args": args}],
    )


@tool("recommend_products", description="Return deterministic S2 products.")
async def _recommend_products(query: str) -> dict:
    _EXECUTIONS.append(query)
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 71, "title": "S2 测试耳机"}],
        "ranked_products": [{"product_id": 71, "title": "S2 测试耳机"}],
        "returned_count": 1,
    }


def test_phase_s2_prompt_is_materially_smaller_than_the_previous_manual():
    # Migration baseline: 4,238 characters before Phase S2.
    assert len(SHOPPING_AGENT_PROMPT) < 1500
    assert len(SHOPPING_AGENT_PROMPT) <= int(4238 * 0.35)
    assert "操作手册 A" not in SHOPPING_AGENT_PROMPT
    assert "固定执行闭环" not in SHOPPING_AGENT_PROMPT
    assert "必须使用 `read_file`" in SHOPPING_SKILL_BOOTSTRAP_PROMPT


def test_each_business_tool_has_one_explicit_skill_contract():
    assert SHOPPING_TOOL_SKILL_REQUIREMENTS == {
        "check_multimodal_consistency": "multimodal-consistency",
        "recommend_products": "discover-products",
        "search_product_candidates": "discover-products",
        "finalize_product_recommendation": "discover-products",
        "compare_products": "compare-products",
        "answer_product_detail": "inspect-product",
        "get_user_shopping_context": "use-shopping-profile",
    }


def test_business_tool_descriptions_no_longer_duplicate_skill_manuals():
    for business_tool in SHOPPING_HIGH_LEVEL_TOOLS:
        description = str(getattr(business_tool, "description", "") or "")
        assert "固定执行闭环" not in description
        assert "典型示例" not in description
        assert "Args:" not in description
        assert "Returns:" not in description


def test_discovery_skill_links_the_candidate_judging_reference():
    skill_text = (DISCOVERY_SKILL / "SKILL.md").read_text(encoding="utf-8")
    reference = DISCOVERY_SKILL / "references" / "candidate-judging.md"

    assert "references/candidate-judging.md" in skill_text
    assert reference.is_file()
    reference_text = reference.read_text(encoding="utf-8")
    assert "exact" in reference_text
    assert "alternative" in reference_text
    assert "基础偏好软排序" in reference_text


def test_discovery_skill_requires_multimodal_consistency_skill_before_retrieval():
    skill_text = (DISCOVERY_SKILL / "SKILL.md").read_text(encoding="utf-8")
    consistency_skill = (
        AI_SERVICE_ROOT / "skills" / "shopping-agent" / "multimodal-consistency" / "SKILL.md"
    )

    assert "multimodal-consistency/SKILL.md" in skill_text
    assert consistency_skill.is_file()
    consistency_text = consistency_skill.read_text(encoding="utf-8")
    assert "check_multimodal_consistency" in consistency_text
    assert "uncertain" in consistency_text


def test_deep_agent_blocks_direct_business_call_then_recovers_after_skill_read(
    monkeypatch,
):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "recommend_products",
                "blocked-before-skill",
                {"query": "推荐通勤耳机"},
            ),
            _call(
                "read_file",
                "read-discovery",
                {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
            ),
            _call(
                "recommend_products",
                "executed-after-skill",
                {"query": "推荐通勤耳机"},
            ),
            AIMessage(content="已按能力说明和真实商品结果完成推荐。"),
        ])
        result = await ShoppingAgent(model).run(
            question="推荐通勤耳机",
            messages=[],
            business_memory={},
            conversation_id="s2-contract",
        )
        return model, result

    _EXECUTIONS.clear()
    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", [_recommend_products]
    )

    model, result = asyncio.run(run())

    assert _EXECUTIONS == ["推荐通勤耳机"]
    assert result["answer"] == "已按能力说明和真实商品结果完成推荐。"
    assert result["skill_reads"] == ["discover-products"]
    assert result["shopping_runtime"] == "deep_agent"
    assert [item["tool_call_id"] for item in result["tool_calls"]] == [
        "executed-after-skill"
    ]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "recommend_products"
    ]
    assert [binding["tool_choice"] for binding in model.tool_bindings][:4] == [
        "required",
        "required",
        "required",
        None,
    ]
