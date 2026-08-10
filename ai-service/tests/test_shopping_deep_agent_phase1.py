"""Phase S1 tests for ShoppingAgent Skills and the DeepAgent adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.api.response_adapter import normalize_ai_response
from app.domain.shopping import agent as shopping_agent_module
from app.domain.shopping.agent import ShoppingAgent
from app.domain.shopping.skill_backend import (
    AI_SERVICE_ROOT,
    build_shopping_skill_backend,
    normalise_shopping_skill_source,
)
from app.domain.shopping.skill_observability import extract_shopping_skill_reads
from app.infrastructure.config import config


SKILLS_ROOT = AI_SERVICE_ROOT / "skills" / "shopping-agent"


def test_production_image_copies_deep_agent_skills():
    dockerfile = (AI_SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY skills ./skills" in dockerfile
EXPECTED_SKILLS = {
    "discover-products",
    "compare-products",
    "inspect-product",
    "multimodal-consistency",
    "use-shopping-profile",
}


def test_deep_agent_skill_runtime_is_enabled_by_default():
    assert config.SHOPPING_DEEP_AGENT_ENABLED is True


class _RecordingToolModel(FakeMessagesListChatModel):
    _tool_bindings: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def tool_bindings(self) -> list[dict[str, Any]]:
        return self._tool_bindings

    def bind_tools(self, tools, **kwargs):
        self._tool_bindings.append({
            "names": tuple(_tool_name(tool) for tool in tools),
            "tool_choice": kwargs.get("tool_choice"),
        })
        return self


def _tool_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or (value.get("function") or {}).get("name") or "")
    return str(getattr(value, "name", "") or "")


def _call(name: str, call_id: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": name, "args": args}],
    )


@tool("recommend_products", description="Return deterministic products for S1.")
async def _recommend_products(query: str) -> dict:
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 7, "title": "S1 测试商品"}],
        "returned_count": 1,
        "query": query,
    }


@tool("compare_products", description="Compare Router-bound products for S1.")
async def _compare_products(query: str, product_ids: list[int]) -> dict:
    return {
        "action": "compare",
        "comparison_rows": [{"product_id": value} for value in product_ids],
        "suggestion": {"reason": "S1 对比完成"},
        "query": query,
    }


@tool("answer_product_detail", description="Inspect one Router-bound product for S1.")
async def _answer_product_detail(query: str, product_id: int) -> dict:
    return {
        "action": "detail",
        "facts": {"product_id": product_id, "price": 299},
        "query": query,
    }


@tool("get_user_shopping_context", description="Return allowed profile data for S1.")
async def _get_user_shopping_context(include_favorites: bool = False) -> dict:
    return {
        "error": False,
        "data": {"profile": {"skin_type": "油皮"}},
        "include_favorites": include_favorites,
    }


FAKE_BUSINESS_TOOLS = [
    _recommend_products,
    _compare_products,
    _answer_product_detail,
    _get_user_shopping_context,
]


def test_shopping_agent_skills_and_reserved_namespaces_are_complete():
    assert {path.name for path in SKILLS_ROOT.iterdir() if path.is_dir()} == EXPECTED_SKILLS
    for name in EXPECTED_SKILLS:
        text = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert f"name: {name}" in text
        assert "description:" in text
        assert "TODO" not in text

    for namespace in ("knowledge-agent", "chitchat-agent", "shared"):
        assert (AI_SERVICE_ROOT / "skills" / namespace).is_dir()


def test_skill_backend_is_virtual_and_confined_to_shopping_namespace():
    backend = build_shopping_skill_backend()
    assert Path(backend.cwd).resolve() == AI_SERVICE_ROOT.resolve()
    assert backend.virtual_mode is True
    assert normalise_shopping_skill_source("skills/shopping-agent") == (
        "/skills/shopping-agent/"
    )
    with pytest.raises(ValueError, match="SHOPPING_SKILLS_ROOT"):
        normalise_shopping_skill_source("/skills/shared/")


def test_skill_observability_exposes_only_direct_skill_names():
    messages = [
        _call(
            "read_file",
            "one",
            {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
        ),
        _call(
            "read_file",
            "two",
            {"file_path": "/skills/shopping-agent/discover-products/references/detail.md"},
        ),
        _call("read_file", "three", {"file_path": "/.env"}),
    ]
    assert extract_shopping_skill_reads(messages) == ["discover-products"]


def test_skill_observability_excludes_failed_skill_reads():
    messages = [
        _call(
            "read_file",
            "failed",
            {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
        ),
        ToolMessage(
            content="permission denied",
            tool_call_id="failed",
            name="read_file",
            status="error",
        ),
    ]
    assert extract_shopping_skill_reads(messages) == []


def test_skill_observability_survives_the_public_response_adapter():
    response = normalize_ai_response({
        "answer": "完成",
        "task_type": "shopping",
        "shopping_runtime": "deep_agent",
        "skill_reads": ["discover-products"],
    })
    assert response.shopping_runtime == "deep_agent"
    assert response.skill_reads == ["discover-products"]


@pytest.mark.parametrize(
    ("skill_name", "business_call", "selected_ids", "expected_capability"),
    [
        (
            "discover-products",
            _call("recommend_products", "business", {"query": "推荐通勤耳机"}),
            [],
            "recommend",
        ),
        (
            "compare-products",
            _call(
                "compare_products",
                "business",
                {"query": "比较这两款", "product_ids": [42, 37]},
            ),
            [42, 37],
            "compare",
        ),
        (
            "inspect-product",
            _call(
                "answer_product_detail",
                "business",
                {"query": "这款多少钱", "product_id": 42},
            ),
            [42],
            "detail",
        ),
    ],
)
def test_deep_agent_reads_task_skill_and_preserves_shopping_contract(
    monkeypatch,
    skill_name: str,
    business_call: AIMessage,
    selected_ids: list[int],
    expected_capability: str,
):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "skill",
                {"file_path": f"/skills/shopping-agent/{skill_name}/SKILL.md"},
            ),
            business_call,
            AIMessage(content="已依据 Skill 和真实商品工具完成。"),
        ])
        agent = ShoppingAgent(model)
        return await agent.run(
            question="执行当前商品任务",
            messages=[],
            business_memory={"selected_product_ids": selected_ids},
            conversation_id="s1-conversation",
            selected_product_ids=selected_ids,
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", FAKE_BUSINESS_TOOLS
    )

    result = asyncio.run(run())

    assert result["answer"] == "已依据 Skill 和真实商品工具完成。"
    assert result["task_type"] == "shopping"
    assert result["capability"] == expected_capability
    assert result["dispatch_source"] == "agent_tool_loop"
    assert result["shopping_runtime"] == "deep_agent"
    assert result["skill_reads"] == [skill_name]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        business_call.tool_calls[0]["name"]
    ]
    assert "read_file" not in {item["tool_name"] for item in result["tool_calls"]}


def test_profile_task_can_read_profile_then_discovery_skill(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call(
                "read_file",
                "profile-skill",
                {"file_path": "/skills/shopping-agent/use-shopping-profile/SKILL.md"},
            ),
            _call(
                "get_user_shopping_context",
                "profile-tool",
                {"include_favorites": False},
            ),
            _call(
                "read_file",
                "discover-skill",
                {"file_path": "/skills/shopping-agent/discover-products/SKILL.md"},
            ),
            _call(
                "recommend_products",
                "recommend-tool",
                {"query": "根据我的肤质推荐防晒"},
            ),
            AIMessage(content="已结合允许的画像和真实商品结果完成推荐。"),
        ])
        return await ShoppingAgent(model).run(
            question="根据我的肤质推荐防晒",
            messages=[],
            business_memory={"user_preferences": {"skin_type": "油皮"}},
            user_id=1,
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "SHOPPING_SKILLS_ROOT", "/skills/shopping-agent/")
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", FAKE_BUSINESS_TOOLS
    )

    result = asyncio.run(run())

    assert result["skill_reads"] == ["use-shopping-profile", "discover-products"]
    assert [item["tool_name"] for item in result["tool_calls"]] == [
        "get_user_shopping_context",
        "recommend_products",
    ]
    assert result["capability"] == "recommend"
    assert result["shopping_runtime"] == "deep_agent"


def test_disabled_switch_keeps_existing_langchain_agent_runtime(monkeypatch):
    async def run():
        model = _RecordingToolModel(responses=[
            _call("recommend_products", "business", {"query": "推荐耳机"}),
            AIMessage(content="旧运行链路仍可用。"),
        ])
        return await ShoppingAgent(model).run(
            question="推荐耳机",
            messages=[],
            business_memory={},
        )

    monkeypatch.setattr(config, "SHOPPING_DEEP_AGENT_ENABLED", False)
    monkeypatch.setattr(
        shopping_agent_module, "_DEEP_AGENT_BUSINESS_TOOLS", FAKE_BUSINESS_TOOLS
    )

    result = asyncio.run(run())

    assert result["shopping_runtime"] == "langchain_agent"
    assert result["skill_reads"] == []
    assert result["dispatch_source"] == "agent_tool_loop"
