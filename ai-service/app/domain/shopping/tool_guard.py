"""Execution guard for ShoppingAgent high-level tools.

The guard is deliberately *not* an intent classifier.  The ShoppingAgent LLM
still decides which high-level capability to use.  This middleware only owns
execution invariants that the model cannot safely guarantee by itself:

* one primary shopping capability per agent run;
* Compare/Detail may only use Router-bound product ids;
* a successful identical tool call is reused within the same run;
* every execution has a compact, privacy-safe trace record.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.domain.shopping.deep_agent_runtime import SHOPPING_SKILL_SOURCE
from app.domain.shopping.script_runner import SHOPPING_SCRIPT_TOOL_NAME
from app.domain.shopping.skill_observability import shopping_skill_name_from_path


_PRIMARY_CAPABILITIES = {
    "recommend_products": "recommend",
    "compare_products": "compare",
    "answer_product_detail": "detail",
}

_SHOPPING_FACT_TOOLS = frozenset({
    *_PRIMARY_CAPABILITIES,
    "get_user_shopping_context",
})

SHOPPING_TOOL_SKILL_REQUIREMENTS = {
    "recommend_products": "discover-products",
    "compare_products": "compare-products",
    "answer_product_detail": "inspect-product",
    "get_user_shopping_context": "use-shopping-profile",
}


class RequireInitialShoppingToolMiddleware(AgentMiddleware):
    """Require the first ShoppingAgent model turn to choose a high-level tool.

    This is an execution contract, not an intent classifier: the LLM still
    chooses *which* of the high-level tools to call.  It only prevents a model
    from fabricating a recommendation, comparison, or detail answer before any
    real product result exists.  Once a tool result is present, normal natural
    language answer generation is allowed again.
    """

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        has_tool_result = any(
            isinstance(message, ToolMessage)
            and str(getattr(message, "name", "") or "") in _SHOPPING_FACT_TOOLS
            and getattr(message, "status", None) != "error"
            for message in (request.messages or [])
        )
        if not has_tool_result:
            return await handler(request.override(tool_choice="required"))
        return await handler(request)


def _normalise_ids(value: Any) -> list[int]:
    ids: list[int] = []
    for raw in value or []:
        try:
            product_id = int(raw)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in ids:
            ids.append(product_id)
    return ids


def _image_fingerprint(value: Any) -> str | None:
    image_url = str(value or "").strip()
    if not image_url:
        return None
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]


def _result_is_error(result: ToolMessage | Command[Any]) -> bool:
    return isinstance(result, ToolMessage) and getattr(result, "status", None) == "error"


def _tool_result_status(result: ToolMessage | Command[Any]) -> str:
    """Expose a useful high-level result state without trusting model text."""
    if _result_is_error(result):
        return "error"
    if not isinstance(result, ToolMessage):
        return "success"
    try:
        payload = json.loads(str(result.content or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return "success"
    action = str(payload.get("action") or "") if isinstance(payload, dict) else ""
    return action if action in {"clarify", "empty"} else "success"


class RequireMatchingShoppingSkillMiddleware(AgentMiddleware):
    """Require the Skill matching the model-selected Shopping tool.

    This middleware never interprets the user's language and never chooses a
    capability. The LLM remains responsible for selecting a Skill and a high-
    level business tool. Code only verifies the declared capability contract
    immediately before execution.
    """

    def __init__(self, *, skill_source: str = SHOPPING_SKILL_SOURCE) -> None:
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
        call_id = str(tool_call.get("id") or "shopping-skill-contract")

        if tool_name == "read_file":
            result = await handler(request)
            if not _result_is_error(result):
                skill_name = shopping_skill_name_from_path(
                    args.get("file_path") or args.get("path"),
                    skill_source=self._skill_source,
                )
                if skill_name and skill_name not in self.read_skills:
                    self.read_skills.append(skill_name)
            return result

        required_skill = SHOPPING_TOOL_SKILL_REQUIREMENTS.get(tool_name)
        if tool_name == SHOPPING_SCRIPT_TOOL_NAME:
            required_skill = str(args.get("skill_name") or "").strip() or None
        if required_skill is None or required_skill in self.read_skills:
            return await handler(request)

        required_path = f"{self._skill_source}{required_skill}/SKILL.md"
        self.records.append({
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "required_skill": required_skill,
            "loaded_skills": list(self.read_skills),
            "status": "blocked",
            "error_code": "SHOPPING_SKILL_REQUIRED",
        })
        payload = {
            "error": True,
            "error_code": "SHOPPING_SKILL_REQUIRED",
            "required_skill": required_skill,
            "message": (
                f"调用 {tool_name} 前必须先使用 read_file 读取 "
                f"{required_path}，遵循其中流程后再重试。"
            ),
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id=call_id,
            name=tool_name,
            status="error",
        )


class ShoppingToolGuardMiddleware(AgentMiddleware):
    """Request-local guard for the four ShoppingAgent high-level tools.

    A ShoppingAgent is built per request, so middleware instance fields are
    naturally request-scoped.  Nothing here is shared across users, turns or
    conversations.
    """

    def __init__(self) -> None:
        super().__init__()
        self._completed: dict[str, ToolMessage] = {}
        self._primary_capability: str | None = None
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
        state = dict(request.state or {})
        call_id = str(tool_call.get("id") or "shopping-tool-call")
        capability = _PRIMARY_CAPABILITIES.get(tool_name)

        # Deep Agents adds read_file for progressive Skill loading.  It is an
        # internal runtime operation, not a Shopping capability, so it must not
        # affect business call deduplication or appear in Shopping tool traces.
        if tool_name not in _SHOPPING_FACT_TOOLS:
            return await handler(request)

        bound_ids = _normalise_ids(state.get("selected_product_ids"))

        invalid_reason = self._validate_bound_ids(
            tool_name=tool_name,
            args=args,
            bound_ids=bound_ids,
        )
        if invalid_reason:
            return self._blocked_message(
                tool_name=tool_name,
                call_id=call_id,
                capability=capability,
                bound_ids=bound_ids,
                input_mode=str(state.get("input_mode") or "text"),
                reason=invalid_reason,
                status="blocked",
            )

        if capability and self._primary_capability and capability != self._primary_capability:
            return self._blocked_message(
                tool_name=tool_name,
                call_id=call_id,
                capability=capability,
                bound_ids=bound_ids,
                input_mode=str(state.get("input_mode") or "text"),
                reason="本轮已经完成另一项商品任务，请直接依据已有工具结果回复用户。",
                status="limited",
            )

        signature = self._signature(
            tool_name=tool_name,
            args=args,
            bound_ids=bound_ids,
            input_mode=str(state.get("input_mode") or "text"),
            image_fingerprint=_image_fingerprint(state.get("image_url")),
        )
        cached = self._completed.get(signature)
        if cached is not None:
            self.records.append({
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "capability": capability,
                "dispatch_source": "agent_tool_loop",
                "args_hash": signature,
                "input_mode": str(state.get("input_mode") or "text"),
                "status": "deduplicated",
                "duration_ms": 0,
                "deduplicated": True,
                "fallback_stage": None,
                "error_code": None,
            })
            return ToolMessage(
                content=cached.content,
                tool_call_id=call_id,
                name=tool_name,
                status="success",
            )

        started = time.perf_counter()
        try:
            result = await handler(request)
        except Exception:
            self.records.append({
                "tool_call_id": call_id,
                "tool_name": tool_name,
                "capability": capability,
                "dispatch_source": "agent_tool_loop",
                "args_hash": signature,
                "input_mode": str(state.get("input_mode") or "text"),
                "status": "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "deduplicated": False,
                "fallback_stage": None,
                "error_code": "TOOL_EXCEPTION",
            })
            raise

        status = _tool_result_status(result)
        self.records.append({
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "capability": capability,
            "dispatch_source": "agent_tool_loop",
            "args_hash": signature,
            "input_mode": str(state.get("input_mode") or "text"),
            "status": status,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "deduplicated": False,
            "fallback_stage": None,
            "error_code": None if status == "success" else "TOOL_ERROR",
        })
        if capability and status in {"success", "clarify", "empty"}:
            self._primary_capability = capability
        if isinstance(result, ToolMessage) and status in {"success", "clarify", "empty"}:
            self._completed[signature] = result
        return result

    @staticmethod
    def _validate_bound_ids(
        *,
        tool_name: str,
        args: dict[str, Any],
        bound_ids: list[int],
    ) -> str | None:
        if tool_name == "compare_products":
            requested = _normalise_ids(args.get("product_ids"))
            if not bound_ids:
                return "我还不确定要比较哪些商品，请说明商品名或序号。"
            if requested and any(product_id not in bound_ids for product_id in requested):
                return "本轮只能比较已确认的商品，请重新说明要比较的商品。"
            if len(requested or bound_ids) < 2:
                return "至少需要两件已确认商品才能比较。"
        if tool_name == "answer_product_detail":
            raw_product_id = args.get("product_id")
            requested = _normalise_ids([raw_product_id]) if raw_product_id is not None else []
            if not bound_ids:
                return "我还不确定你要了解哪件商品，请说明商品名或序号。"
            if requested and requested[0] not in bound_ids:
                return "本轮只能查询已确认的商品，请重新说明要了解的商品。"
            if not requested and len(bound_ids) != 1:
                return "你想了解哪一件商品？请明确商品名或序号。"
        return None

    def _blocked_message(
        self,
        *,
        tool_name: str,
        call_id: str,
        capability: str | None,
        bound_ids: list[int],
        input_mode: str,
        reason: str,
        status: str,
    ) -> ToolMessage:
        self.records.append({
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "capability": capability,
            "dispatch_source": "agent_tool_loop",
            "args_hash": None,
            "input_mode": input_mode,
            "status": status,
            "duration_ms": 0,
            "deduplicated": False,
            "fallback_stage": None,
            "error_code": "SHOPPING_TOOL_GUARD_BLOCKED",
        })
        payload = {
            "action": "clarify",
            "clarify_question": reason,
            "bound_product_ids": bound_ids,
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
            tool_call_id=call_id,
            name=tool_name,
            status="success",
        )

    @staticmethod
    def _signature(
        *,
        tool_name: str,
        args: dict[str, Any],
        bound_ids: list[int],
        input_mode: str,
        image_fingerprint: str | None,
    ) -> str:
        payload = {
            "tool_name": tool_name,
            "args": args,
            "bound_product_ids": bound_ids,
            "input_mode": input_mode,
            "image_fingerprint": image_fingerprint,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
