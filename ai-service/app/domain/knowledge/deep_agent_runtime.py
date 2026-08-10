"""Execution boundaries for the KnowledgeAgent Deep Agents runtime."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Awaitable, Callable, Iterable

from deepagents import FilesystemPermission
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from packaging.version import Version

from app.domain.knowledge.skill_backend import KNOWLEDGE_SKILL_SOURCE
from app.domain.knowledge.skill_observability import knowledge_skill_name_from_path


KNOWLEDGE_DEEPAGENTS_VERSION = "0.7.1"
KNOWLEDGE_ALLOWED_SKILLS = frozenset({
    "answer-with-evidence",
    "answer-safety-question",
})
KNOWLEDGE_ALLOWED_BUILTIN_TOOLS = frozenset({"read_file"})
KNOWLEDGE_BLOCKED_BUILTIN_TOOLS = frozenset({
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


class KnowledgeDeepAgentsCompatibilityError(RuntimeError):
    """Raised when the installed Deep Agents version differs from the pin."""


def validate_knowledge_deepagents_runtime() -> str:
    try:
        installed = version("deepagents")
    except PackageNotFoundError as exc:  # pragma: no cover - environment error
        raise KnowledgeDeepAgentsCompatibilityError(
            "deepagents is not installed; install deepagents==0.7.1 first."
        ) from exc
    if Version(installed) != Version(KNOWLEDGE_DEEPAGENTS_VERSION):
        raise KnowledgeDeepAgentsCompatibilityError(
            "Unsupported deepagents version: "
            f"installed={installed}, expected={KNOWLEDGE_DEEPAGENTS_VERSION}."
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


class KnowledgeDeepAgentToolSurfaceMiddleware(AgentMiddleware):
    """Expose Skill reading first, then the explicit Knowledge business tools."""

    def __init__(
        self,
        business_tool_names: Iterable[str],
        *,
        skill_contract: "RequireKnowledgeSkillMiddleware | None" = None,
    ) -> None:
        super().__init__()
        names = {str(name).strip() for name in business_tool_names if str(name).strip()}
        collisions = names & KNOWLEDGE_BLOCKED_BUILTIN_TOOLS
        if collisions:
            raise ValueError(
                "Knowledge business tools collide with blocked Deep Agents tools: "
                + ", ".join(sorted(collisions))
            )
        self._business_tool_names = frozenset(names)
        self._skill_contract = skill_contract
        self.allowed_tool_names = frozenset({*KNOWLEDGE_ALLOWED_BUILTIN_TOOLS, *names})
        self.visible_tool_snapshots: list[tuple[str, ...]] = []

    def _filtered_request(self, request: ModelRequest) -> ModelRequest:
        # Before the agent has loaded a valid Skill, ``read_file`` is the only
        # visible tool.  Together with RequireKnowledgeRetrievalMiddleware's
        # ``tool_choice=required`` this makes Skill loading the first action,
        # without guessing which of the two Skills the model should use.
        # Once a Skill is loaded, the model sees the real retrieval tool and
        # remains free to formulate its own query.
        allowed = set(KNOWLEDGE_ALLOWED_BUILTIN_TOOLS)
        if self._skill_contract is None or self._skill_contract.read_skills:
            allowed.update(self._business_tool_names)
        visible = [
            tool for tool in (request.tools or [])
            if _tool_name(tool) in allowed
        ]
        self.visible_tool_snapshots.append(tuple(_tool_name(tool) for tool in visible))
        return request.override(tools=visible)

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return handler(self._filtered_request(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(self._filtered_request(request))


def _has_successful_knowledge_result(messages: Iterable[Any]) -> bool:
    """Whether the current run already has real evidence to answer from."""
    return any(
        isinstance(message, ToolMessage)
        and str(getattr(message, "name", "") or "") == "search_knowledge"
        and str(getattr(message, "status", "") or "").lower() not in {"error", "failed"}
        for message in (messages or [])
    )


class RequireKnowledgeRetrievalMiddleware(AgentMiddleware):
    """Require an evidence-producing tool action before a final answer.

    Router has already decided that this is a knowledge request.  This
    middleware does not classify the question or prescribe a Skill; it only
    prevents the model from ending a knowledge turn before a real retrieval
    result exists.  The model still selects the matching Skill and query.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        if not _has_successful_knowledge_result(request.messages or []):
            return await handler(request.override(tool_choice="required"))
        return await handler(request)


class RequireKnowledgeSkillMiddleware(AgentMiddleware):
    """Require a valid Knowledge Skill before executing a knowledge tool."""

    def __init__(self, *, skill_source: str = KNOWLEDGE_SKILL_SOURCE) -> None:
        super().__init__()
        self._skill_source = f"/{str(skill_source).strip('/')}/"
        self.read_skills: list[str] = []
        self.records: list[dict[str, Any]] = []

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_call = dict(request.tool_call or {})
        tool_name = str(tool_call.get("name") or getattr(request.tool, "name", "") or "")
        args = tool_call.get("args") or {}
        args = dict(args) if isinstance(args, dict) else {}
        call_id = str(tool_call.get("id") or "knowledge-skill-contract")

        if tool_name == "read_file":
            result = await handler(request)
            if not (
                isinstance(result, ToolMessage)
                and getattr(result, "status", None) == "error"
            ):
                skill_name = knowledge_skill_name_from_path(
                    args.get("file_path") or args.get("path"),
                    skill_source=self._skill_source,
                )
                if (
                    skill_name in KNOWLEDGE_ALLOWED_SKILLS
                    and skill_name not in self.read_skills
                ):
                    self.read_skills.append(skill_name)
            return result

        if tool_name != "search_knowledge" or self.read_skills:
            return await handler(request)

        self.records.append({
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "status": "blocked",
            "error_code": "KNOWLEDGE_SKILL_REQUIRED",
        })
        return ToolMessage(
            content=json.dumps({
                "error": True,
                "error_code": "KNOWLEDGE_SKILL_REQUIRED",
                "message": (
                    "调用 search_knowledge 前必须先使用 read_file 读取最匹配的 "
                    "/skills/knowledge-agent/<skill>/SKILL.md，然后按 Skill 重试。"
                ),
            }, ensure_ascii=False),
            tool_call_id=call_id,
            name=tool_name,
            status="error",
        )


def knowledge_skill_permissions(
    *,
    skill_source: str = KNOWLEDGE_SKILL_SOURCE,
) -> list[FilesystemPermission]:
    source = f"/{str(skill_source).strip('/')}/"
    return [
        FilesystemPermission(operations=["read"], paths=[f"{source}**"], mode="allow"),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]


__all__ = [
    "KNOWLEDGE_ALLOWED_SKILLS",
    "KNOWLEDGE_DEEPAGENTS_VERSION",
    "KnowledgeDeepAgentToolSurfaceMiddleware",
    "RequireKnowledgeRetrievalMiddleware",
    "RequireKnowledgeSkillMiddleware",
    "knowledge_skill_permissions",
    "validate_knowledge_deepagents_runtime",
]
