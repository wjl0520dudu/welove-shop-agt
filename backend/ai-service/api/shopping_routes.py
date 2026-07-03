from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter

from api.response_adapter import build_error_response, normalize_ai_response
from api.schemas import AIResponse, ChatRequest
from core.llm import get_llm
from shopping.product_repository import ProductRepository
from shopping.recommender import ShoppingRecommender, shopping_state_to_result

router = APIRouter(prefix="/api/shopping", tags=["shopping"])
logger = logging.getLogger("ai-service.shopping")


def _parse_user_id(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/recommend", response_model=AIResponse)
async def recommend(request: ChatRequest) -> AIResponse:
    llm = get_llm()
    trace_id = str(uuid4())

    if llm is None:
        return build_error_response(
            "LLM 未配置，导购推荐暂不可用",
            trace_id=trace_id,
            error_code="AI_LLM_NOT_CONFIGURED",
            task_type="shopping",
            answer="当前导购服务还没有配置模型，暂时无法生成推荐。",
        )

    repository = ProductRepository()
    recommender = ShoppingRecommender(llm, repository)
    try:
        profile = {
            "username": request.username,
            "gender": request.gender,
            "skin_type": request.skin_type,
            "preference_tags": request.preference_tags or [],
        }
        state = await recommender.recommend(
            question=request.question,
            user_id=_parse_user_id(request.user_id),
            session_id=request.conversation_id,
            context=request.context,
            profile={key: value for key, value in profile.items() if value not in (None, "", [])},
        )
    except Exception:
        logger.exception("Shopping recommendation failed")
        return build_error_response(
            "导购推荐处理失败",
            trace_id=trace_id,
            error_code="AI_SHOPPING_ERROR",
            task_type="shopping",
            answer="导购推荐暂时不可用，请稍后再试。",
        )

    return normalize_ai_response(
        shopping_state_to_result(state),
        trace_id=trace_id,
    )
