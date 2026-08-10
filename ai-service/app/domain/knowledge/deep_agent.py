"""Deep Agents adapter for the existing KnowledgeAgent contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from deepagents import create_deep_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

from app.application.assistant.state import KnowledgeAgentState
from app.domain.knowledge.deep_agent_runtime import (
    KnowledgeDeepAgentToolSurfaceMiddleware,
    RequireKnowledgeRetrievalMiddleware,
    RequireKnowledgeSkillMiddleware,
    knowledge_skill_permissions,
    validate_knowledge_deepagents_runtime,
)
from app.domain.knowledge.skill_backend import (
    build_knowledge_skill_backend,
    normalise_knowledge_skill_source,
)
from app.prompts.prompts import KNOWLEDGE_SKILL_BOOTSTRAP_PROMPT


KNOWLEDGE_DEEP_AGENT_RUNTIME = "deep_agent"


@dataclass(frozen=True)
class KnowledgeDeepAgentRuntime:
    graph: Any
    skill_source: str
    skill_contract: RequireKnowledgeSkillMiddleware
    tool_surface: KnowledgeDeepAgentToolSurfaceMiddleware


class KnowledgeDeepAgentAdapter:
    """Build a request-local DeepAgent while preserving KnowledgeAgent.run."""

    def __init__(
        self,
        *,
        llm: Any,
        tools: Iterable[Any],
        checkpointer: Any,
        skills_root: str,
        backend: Any | None = None,
    ) -> None:
        self._llm = llm
        self._tools = list(tools)
        self._checkpointer = checkpointer
        self._skill_source = normalise_knowledge_skill_source(skills_root)
        self._backend = backend

    def build(self, *, system_prompt: str) -> KnowledgeDeepAgentRuntime:
        validate_knowledge_deepagents_runtime()
        tool_names = {str(getattr(tool, "name", "") or "") for tool in self._tools}
        skill_contract = RequireKnowledgeSkillMiddleware(
            skill_source=self._skill_source,
        )
        surface = KnowledgeDeepAgentToolSurfaceMiddleware(
            tool_names,
            skill_contract=skill_contract,
        )
        graph = create_deep_agent(
            model=self._llm,
            tools=self._tools,
            system_prompt=system_prompt + "\n\n" + KNOWLEDGE_SKILL_BOOTSTRAP_PROMPT,
            skills=[self._skill_source],
            backend=self._backend or build_knowledge_skill_backend(),
            permissions=knowledge_skill_permissions(skill_source=self._skill_source),
            middleware=[
                RequireKnowledgeRetrievalMiddleware(),
                skill_contract,
                surface,
                ToolCallLimitMiddleware(
                    tool_name="search_knowledge",
                    run_limit=2,
                    exit_behavior="continue",
                ),
                ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"),
            ],
            subagents=[],
            state_schema=KnowledgeAgentState,
            checkpointer=self._checkpointer,
            name="knowledge-deep-agent",
        )
        return KnowledgeDeepAgentRuntime(
            graph=graph,
            skill_source=self._skill_source,
            skill_contract=skill_contract,
            tool_surface=surface,
        )


__all__ = [
    "KNOWLEDGE_DEEP_AGENT_RUNTIME",
    "KnowledgeDeepAgentAdapter",
    "KnowledgeDeepAgentRuntime",
]
