"""Visual consistency check for a ShoppingAgent multimodal discovery turn.

This module deliberately answers only one narrow question: whether the image
subject and the text's explicit shopping target are clearly incompatible.  It
does not route, retrieve products, create cards, or answer the user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field

from app.infrastructure.config import config
from app.infrastructure.retrieval.multimodal_embeddings import _normalize_image_url

logger = logging.getLogger("ai-service.shopping.multimodal_consistency")


class MultimodalConsistencyDecision(BaseModel):
    """The only semantic output allowed from the visual preflight."""

    decision: Literal["consistent", "conflict", "uncertain"]
    image_subject: str = Field(default="")
    text_target: str = Field(default="")
    reason: str = Field(default="")


class MultimodalConsistencyResult(MultimodalConsistencyDecision):
    """Decision plus safe operational observations for Tool traces."""

    model: str = ""
    fallback_used: bool = False
    duration_ms: int = 0


_CONSISTENCY_PROMPT = """你是电商导购系统中的图文商品目标一致性检查器。

你的唯一任务：根据一张参考图片和用户文字，判断图片中的主要商品主体与文字中明确想找的商品目标是否存在明显、确定的冲突。

判定规则：
- conflict：图片主体与文字商品目标都清楚，且是不同且互斥的商品目标。例如图片是跑鞋，文字要找降噪耳机。
- consistent：文字明确要找与图片同类或相似的商品；或文字只是补充预算、品牌、颜色、用途、功效、肤质、偏好等筛选条件。
- uncertain：图片不清、存在多个主体、文字没有明确商品目标、文字目标很宽泛，或无法可靠判断。不要把不确定当作冲突。
- 图片作为穿搭、场景或配件参考时，除非文字明确要求的商品目标与图片主体互斥，否则输出 uncertain，不输出 conflict。
- 不推荐商品，不解释常识，不判断价格或检索可行性，不执行路由。

只返回一个 JSON 对象，不要 Markdown、代码块或其他文字，格式如下：
{"decision":"consistent|conflict|uncertain","image_subject":"","text_target":"","reason":""}"""


# The DashScope SDK keeps endpoint settings in module globals.  Serialising
# this tiny native call prevents another SDK consumer from observing a partial
# base-url update while a request is in flight.
_DASHSCOPE_CALL_LOCK = threading.Lock()


def _fallback_result(*, reason: str, started: float) -> MultimodalConsistencyResult:
    return MultimodalConsistencyResult(
        decision="uncertain",
        reason=reason,
        model=config.SHOPPING_MULTIMODAL_CONSISTENCY_MODEL,
        fallback_used=True,
        duration_ms=int((perf_counter() - started) * 1000),
    )


def _call_dashscope_multimodal(*, query: str, image_url: str):
    """Call the official DashScope multimodal SDK synchronously.

    ``MultiModalConversation.call`` is a blocking SDK API, so the async caller
    below always executes this function in a worker thread.
    """
    import dashscope

    with _DASHSCOPE_CALL_LOCK:
        if config.DASHSCOPE_MAAS_BASE_URL:
            dashscope.base_http_api_url = config.DASHSCOPE_MAAS_BASE_URL
        return dashscope.MultiModalConversation.call(
            api_key=config.DASHSCOPE_API_KEY,
            model=config.SHOPPING_MULTIMODAL_CONSISTENCY_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"image": image_url},
                    {"text": _CONSISTENCY_PROMPT + "\n\n用户文字：" + str(query or "").strip()},
                ],
            }],
        )


def _dashscope_response_text(response) -> str:
    """Extract native SDK content and surface provider errors as exceptions."""
    status_code = getattr(response, "status_code", None)
    if status_code is not None and int(status_code) != 200:
        code = getattr(response, "code", "DASHSCOPE_ERROR")
        message = getattr(response, "message", "DashScope 多模态调用失败")
        raise RuntimeError(f"{code}: {message}")
    content = response.output.choices[0].message.content
    if isinstance(content, list):
        text_parts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        return "\n".join(text_parts).strip()
    return str(content or "").strip()


def _parse_decision(text: str) -> MultimodalConsistencyDecision:
    """Accept the documented JSON response and defensively unwrap code fences."""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    return MultimodalConsistencyDecision.model_validate(json.loads(cleaned))


async def assess_multimodal_consistency(
    *,
    query: str,
    image_url: str,
    run_config=None,
    caller=None,
) -> MultimodalConsistencyResult:
    """Assess one already-routed image+text product-discovery request.

    Any unavailable model, malformed image URL, upstream failure, or timeout is
    deliberately a non-terminal ``uncertain`` result.  A visual preflight must
    never make a user request hang or remove its normal retrieval fallback.
    """
    started = perf_counter()
    if not config.SHOPPING_MULTIMODAL_CONSISTENCY_ENABLED:
        return _fallback_result(reason="图文一致性检查未启用", started=started)

    normalized_url = _normalize_image_url(image_url)
    if not normalized_url:
        return _fallback_result(reason="没有可用于图文一致性检查的图片", started=started)

    if not config.DASHSCOPE_API_KEY or not config.SHOPPING_MULTIMODAL_CONSISTENCY_MODEL:
        return _fallback_result(reason="图文一致性模型未配置", started=started)

    try:
        del run_config  # Native SDK calls are observed through the Tool trace.
        response = await asyncio.wait_for(
            asyncio.to_thread(
                caller or _call_dashscope_multimodal,
                query=str(query or ""),
                image_url=normalized_url,
            ),
            timeout=max(0.1, config.SHOPPING_MULTIMODAL_CONSISTENCY_TIMEOUT_SECONDS),
        )
        decision = _parse_decision(_dashscope_response_text(response))
    except Exception as exc:  # noqa: BLE001
        logger.warning("multimodal consistency check unavailable: %s", exc, exc_info=True)
        return _fallback_result(reason="图文一致性检查暂不可用", started=started)

    # A conflict without two reliable labels cannot render a safe clarification;
    # downgrade it rather than fabricating what the image or text refers to.
    if decision.decision == "conflict" and (
        not decision.image_subject.strip() or not decision.text_target.strip()
    ):
        decision = MultimodalConsistencyDecision(
            decision="uncertain",
            reason="图文目标标注不完整，无法可靠发起澄清",
        )

    return MultimodalConsistencyResult(
        **decision.model_dump(),
        model=config.SHOPPING_MULTIMODAL_CONSISTENCY_MODEL,
        fallback_used=False,
        duration_ms=int((perf_counter() - started) * 1000),
    )


def build_multimodal_conflict_question(result: MultimodalConsistencyResult) -> str:
    """Render the sole user-visible clarification for a verified conflict."""
    return (
        f"图片看起来是{result.image_subject.strip()}，"
        f"但你文字中想找的是{result.text_target.strip()}。"
        f"请确认是按图片找相似{result.image_subject.strip()}，"
        f"还是按文字找{result.text_target.strip()}？"
    )


__all__ = [
    "MultimodalConsistencyDecision",
    "MultimodalConsistencyResult",
    "assess_multimodal_consistency",
    "build_multimodal_conflict_question",
]
