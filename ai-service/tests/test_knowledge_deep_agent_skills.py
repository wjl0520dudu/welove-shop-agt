"""KnowledgeAgent DeepAgent + Skills runtime tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.tools import tool
from pydantic import PrivateAttr

from app.api.response_adapter import normalize_ai_response
from app.domain.knowledge import agent as knowledge_agent_module
from app.domain.knowledge.agent import KnowledgeAgent
from app.domain.knowledge.deep_agent_runtime import (
    KnowledgeDeepAgentToolSurfaceMiddleware,
    RequireKnowledgeRetrievalMiddleware,
    RequireKnowledgeSkillMiddleware,
)
from app.domain.knowledge.skill_backend import (
    AI_SERVICE_ROOT,
    build_knowledge_skill_backend,
    normalise_knowledge_skill_source,
)
from app.domain.knowledge.skill_observability import extract_knowledge_skill_reads
from app.infrastructure.config import config


SKILLS_ROOT = AI_SERVICE_ROOT / "skills" / "knowledge-agent"
EXPECTED_SKILLS = {"answer-with-evidence", "answer-safety-question"}


class _RecordingToolModel(FakeMessagesListChatModel):
    _tool_bindings: list[dict[str, Any]] = PrivateAttr(default_factory=list)

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


@tool("search_knowledge", description="Return deterministic evidence for tests.")
async def _search_knowledge(query: str, search_mode: str = "hybrid", use_rerank: bool = True) -> dict:
    return {
        "knowledge_context": "[资料1] 来源：测试知识库\n开放式耳机不会封闭耳道。",
        "sources": [{"title": "测试知识库", "score": 0.9}],
        "total_results": 1,
        "search_mode": search_mode,
        "use_rerank": use_rerank,
        "fallback_used": False,
        "query": query,
    }


async def _grounded(*_args, **_kwargs):
    return True, "test"


async def _no_persist(*_args, **_kwargs):
    return None


def test_knowledge_deep_agent_is_enabled_by_default():
    assert config.KNOWLEDGE_DEEP_AGENT_ENABLED is True


def test_knowledge_skills_are_standard_and_namespaced():
    assert {path.name for path in SKILLS_ROOT.iterdir() if path.is_dir()} == EXPECTED_SKILLS
    for name in EXPECTED_SKILLS:
        text = (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert f"name: {name}" in text
        assert "description:" in text
        assert "TODO" not in text


def test_knowledge_backend_is_virtual_and_confined():
    backend = build_knowledge_skill_backend()
    assert Path(backend.cwd).resolve() == AI_SERVICE_ROOT.resolve()
    assert backend.virtual_mode is True
    assert normalise_knowledge_skill_source("skills/knowledge-agent") == (
        "/skills/knowledge-agent/"
    )
    with pytest.raises(ValueError, match="KNOWLEDGE_SKILLS_ROOT"):
        normalise_knowledge_skill_source("/skills/shopping-agent/")


def test_knowledge_skill_observability_excludes_other_paths_and_failed_reads():
    messages = [
        _call(
            "read_file",
            "ok",
            {"file_path": "/skills/knowledge-agent/answer-with-evidence/SKILL.md"},
        ),
        _call(
            "read_file",
            "failed",
            {"file_path": "/skills/knowledge-agent/answer-safety-question/SKILL.md"},
        ),
        ToolMessage(
            content="permission denied",
            tool_call_id="failed",
            name="read_file",
            status="error",
        ),
        _call("read_file", "other", {"file_path": "/skills/shopping-agent/a/SKILL.md"}),
    ]
    assert extract_knowledge_skill_reads(messages) == ["answer-with-evidence"]


def test_skill_contract_blocks_search_before_a_valid_skill_read():
    middleware = RequireKnowledgeSkillMiddleware()

    class _Request:
        tool_call = {
            "id": "search-before-skill",
            "name": "search_knowledge",
            "args": {"query": "烟酰胺"},
        }
        tool = _search_knowledge

    async def handler(_request):
        raise AssertionError("blocked search must not reach the real tool")

    result = asyncio.run(middleware.awrap_tool_call(_Request(), handler))
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "KNOWLEDGE_SKILL_REQUIRED" in str(result.content)


def test_knowledge_model_turn_requires_a_tool_until_real_evidence_exists():
    async def run():
        middleware = RequireKnowledgeRetrievalMiddleware()
        observed: list[object] = []

        async def handler(request):
            observed.append(request.tool_choice)
            return ModelResponse(result=[AIMessage(content="ok")])

        initial = ModelRequest(
            model=_RecordingToolModel(responses=[]),
            messages=[HumanMessage(content="烟酰胺能不能白天用")],
        )
        after_skill = ModelRequest(
            model=_RecordingToolModel(responses=[]),
            messages=[
                HumanMessage(content="烟酰胺能不能白天用"),
                ToolMessage(
                    content="# answer-with-evidence",
                    tool_call_id="skill",
                    name="read_file",
                ),
            ],
        )
        after_blocked_search = ModelRequest(
            model=_RecordingToolModel(responses=[]),
            messages=[
                HumanMessage(content="烟酰胺能不能白天用"),
                ToolMessage(
                    content='{"error":true,"error_code":"KNOWLEDGE_SKILL_REQUIRED"}',
                    tool_call_id="blocked",
                    name="search_knowledge",
                    status="error",
                ),
            ],
        )
        after_retrieval = ModelRequest(
            model=_RecordingToolModel(responses=[]),
            messages=[
                HumanMessage(content="烟酰胺能不能白天用"),
                ToolMessage(
                    content='{"knowledge_context":"资料","sources":[{"title":"测试"}]}',
                    tool_call_id="search",
                    name="search_knowledge",
                ),
            ],
        )

        await middleware.awrap_model_call(initial, handler)
        await middleware.awrap_model_call(after_skill, handler)
        await middleware.awrap_model_call(after_blocked_search, handler)
        await middleware.awrap_model_call(after_retrieval, handler)

        assert observed == ["required", "required", "required", None]

    asyncio.run(run())


def test_knowledge_tool_surface_exposes_search_only_after_skill_read():
    async def run():
        contract = RequireKnowledgeSkillMiddleware()
        surface = KnowledgeDeepAgentToolSurfaceMiddleware(
            ["search_knowledge"],
            skill_contract=contract,
        )
        observed: list[tuple[str, ...]] = []

        async def handler(request):
            observed.append(tuple(_tool_name(tool) for tool in request.tools or []))
            return ModelResponse(result=[AIMessage(content="ok")])

        request = ModelRequest(
            model=_RecordingToolModel(responses=[]),
            messages=[HumanMessage(content="烟酰胺能不能白天用")],
            tools=[
                SimpleNamespace(name="read_file"),
                SimpleNamespace(name="search_knowledge"),
                SimpleNamespace(name="execute"),
            ],
        )
        await surface.awrap_model_call(request, handler)
        contract.read_skills.append("answer-with-evidence")
        await surface.awrap_model_call(request, handler)

        assert observed == [
            ("read_file",),
            ("read_file", "search_knowledge"),
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    ("skill_name", "question"),
    [
        ("answer-with-evidence", "开放式耳机和入耳式耳机有什么区别？"),
        ("answer-safety-question", "孕妇能使用含视黄醇的护肤品吗？"),
    ],
)
def test_deep_agent_reads_matching_skill_then_searches(
    monkeypatch,
    skill_name: str,
    question: str,
):
    model = _RecordingToolModel(responses=[
        _call(
            "read_file",
            "skill",
            {"file_path": f"/skills/knowledge-agent/{skill_name}/SKILL.md"},
        ),
        _call(
            "search_knowledge",
            "search",
            {"query": question, "search_mode": "hybrid", "use_rerank": True},
        ),
        AIMessage(content="这是严格依据测试资料生成的回答。"),
    ])
    monkeypatch.setattr(config, "KNOWLEDGE_DEEP_AGENT_ENABLED", True)
    monkeypatch.setattr(config, "KNOWLEDGE_SKILLS_ROOT", "/skills/knowledge-agent/")
    monkeypatch.setattr(knowledge_agent_module, "search_knowledge", _search_knowledge)
    monkeypatch.setattr(knowledge_agent_module, "_grounding_check", _grounded)
    monkeypatch.setattr(KnowledgeAgent, "_persist_entities", _no_persist)

    result = asyncio.run(KnowledgeAgent(model).run(
        messages=[HumanMessage(content=question)],
        conversation_id=f"knowledge-{skill_name}",
    ))

    assert result["answer"] == "这是严格依据测试资料生成的回答。"
    assert result["knowledge_runtime"] == "deep_agent"
    assert result["skill_reads"] == [skill_name]
    assert [item["tool_name"] for item in result["tool_calls"]] == ["search_knowledge"]
    assert result["sources"][0]["title"] == "测试知识库"
    assert result["has_answer"] is True


def test_disabled_switch_keeps_legacy_langchain_agent(monkeypatch):
    model = _RecordingToolModel(responses=[
        _call("search_knowledge", "search", {"query": "烟酰胺"}),
        AIMessage(content="旧链显式回滚仍可使用。"),
    ])
    monkeypatch.setattr(config, "KNOWLEDGE_DEEP_AGENT_ENABLED", False)
    monkeypatch.setattr(knowledge_agent_module, "search_knowledge", _search_knowledge)
    monkeypatch.setattr(knowledge_agent_module, "_grounding_check", _grounded)
    monkeypatch.setattr(KnowledgeAgent, "_persist_entities", _no_persist)

    result = asyncio.run(KnowledgeAgent(model).run(
        messages=[HumanMessage(content="烟酰胺是什么？")],
        conversation_id="knowledge-legacy",
    ))

    assert result["knowledge_runtime"] == "langchain_agent"
    assert result["skill_reads"] == []
    assert result["answer"] == "旧链显式回滚仍可使用。"


def test_knowledge_observability_survives_response_adapter():
    response = normalize_ai_response({
        "answer": "完成",
        "task_type": "knowledge",
        "knowledge_runtime": "deep_agent",
        "skill_reads": ["answer-with-evidence"],
    })
    assert response.knowledge_runtime == "deep_agent"
    assert response.skill_reads == ["answer-with-evidence"]
