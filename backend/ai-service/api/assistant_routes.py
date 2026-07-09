from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from api.response_adapter import build_error_response, normalize_ai_response
from api.schemas import AIResponse, ChatRequest
from assistant.graph import AssistantGraph
from core.errors import ErrorCode
from core.llm import get_llm


router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger("ai-service.assistant")


class AssistantRunRequest(ChatRequest):
    # 购物车写操作已交给前端，这些字段保留兼容旧调用方，不再被 graph 消费。
    confirmed: bool = Field(False, description="[deprecated] 购物车操作改由前端直接处理")
    cart_action: Optional[str] = Field(None, description="[deprecated] 不再由 Agent 处理")
    product_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    sku_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    cart_item_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    quantity: int = Field(1, ge=1, description="[deprecated] 不再由 Agent 处理")


def _parse_user_id(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/run", response_model=AIResponse)
async def run_assistant(request: AssistantRunRequest, http_request: Request) -> AIResponse:
    llm = get_llm()
    # 优先复用中间件生成/透传的 traceId；没有则新建（防御性，正常不会走到）
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())
    if llm is None:
        return build_error_response(
            "LLM 未配置，统一 Agent 暂不可用。",
            trace_id=trace_id,
            error_code=ErrorCode.LLM_NOT_CONFIGURED,
            task_type="unknown",
            answer="当前 AI 服务还没有配置模型，无法运行 Agent。",
        )

    graph = AssistantGraph(llm)
    try:
        result = await graph.run(
            question=request.question,
            context=request.context,
            conversation_id=request.conversation_id,
            user_id=_parse_user_id(request.user_id),
            jwt_token=request.jwt_token,
            trace_id=trace_id,
        )
    except Exception:
        logger.exception("Assistant agent run failed")
        return build_error_response(
            "AI Agent 处理失败。",
            trace_id=trace_id,
            error_code=ErrorCode.ASSISTANT_ERROR,
            task_type="unknown",
            answer="AI Agent 暂时不可用，请稍后再试。",
        )
    return normalize_ai_response(result, trace_id=result.get("trace_id") or trace_id)


def _sse_frame(event_type: str, data: dict) -> str:
    """把 (event_type, data) 编成 SSE 一帧（event/data 双字段 + 双换行）。

    符合 W3C SSE 规范：https://html.spec.whatwg.org/multipage/server-sent-events.html
    """
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/stream")
async def stream_assistant(request: AssistantRunRequest, http_request: Request):
    """流式版本 /run，返回 SSE 事件流。

    事件类型：start / route / token / tool_call / tool_result / final / error / done。
    详见 assistant/graph.py::astream。

    前端使用示例：
        const es = new EventSource('/api/assistant/stream', ...)
        es.addEventListener('token', e => append(JSON.parse(e.data).content))
        es.addEventListener('final', e => renderCards(JSON.parse(e.data).product_cards))
        es.addEventListener('done', () => es.close())
    """
    llm = get_llm()
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())

    async def event_stream() -> AsyncIterator[bytes]:
        if llm is None:
            yield _sse_frame("error", {
                "trace_id": trace_id,
                "error_code": ErrorCode.LLM_NOT_CONFIGURED,
                "message": "当前 AI 服务还没有配置模型，无法运行 Agent。",
            }).encode("utf-8")
            yield _sse_frame("done", {}).encode("utf-8")
            return

        graph = AssistantGraph(llm)
        try:
            async for event in graph.astream(
                question=request.question,
                context=request.context,
                conversation_id=request.conversation_id,
                user_id=_parse_user_id(request.user_id),
                jwt_token=request.jwt_token,
                trace_id=trace_id,
            ):
                yield _sse_frame(event["type"], event.get("data") or {}).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            logger.exception("Assistant stream failed")
            yield _sse_frame("error", {
                "trace_id": trace_id,
                "error_code": ErrorCode.ASSISTANT_ERROR,
                "message": str(e),
            }).encode("utf-8")
            yield _sse_frame("done", {}).encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx 反向代理时必须，防止代理缓冲整个流
            "X-Accel-Buffering": "no",
            # 让前端/Java 网关能拿到当前流的 traceId 做关联
            "X-Trace-Id": trace_id,
        },
    )
