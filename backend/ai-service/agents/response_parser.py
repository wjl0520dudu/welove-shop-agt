from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from langchain_core.messages import AIMessage, ToolMessage

from api.response_adapter import model_to_dict
from agents.schemas import AgentFinalResponse


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _messages(state: Dict[str, Any]) -> list[Any]:
    messages = state.get("messages") or []
    return list(messages) if isinstance(messages, Iterable) else []


def _last_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return str(message.content or "")
        if getattr(message, "type", None) == "ai":
            return str(getattr(message, "content", "") or "")
    return ""


def _merge_tool_payloads(messages: list[Any]) -> dict:
    """从 ToolMessage 内容里合并检索/工具相关字段（已移除 cart 相关字段）。"""
    merged: dict = {"tool_calls": []}
    for message in messages:
        if not isinstance(message, ToolMessage) and getattr(message, "type", None) != "tool":
            continue
        payload = _json_dict(getattr(message, "content", ""))
        if not payload:
            continue
        for key in ("product_cards", "sources", "error", "error_code", "message", "task_type", "answer"):
            if payload.get(key) not in (None, [], ""):
                merged[key] = payload[key]
        if payload.get("tool_call"):
            merged["tool_calls"].append(payload["tool_call"])
        if payload.get("tool_calls"):
            merged["tool_calls"].extend(payload["tool_calls"])
    return merged


def agent_state_to_result(state: Dict[str, Any], default_task_type: str = "unknown") -> dict:
    """从 create_agent 的 messages/structured_response 拼出 result dict。"""
    structured = state.get("structured_response")
    if structured is not None:
        result = model_to_dict(structured)
    else:
        messages = _messages(state)
        result = _merge_tool_payloads(messages)
        result.setdefault("answer", _last_ai_text(messages))
        result.setdefault("task_type", default_task_type)

    result.setdefault("answer", "")
    result.setdefault("task_type", default_task_type)
    result.setdefault("tool_calls", [])
    return result


def error_result(message: str, error_code: str, task_type: str = "unknown") -> dict:
    return model_to_dict(AgentFinalResponse(answer=message, task_type=task_type, error=True, error_code=error_code, message=message))
