from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.api.response_adapter import build_error_response, normalize_ai_response
from app.api.schemas import (
    AIResponse,
    ChatRequest,
    RollingSummaryRequest,
    RollingSummaryResponse,
)
from app.application.assistant.conversation_summary import build_rolling_summary
from app.application.assistant.graph import AssistantGraph
from app.infrastructure.errors import ErrorCode
from app.infrastructure.llm.llm import get_llm
from app.infrastructure.retrieval.multimodal_embeddings import MultimodalImageError, _normalize_image_url


router = APIRouter(prefix="/api/assistant", tags=["assistant"])
logger = logging.getLogger("ai-service.assistant")

# 多模态接口 HEAD 预检超时（秒）。图片放在自己 CDN 上，正常 100-300ms 内响应。
# 超过 3 秒当作不可达处理，避免拖慢用户请求。
_IMAGE_HEAD_TIMEOUT = 3.0


class AssistantRunRequest(ChatRequest):
    # 购物车写操作已交给前端，这些字段保留兼容旧调用方，不再被 graph 消费。
    confirmed: bool = Field(False, description="[deprecated] 购物车操作改由前端直接处理")
    cart_action: Optional[str] = Field(None, description="[deprecated] 不再由 Agent 处理")
    product_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    sku_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    cart_item_id: Optional[int] = Field(None, description="[deprecated] 不再由 Agent 处理")
    quantity: int = Field(1, ge=1, description="[deprecated] 不再由 Agent 处理")


