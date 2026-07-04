from __future__ import annotations

import logging
from typing import Literal, Optional
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
    confirmed: bool = Field(False, description="Whether user confirmed a write operation")
    cart_action: Optional[Literal["list", "count", "add", "remove", "update"]] = Field(
        None,
        description="Explicit cart action from caller",
    )
    product_id: Optional[int] = Field(None, description="Selected product ID")
    sku_id: Optional[int] = Field(None, description="Selected SKU ID")
    cart_item_id: Optional[int] = Field(None, description="Selected cart item ID")
    quantity: int = Field(1, ge=1, description="Quantity")


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
            confirmed=request.confirmed,
            cart_action=request.cart_action,
            product_id=request.product_id,
            sku_id=request.sku_id,
            cart_item_id=request.cart_item_id,
            quantity=request.quantity,
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