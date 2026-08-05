"""Deep Agents adapter for the existing ShoppingAgent contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from deepagents import create_deep_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware

from app.application.assistant.state import ShoppingAgentState
from app.prompts.prompts import SHOPPING_SKILL_BOOTSTRAP_PROMPT
from app.domain.shopping.deep_agent_runtime import (
    ShoppingDeepAgentToolSurfaceMiddleware,
    shopping_skill_permissions,
    validate_shopping_deepagents_runtime,
)
from app.domain.shopping.skill_backend import (
    build_shopping_skill_backend,
    normalise_shopping_skill_source,
)
from app.domain.shopping.tool_guard import (
    RequireInitialShoppingToolMiddleware,
    RequireMatchingShoppingSkillMiddleware,
    RequireMultimodalConsistencyMiddleware,
    ShoppingToolGuardMiddleware,
)


SHOPPING_DEEP_AGENT_RUNTIME = "deep_agent"

@dataclass(frozen=True)
class ShoppingDeepAgentRuntime:
    """Compiled graph plus request-local middleware used for observations."""

    graph: Any
    tool_surface: ShoppingDeepAgentToolSurfaceMiddleware
    skill_source: str


class ShoppingDeepAgentAdapter:
    """Build DeepAgent without changing ShoppingAgent.run inputs or outputs."""

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
        self._skill_source = normalise_shopping_skill_source(skills_root)
        self._backend = backend

    def build(
        self,
        *,
        system_prompt: str,
        guard: ShoppingToolGuardMiddleware,
        multimodal_guard: RequireMultimodalConsistencyMiddleware,
    ) -> ShoppingDeepAgentRuntime:
        validate_shopping_deepagents_runtime()
        business_tool_names = {
            str(getattr(tool, "name", "") or "") for tool in self._tools
        }
        surface = ShoppingDeepAgentToolSurfaceMiddleware(business_tool_names)
        skill_contract = RequireMatchingShoppingSkillMiddleware(
            skill_source=self._skill_source,
        )
        graph = create_deep_agent(
            model=self._llm,
            tools=self._tools,
            system_prompt=system_prompt + "\n\n" + SHOPPING_SKILL_BOOTSTRAP_PROMPT,
            skills=[self._skill_source],
            backend=self._backend or build_shopping_skill_backend(),
            permissions=shopping_skill_permissions(
                skill_source=self._skill_source,
            ),
            middleware=[
                RequireInitialShoppingToolMiddleware(),
                skill_contract,
                multimodal_guard,
                guard,
                surface,
                # Six calls support one correction plus profile/business Skill,
                # their business tools and one optional controlled script.
                ToolCallLimitMiddleware(run_limit=6, exit_behavior="continue"),
                ModelCallLimitMiddleware(run_limit=8, exit_behavior="end"),
            ],
            subagents=[],
            state_schema=ShoppingAgentState,
            checkpointer=self._checkpointer,
            name="shopping-deep-agent",
        )
        return ShoppingDeepAgentRuntime(
            graph=graph,
            tool_surface=surface,
            skill_source=self._skill_source,
        )


__all__ = [
    "SHOPPING_DEEP_AGENT_RUNTIME",
    "ShoppingDeepAgentAdapter",
    "ShoppingDeepAgentRuntime",
]
