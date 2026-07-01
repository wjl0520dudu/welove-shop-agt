import json
from typing import Any, Dict, Iterable, List, Optional

from api.schemas import (
    AIResponse,
    AgentStepDTO,
    CartList,
    CartSelection,
    Source,
    ToolCallDTO,
)


def model_to_dict(model: Any) -> Dict[str, Any]:
    """Serialize Pydantic v1/v2 models and plain dicts consistently."""
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    if hasattr(model, "dict"):
        return model.dict(exclude_none=True)
    return dict(model)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_sources(value: Any) -> List[Dict[str, Any]]:
    sources = []
    for item in _as_list(value):
        if isinstance(item, Source):
            sources.append(model_to_dict(item))
        elif isinstance(item, dict):
            normalized = dict(item)
            if "doc" not in normalized and "doc_name" in normalized:
                normalized["doc"] = normalized.get("doc_name")
            sources.append(normalized)
    return sources


def _normalize_steps(value: Any) -> List[Dict[str, Any]]:
    steps = []
    for item in _as_list(value):
        if isinstance(item, AgentStepDTO):
            steps.append(model_to_dict(item))
        elif isinstance(item, dict):
            steps.append(item)
        elif hasattr(item, "step_id"):
            steps.append(
                {
                    "step_id": getattr(item, "step_id", None),
                    "step_type": getattr(getattr(item, "step_type", None), "value", getattr(item, "step_type", None)),
                    "step_name": getattr(item, "step_name", ""),
                    "status": getattr(getattr(item, "status", None), "value", getattr(item, "status", None)),
                    "input_data": getattr(item, "input_data", None),
                    "output_data": getattr(item, "output_data", None),
                    "error_message": getattr(item, "error_message", None),
                    "duration_ms": getattr(item, "duration_ms", None),
                    "tool_call_id": getattr(item, "tool_call_id", None),
                    "start_time": getattr(item, "start_time", None),
                    "end_time": getattr(item, "end_time", None),
                }
            )
    return steps


def _normalize_tool_calls(value: Any) -> List[Dict[str, Any]]:
    tool_calls = []
    for item in _as_list(value):
        if isinstance(item, ToolCallDTO):
            tool_calls.append(model_to_dict(item))
        elif isinstance(item, dict):
            tool_calls.append(item)
        elif hasattr(item, "tool_call_id"):
            tool_calls.append(
                {
                    "tool_call_id": getattr(item, "tool_call_id", None),
                    "tool_name": getattr(item, "tool_name", ""),
                    "input_params": getattr(item, "input_params", {}) or {},
                    "output": getattr(item, "output", {}) or {},
                    "status": getattr(item, "status", ""),
                    "duration_ms": getattr(item, "duration_ms", None),
                    "error_message": getattr(item, "error_message", None),
                    "timestamp": getattr(item, "timestamp", None),
                }
            )
    return tool_calls


def normalize_ai_response(
    result: Optional[Dict[str, Any]],
    run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: str = "completed",
) -> AIResponse:
    """Convert legacy Agent dicts into the stable API response contract."""
    result = result or {}
    sources = _normalize_sources(result.get("sources", []))
    cart_selection = result.get("cart_selection")
    cart_list = result.get("cart_list")

    if isinstance(cart_selection, dict) and cart_selection.get("type") == "cart_list" and not cart_list:
        cart_list = cart_selection
        cart_selection = None

    response = AIResponse(
        answer=result.get("answer", "") or "",
        sources=sources,
        task_type=result.get("task_type", "unknown") or "unknown",
        product_cards=result.get("product_cards") or [],
        confirm_card=result.get("confirm_card"),
        cart_selection=cart_selection,
        cart_list=cart_list,
        run_id=run_id or result.get("run_id"),
        trace_id=trace_id or result.get("trace_id"),
        status=status,
        error=bool(result.get("error", False)),
        error_code=result.get("error_code"),
        message=result.get("message"),
        has_sources=bool(result.get("has_sources", bool(sources))),
        steps=_normalize_steps(result.get("steps") or result.get("_steps")),
        tool_calls=_normalize_tool_calls(result.get("tool_calls")),
        intermediate_conclusions=result.get("intermediate_conclusions") or [],
    )
    return response


def build_error_response(
    message: str,
    run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    error_code: str = "AI_INTERNAL_ERROR",
    task_type: str = "unknown",
    answer: str = "",
) -> AIResponse:
    return AIResponse(
        answer=answer,
        sources=[],
        task_type=task_type,
        product_cards=[],
        run_id=run_id,
        trace_id=trace_id,
        status="failed",
        error=True,
        error_code=error_code,
        message=message,
        has_sources=False,
    )


def parse_stream_event(event_data: Any) -> Dict[str, Any]:
    """Parse legacy stream event data into a dict."""
    if isinstance(event_data, dict):
        return event_data
    if event_data is None:
        return {}
    raw = str(event_data).strip()
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if not raw:
        return {}
    return json.loads(raw)


def sse_event(event: Dict[str, Any]) -> str:
    """Format an event dict as a Server-Sent Event line."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def stream_start_event(run_id: str, trace_id: str) -> Dict[str, Any]:
    return {"type": "start", "run_id": run_id, "trace_id": trace_id}


def stream_error_event(
    message: str,
    run_id: Optional[str],
    trace_id: Optional[str],
    error_code: str = "AI_INTERNAL_ERROR",
) -> Dict[str, Any]:
    return {
        "type": "error",
        "error": True,
        "error_code": error_code,
        "message": message,
        "content": message,
        "run_id": run_id,
        "trace_id": trace_id,
    }


def _response_to_dict(response: AIResponse) -> Dict[str, Any]:
    """Serialize AIResponse keeping all contract keys (None -> null).

    model_to_dict 默认 exclude_none=True 会丢掉 confirm_card/cart_list 等
    null 字段，破坏 "Java 不需要猜字段" 的统一契约，因此结束事件单独用
    保留全部字段的序列化方式。
    """
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    return dict(response)


def stream_end_event(response: AIResponse) -> Dict[str, Any]:
    data = _response_to_dict(response)
    return {
        "type": "end",
        "content": response.answer,
        "task_type": response.task_type,
        "run_id": response.run_id,
        "trace_id": response.trace_id,
        "response": data,
    }

