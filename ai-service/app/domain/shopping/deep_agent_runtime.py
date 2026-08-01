"""Compatibility helpers for the Shopping Deep Agents runtime.

Phase S0 does not replace ``ShoppingAgent`` yet.  This module records the
minimal runtime contract that Phase S1 will reuse:

* Deep Agents is pinned to the version validated by the service;
* the model may read Shopping Skills but cannot see generic write, shell,
  planning, or subagent tools;
* the filesystem is read-only and scoped to the ShoppingAgent Skill source.

These are execution-surface constraints, not shopping intent rules.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any, Iterable

from deepagents import FilesystemPermission
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from packaging.version import Version


SHOPPING_DEEPAGENTS_VERSION = "0.7.1"
SHOPPING_SKILL_SOURCE = "/skills/shopping-agent/"
SHOPPING_SHARED_SKILL_SOURCE = "/skills/shared/"

# ``read_file`` is required for Skill Level-2 loading.  Everything else from
# the generic Deep Agents harness is outside ShoppingAgent's Phase S0/S1
# responsibility and must not be visible to its model.
SHOPPING_ALLOWED_BUILTIN_TOOLS = frozenset({"read_file"})
SHOPPING_BLOCKED_BUILTIN_TOOLS = frozenset({
    "ls",
    "write_file",
    "edit_file",
    "delete",
    "glob",
    "grep",
    "execute",
    "task",
    "write_todos",
})


class DeepAgentsCompatibilityError(RuntimeError):
    """Raised when the installed Deep Agents runtime differs from the pin."""


def validate_shopping_deepagents_runtime() -> str:
    """Return the installed version after checking the Phase S0 exact pin."""
    try:
        installed = version("deepagents")
    except PackageNotFoundError as exc:  # pragma: no cover - environment error
        raise DeepAgentsCompatibilityError(
            "deepagents is not installed; install deepagents==0.7.1 first."
        ) from exc
    if Version(installed) != Version(SHOPPING_DEEPAGENTS_VERSION):
        raise DeepAgentsCompatibilityError(
            "Unsupported deepagents version: "
            f"installed={installed}, expected={SHOPPING_DEEPAGENTS_VERSION}."
        )
    return installed


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        name = tool.get("name")
        if name:
            return str(name)
        function = tool.get("function")
        if isinstance(function, dict):
            return str(function.get("name") or "")
        return ""
    return str(getattr(tool, "name", "") or "")


class ShoppingDeepAgentToolSurfaceMiddleware(AgentMiddleware):
    """Expose only Skill reading plus explicitly supplied Shopping tools.

    ``create_deep_agent`` adds filesystem and subagent tools to the model
    surface.  ShoppingAgent already lives below the global Router/Planner/DAG,
    so generic planning, subagent, file-write, and shell tools would duplicate
    orchestration and broaden the execution boundary.  Filtering happens at
    model-call time after Deep Agents has injected its built-ins.
    """

    def __init__(self, business_tool_names: Iterable[str]) -> None:
        super().__init__()
        names = {str(name).strip() for name in business_tool_names if str(name).strip()}
        collisions = names & SHOPPING_BLOCKED_BUILTIN_TOOLS
        if collisions:
            raise ValueError(
                "Shopping business tools collide with blocked Deep Agents tools: "
                + ", ".join(sorted(collisions))
            )
        self.allowed_tool_names = frozenset({*SHOPPING_ALLOWED_BUILTIN_TOOLS, *names})
        self.available_tool_snapshots: list[tuple[str, ...]] = []
        self.visible_tool_snapshots: list[tuple[str, ...]] = []

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        available_names = tuple(_tool_name(tool) for tool in (request.tools or []))
        visible = [
            tool
            for tool in (request.tools or [])
            if _tool_name(tool) in self.allowed_tool_names
        ]
        self.available_tool_snapshots.append(available_names)
        self.visible_tool_snapshots.append(tuple(_tool_name(tool) for tool in visible))
        return request.override(tools=visible)

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return handler(self._filtered_request(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(self._filtered_request(request))


def shopping_skill_permissions(
    *,
    include_shared: bool = False,
) -> list[FilesystemPermission]:
    """Build first-match filesystem rules for a read-only Skill source."""
    rules = [
        FilesystemPermission(
            operations=["read"],
            paths=[f"{SHOPPING_SKILL_SOURCE}**"],
            mode="allow",
        ),
    ]
    if include_shared:
        rules.append(
            FilesystemPermission(
                operations=["read"],
                paths=[f"{SHOPPING_SHARED_SKILL_SOURCE}**"],
                mode="allow",
            )
        )
    rules.extend([
        FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ])
    return rules


__all__ = [
    "DeepAgentsCompatibilityError",
    "SHOPPING_ALLOWED_BUILTIN_TOOLS",
    "SHOPPING_BLOCKED_BUILTIN_TOOLS",
    "SHOPPING_DEEPAGENTS_VERSION",
    "SHOPPING_SHARED_SKILL_SOURCE",
    "SHOPPING_SKILL_SOURCE",
    "ShoppingDeepAgentToolSurfaceMiddleware",
    "shopping_skill_permissions",
    "validate_shopping_deepagents_runtime",
]
