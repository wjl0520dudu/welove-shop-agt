"""Privacy-safe observability helpers for ShoppingAgent Skill reads."""

from __future__ import annotations

import json
from typing import Any, Iterable

from app.domain.shopping.deep_agent_runtime import SHOPPING_SKILL_SOURCE
from app.domain.shopping.script_runner import SHOPPING_SCRIPT_TOOL_NAME


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


def shopping_skill_name_from_path(
    raw_path: Any,
    *,
    skill_source: str = SHOPPING_SKILL_SOURCE,
) -> str | None:
    """Return a direct Shopping Skill name for an exact ``SKILL.md`` path."""
    source = f"/{str(skill_source).strip('/')}".replace("\\", "/")
    path = f"/{str(raw_path or '').strip('/')}".replace("\\", "/")
    if not path.startswith(f"{source}/") or not path.endswith("/SKILL.md"):
        return None
    relative = path[len(source) + 1 :]
    parts = relative.split("/")
    if len(parts) != 2 or parts[1] != "SKILL.md":
        return None
    return parts[0].strip() or None


def extract_shopping_skill_reads(
    messages: Iterable[Any],
    *,
    skill_source: str = SHOPPING_SKILL_SOURCE,
) -> list[str]:
    """Return ordered Skill names without exposing host paths or file data."""
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
            raw_path = args.get("file_path") or args.get("path") or ""
            skill_name = shopping_skill_name_from_path(
                raw_path,
                skill_source=skill_source,
            )
            if skill_name and skill_name not in reads:
                reads.append(skill_name)
    return reads


def extract_shopping_script_calls(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """Return privacy-safe controlled script traces without input/output data."""
    message_list = list(messages or [])
    results: dict[str, dict[str, Any]] = {}
    statuses: dict[str, str] = {}
    for message in message_list:
        if getattr(message, "type", "") != "tool":
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        statuses[call_id] = str(getattr(message, "status", "") or "")
        try:
            content = getattr(message, "content", "")
            payload = json.loads(content) if isinstance(content, str) else content
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        results[call_id] = payload if isinstance(payload, dict) else {}

    traces: list[dict[str, Any]] = []
    for message in message_list:
        for tool_call in getattr(message, "tool_calls", None) or []:
            call_id, name, args = _tool_call_parts(tool_call)
            if name != SHOPPING_SCRIPT_TOOL_NAME:
                continue
            result = results.get(call_id, {})
            error = statuses.get(call_id) == "error" or bool(result.get("error"))
            traces.append({
                "tool_call_id": call_id,
                "skill_name": str(result.get("skill_name") or args.get("skill_name") or ""),
                "script_name": str(result.get("script_name") or args.get("script_name") or ""),
                "status": "error" if error else "success",
                "duration_ms": result.get("duration_ms"),
                "error_code": result.get("error_code"),
            })
    return traces


__all__ = [
    "extract_shopping_script_calls",
    "extract_shopping_skill_reads",
    "shopping_skill_name_from_path",
]