@router.post("/conversation-summary", response_model=RollingSummaryResponse)
async def create_conversation_summary(request: RollingSummaryRequest) -> RollingSummaryResponse:
    """Internal best-effort endpoint used by chat-service after a turn is saved."""
    llm = get_llm()
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM is not configured")
    try:
        summary = await build_rolling_summary(
            llm,
            previous_summary=request.previous_summary,
            messages=request.messages,
            max_chars=request.max_chars,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("rolling summary generation failed")
        raise HTTPException(status_code=502, detail="rolling summary generation failed") from exc
    if not summary:
        raise HTTPException(status_code=502, detail="rolling summary generation returned empty text")
    return RollingSummaryResponse(summary=summary)


def _parse_user_id(value: Optional[str]) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _raise_multimodal_image_error(trace_id: str, error: MultimodalImageError) -> None:
    logger.warning("trace=%s DashScope rejected image: %s", trace_id, error)
    raise HTTPException(
        status_code=400,
        detail={
            "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
            "message": f"图片无法识别：{error.reason}",
        },
    )


@router.post("/run", response_model=AIResponse)
async def run_assistant(request: AssistantRunRequest, http_request: Request) -> AIResponse:
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())
    image_url = None
    if request.image_url:
        image_url = _validate_image_url(request.image_url)
        await _precheck_image_reachable(image_url, trace_id)

    llm = get_llm()
    # trace_id is assigned before optional image validation so errors retain it.
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
            gender=request.gender,
            skin_type=request.skin_type,
            preference_tags=request.preference_tags,
            conversation_history=request.conversation_history,
            conversation_summary=request.conversation_summary,
            trace_id=trace_id,
            image_url=image_url,
        )
    except MultimodalImageError as e:
        _raise_multimodal_image_error(trace_id, e)
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

    事件类型：start / route / orchestrator_plan / orchestrator_subtask /
    subtask_result / token / tool_call / tool_result / final / error / done。
    详见 assistant/graph.py::astream。

    客户端断开检测：每次 yield 前用 Starlette 自带的 `request.is_disconnected()`
    嗅探一次,提前终止 graph.astream,避免 LLM 继续空转烧 token。
    不影响 chat-service 的 doOnCancel 落库语义,仅作为成本侧优化。

    前端使用示例：
        const es = new EventSource('/api/assistant/stream', ...)
        es.addEventListener('token', e => append(JSON.parse(e.data).content))
        es.addEventListener('final', e => renderCards(JSON.parse(e.data).product_cards))
        es.addEventListener('done', () => es.close())
    """
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())
    image_url = None
    if request.image_url:
        image_url = _validate_image_url(request.image_url)
        await _precheck_image_reachable(image_url, trace_id)

    llm = get_llm()

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
                gender=request.gender,
                skin_type=request.skin_type,
                preference_tags=request.preference_tags,
                conversation_history=request.conversation_history,
                conversation_summary=request.conversation_summary,
                trace_id=trace_id,
                image_url=image_url,
            ):
                # 客户端断开后提前停 LLM,避免空跑 token
                if await http_request.is_disconnected():
                    logger.info(
                        "client disconnected, abort astream trace=%s conv=%s",
                        trace_id, request.conversation_id,
                    )
                    break
                yield _sse_frame(event["type"], event.get("data") or {}).encode("utf-8")
        except MultimodalImageError as e:
            logger.warning("trace=%s DashScope rejected image: %s", trace_id, e)
            yield _sse_frame("error", {
                "trace_id": trace_id,
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": f"图片无法识别：{e.reason}",
            }).encode("utf-8")
            yield _sse_frame("done", {}).encode("utf-8")
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


# ─────────────────────────────────────────────────────────────
# 多模态接口（图文混合）
# ─────────────────────────────────────────────────────────────
# 相较文本接口的唯一差异：request 里可带 image_url（单张 OSS 图片 URL）。
# - 有 image_url + shopping 意图 → shopping_node 走 search_multimodal_v1
#   （三路 + qwen3-vl-rerank）
# - 复合请求由 Orchestrator 把图片收敛到 use_image=true 的 shopping 子任务；
#   knowledge/chitchat 子任务不会继承全局图片。知识任务如需图片检索产物，
#   通过 depends_on 接收前置 shopping 的结构化商品结果。
# - 无 image_url → 完全等价于 /run 或 /stream，走原文本链路

class MultimodalAssistantRunRequest(AssistantRunRequest):
    """带图版本 AssistantRunRequest。

    - image_url 必填（多模态接口的意义就是要有图）
    - question 覆盖为可选（纯图搜商品场景：用户只传图不打字）
    """
    image_url: str = Field(..., description="Single reference image URL (OSS)")
    # 覆盖父类的必填 question：纯图搜索时用户可能只传图。
    question: str = Field("", description="User input text (可选，纯图搜索时可为空)")


def _validate_image_url(image_url: Optional[str]) -> str:
    """校验图片 URL 非空 + 归一化。真正的可达性检查走 _precheck_image_reachable。"""
    if not image_url or not str(image_url).strip():
        raise HTTPException(
            status_code=400,
            detail="image_url is required for multimodal endpoints",
        )
    return str(image_url).strip()


async def _precheck_image_reachable(image_url: str, trace_id: str) -> None:
    """HEAD 预检图片是否可访问。不可访问直接抛 HTTPException 400。

    第一道防线：本地一次 HEAD 请求（100-300ms）能拦截 90% 的坏图（URL 拼错、
    图被删、域名不对）。DashScope 那道兜底再拦异常图（格式非法、被 CDN 拒绝
    识别）。

    - 相对路径会先走 _normalize_image_url 拼 IMAGE_BASE_URL 再 HEAD；
    - 归一化后仍无绝对 URL（比如 IMAGE_BASE_URL 未配 + 用户传相对路径）→ 400；
    - 少数 CDN 不支持 HEAD 只支持 GET，容错：非 200/405 才判失败。
      405 Method Not Allowed 说明服务器认识资源但拒绝 HEAD，视作可达；
    - 网络超时 / 连接失败 → 400，让用户知道图片不可达而不是"AI 出错"。
    """
    normalized = _normalize_image_url(image_url)
    if not normalized or not normalized.lower().startswith(("http://", "https://")):
        logger.warning(
            "trace=%s image_url 未能拼成绝对 URL: raw=%r normalized=%r",
            trace_id, image_url, normalized,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": "图片地址无效（无法拼成绝对 URL）",
            },
        )

    try:
        async with httpx.AsyncClient(timeout=_IMAGE_HEAD_TIMEOUT, follow_redirects=True) as client:
            resp = await client.head(normalized)
    except httpx.TimeoutException:
        logger.warning("trace=%s image HEAD 超时: %s", trace_id, normalized)
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": "图片地址访问超时，请检查后重试",
            },
        )
    except httpx.HTTPError as e:
        logger.warning("trace=%s image HEAD 失败: %s (%s)", trace_id, normalized, e)
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": f"图片地址无法访问：{e}",
            },
        )

    # 200 = 可达；405 = 服务器拒 HEAD 但资源存在（少数 CDN），继续放行让 DashScope 兜底；
    # 其他一律判失败。
    if resp.status_code == 200:
        return
    if resp.status_code == 405:
        logger.debug("trace=%s image HEAD 返回 405，放行让 DashScope 兜底: %s",
                     trace_id, normalized)
        return

    logger.warning("trace=%s image HEAD %d: %s", trace_id, resp.status_code, normalized)
    raise HTTPException(
        status_code=400,
        detail={
            "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
            "message": f"图片地址不可访问（HTTP {resp.status_code}）",
        },
    )


@router.post("/multimodal/run", response_model=AIResponse)
async def run_multimodal_assistant(
    request: MultimodalAssistantRunRequest,
    http_request: Request,
) -> AIResponse:
    """多模态非流式：图 + 文 → 一次性 AIResponse（含 product_cards）。

    Apifox 测试更简单：请求发出后一次返回商品卡片列表和推荐话术。

    图片校验两道防线：
    - HEAD 预检（本地 100-300ms）：拦 URL 拼错 / 图删了 / 域名错
    - DashScope MultimodalImageError（图片格式非法、拒绝识别）
    任一失败都返回 HTTP 400 + error_code=AI_MULTIMODAL_IMAGE_INVALID
    """
    # Compatibility alias.  The primary /run endpoint now accepts an optional
    # image_url and owns validation, graph invocation, and error semantics.
    return await run_assistant(request, http_request)

    image_url = _validate_image_url(request.image_url)

    llm = get_llm()
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())

    # 第一道防线：HEAD 预检，失败直接抛 HTTPException 400（不进 graph）
    await _precheck_image_reachable(image_url, trace_id)

    if llm is None:
        return build_error_response(
            "LLM 未配置，多模态 Agent 暂不可用。",
            trace_id=trace_id,
            error_code=ErrorCode.LLM_NOT_CONFIGURED,
            task_type="unknown",
            answer="当前 AI 服务还没有配置模型，无法运行多模态 Agent。",
        )

    graph = AssistantGraph(llm)
    try:
        result = await graph.run(
            question=request.question,
            context=request.context,
            conversation_id=request.conversation_id,
            user_id=_parse_user_id(request.user_id),
            jwt_token=request.jwt_token,
            gender=request.gender,
            skin_type=request.skin_type,
            preference_tags=request.preference_tags,
            trace_id=trace_id,
            image_url=image_url,
            conversation_history=request.conversation_history,
            conversation_summary=request.conversation_summary,
        )
    except MultimodalImageError as e:
        # 第二道防线：HEAD 通过但 DashScope 拒识别（图片格式非法 / CDN 拒绝
        # 二次访问 / 图被识别成禁用内容）
        logger.warning("trace=%s DashScope 拒识别: %s", trace_id, e)
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": f"图片无法识别：{e.reason}",
            },
        )
    except Exception:
        logger.exception("Multimodal assistant run failed")
        return build_error_response(
            "多模态 Agent 处理失败。",
            trace_id=trace_id,
            error_code=ErrorCode.ASSISTANT_ERROR,
            task_type="unknown",
            answer="多模态 Agent 暂时不可用，请稍后再试。",
        )
    return normalize_ai_response(result, trace_id=result.get("trace_id") or trace_id)


@router.post("/multimodal/stream")
async def stream_multimodal_assistant(
    request: MultimodalAssistantRunRequest,
    http_request: Request,
):
    """多模态流式：图 + 文 → SSE 事件流。

    事件类型与 /stream 一致（start/route/token/tool_call/tool_result/final/
    error/done）。图搜的推荐话术会通过 token 事件流式吐出。

    图片校验策略跟 /multimodal/run 一致：
    - HEAD 预检在开流前完成，失败 HTTP 400（不发一帧 SSE）
    - 开流后 DashScope 拒识别 → 发 error 事件（error_code=IMAGE_INVALID）
      再 done，SSE 语义完整
    """
    # Compatibility alias.  New callers use /stream with an optional image_url.
    return await stream_assistant(request, http_request)

    image_url = _validate_image_url(request.image_url)

    llm = get_llm()
    trace_id = getattr(http_request.state, "trace_id", None) or str(uuid4())

    # 开流前预检失败，直接 HTTP 400（不进 StreamingResponse，让前端能 catch）
    await _precheck_image_reachable(image_url, trace_id)

    async def event_stream() -> AsyncIterator[bytes]:
        if llm is None:
            yield _sse_frame("error", {
                "trace_id": trace_id,
                "error_code": ErrorCode.LLM_NOT_CONFIGURED,
                "message": "当前 AI 服务还没有配置模型，无法运行多模态 Agent。",
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
                gender=request.gender,
                skin_type=request.skin_type,
                preference_tags=request.preference_tags,
                trace_id=trace_id,
                image_url=image_url,
                conversation_history=request.conversation_history,
                conversation_summary=request.conversation_summary,
            ):
                if await http_request.is_disconnected():
                    logger.info(
                        "client disconnected, abort multimodal astream trace=%s conv=%s",
                        trace_id, request.conversation_id,
                    )
                    break
                yield _sse_frame(event["type"], event.get("data") or {}).encode("utf-8")
        except MultimodalImageError as e:
            logger.warning("trace=%s DashScope 拒识别（流式）: %s", trace_id, e)
            yield _sse_frame("error", {
                "trace_id": trace_id,
                "error_code": ErrorCode.MULTIMODAL_IMAGE_INVALID,
                "message": f"图片无法识别：{e.reason}",
            }).encode("utf-8")
            yield _sse_frame("done", {}).encode("utf-8")
        except Exception as e:  # noqa: BLE001
            logger.exception("Multimodal assistant stream failed")
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
            "X-Accel-Buffering": "no",
            "X-Trace-Id": trace_id,
        },
    )
