"""Privacy-safe observability for KnowledgeAgent Skill reads."""

from __future__ import annotations

from typing import Any, Iterable

from app.domain.knowledge.skill_backend import KNOWLEDGE_SKILL_SOURCE


def _tool_call_parts(tool_call: Any) -> tuple[str, str, dict[str, Any]]:
    if isinstance(tool_call, dict):
        call_id = str(tool_call.get("id") or "")
        name = str(tool_call.get("name") or "")
        args = tool_call.get("args") or tool_call.get("arguments") or {}
    else:
        call_id = str(getattr(tool_call, "id", "") or "")
        name = str(getattr(tool_call, "name", "") or "")
        args = getattr(tool_call, "args", None) or getattr(
            tool_call, "arguments", None
        ) or {}
    return call_id, name, dict(args) if isinstance(args, dict) else {}


def knowledge_skill_name_from_path(
    raw_path: Any,
    *,
    skill_source: str = KNOWLEDGE_SKILL_SOURCE,
) -> str | None:
    """Return a direct Knowledge Skill name for an exact SKILL.md path."""
    source = f"/{str(skill_source).strip('/')}".replace("\\", "/")
    path = f"/{str(raw_path or '').strip('/')}".replace("\\", "/")
    if not path.startswith(f"{source}/") or not path.endswith("/SKILL.md"):
        return None
    relative = path[len(source) + 1 :]
    parts = relative.split("/")
    if len(parts) != 2 or parts[1] != "SKILL.md":
        return None
    return parts[0].strip() or None


def extract_knowledge_skill_reads(
    messages: Iterable[Any],
    *,
    skill_source: str = KNOWLEDGE_SKILL_SOURCE,
) -> list[str]:
    """Return ordered successful Skill names without exposing file contents."""
    message_list = list(messages or [])
    failed_read_ids = {
        str(getattr(message, "tool_call_id", "") or "")
        for message in message_list
        if getattr(message, "type", "") == "tool"
        and getattr(message, "status", None) == "error"
    }
    reads: list[str] = []
    for message in message_list:
        for tool_call in getattr(message, "tool_calls", None) or []:
            call_id, name, args = _tool_call_parts(tool_call)
            if name != "read_file" or call_id in failed_read_ids:
                continue
            skill_name = knowledge_skill_name_from_path(
                args.get("file_path") or args.get("path"),
                skill_source=skill_source,
            )
            if skill_name and skill_name not in reads:
                reads.append(skill_name)
    return reads


__all__ = [
    "extract_knowledge_skill_reads",
    "knowledge_skill_name_from_path",
]
