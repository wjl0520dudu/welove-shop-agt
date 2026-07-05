from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter
from pydantic import Field

from api.response_adapter import build_error_response, normalize_ai_response
from api.schemas import AIResponse, ChatRequest
from assistant.graph import AssistantGraph
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
async def run_assistant(request: AssistantRunRequest) -> AIResponse:
    llm = get_llm()
    trace_id = str(uuid4())
    if llm is None:
        return build_error_response(
            "LLM 未配置，统一 Agent 暂不可用。",
            trace_id=trace_id,
            error_code="AI_LLM_NOT_CONFIGURED",
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
        )
    except Exception:
        logger.exception("Assistant agent run failed")
        return build_error_response(
            "AI Agent 处理失败。",
            trace_id=trace_id,
            error_code="AI_ASSISTANT_ERROR",
            task_type="unknown",
            answer="AI Agent 暂时不可用，请稍后再试。",
        )
    return normalize_ai_response(result, trace_id=result.get("trace_id") or trace_id)
