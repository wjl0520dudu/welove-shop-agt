from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.domain.shopping.preferences import build_preference_questions
from app.prompts.prompts import SHOPPING_AGENT_PROMPT
from app.application.assistant.state import ShoppingAgentState
from app.infrastructure.errors import ErrorCode
from app.domain.shopping.capabilities import (
    CompareCapability,
    DetailCapability,
    RecommendCapability,
    UserShoppingContextCapability,
)
from app.domain.shopping.dispatcher import DispatchDecision, dispatch_shopping_capability
from app.domain.shopping.high_level_tools import SHOPPING_HIGH_LEVEL_TOOLS
from app.domain.shopping.schemas import ShoppingContext
from app.domain.shopping.tool_guard import (
    RequireInitialShoppingToolMiddleware,
    ShoppingToolGuardMiddleware,
)

# Phase 1a 关键变更：LLM 只面对 4 个高层 tool，底层 12 个工具全部退到 Capability 内部。
# 见 shopping/high_level_tools.py 和 shopping/capabilities/*。
_ALL_TOOLS = SHOPPING_HIGH_LEVEL_TOOLS

logger = logging.getLogger("ai-service.shopping.agent")

TokenSink = Callable[[str], None]

# ShoppingAgent 独立 checkpointer，跟主图/router/knowledge 隔离。
_shopping_checkpointer = InMemorySaver()


class ShoppingAgent:
    """导购 Agent —— Phase 1a 起使用高层 Capability Tool 模式。

    ## Phase 1a 变更（本 commit）
    - LLM 可见工具从 12 个 → 4 个高层 tool
    - product_cards 从 ToolMessage 抽取（不再无条件读 Store 兜底）
    - system_prompt 大幅精简（76 行控制指令 → 40 行工具描述）
    - 底层工具（search_products/get_product_detail/…）仍存在，但只作为
      Capability 内部函数被调用，不再挂给 LLM

    ## Phase 1b 计划（下个 commit）
    - shopping/retrieval.py 内部从 PgVectorStore 切到 ProductMilvusStore（三路 + rerank）
    - agent.py 零改动
    """

    def __init__(self, llm):
        self._llm = llm

    def _build_system_prompt(
        self,
        *,
        selected_product_ids: List[int],
        image_url: Optional[str],
        input_mode: str,
    ) -> str:
        """Build a bounded, turn-local prompt for the Shopping Tool Agent."""
        bound = ", ".join(str(product_id) for product_id in selected_product_ids) or "无"
        image_note = "有；仅 recommend_products 可以使用" if image_url else "无"
        return (
            SHOPPING_AGENT_PROMPT
            + "\n\n## 本轮 Router 已交付的执行边界\n"
            + f"- 已绑定商品 ID：{bound}\n"
            + f"- 图片：{image_note}\n"
            + f"- 推荐输入模式：{input_mode}\n"
            + "- 当前用户问题已经消除可解析的跨轮指代；不要再读取或猜测会话历史。"
        )

    def _build_messages(
        self, question: str, messages: List[Dict[str, Any]]
    ) -> list:
        """ShoppingAgent receives the canonical current turn, never raw history."""
        del messages
        return [HumanMessage(content=(question or "").strip() or "请根据当前商品需求提供帮助。")]

    async def run(
        self,
        *,
        question: str,
        messages: List[Dict[str, Any]],
        business_memory: Dict[str, Any],
        conversation_id: Optional[str] = None,
        user_id: Optional[int | str] = None,
        jwt_token: Optional[str] = None,
        selected_product_ids: Optional[List[int]] = None,
        image_url: Optional[str] = None,
        input_mode: str = "text",
        token_sink: Optional[TokenSink] = None,
    ) -> dict:
        """执行导购推荐。

        Returns:
            {"answer": str, "product_cards": [...], "task_type": "shopping",
             "sources": [], "tool_calls": [...], "error": bool}
        """
        if self._llm is None:
            return {
                "answer": "导购 Agent 暂不可用。",
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.LLM_NOT_CONFIGURED,
            }

        effective_memory = _minimal_business_memory(
            business_memory,
            selected_product_ids=selected_product_ids,
        )
        bound_product_ids = list(effective_memory.get("selected_product_ids") or [])
        normalised_input_mode = _normalise_input_mode(image_url, input_mode)
        guard = ShoppingToolGuardMiddleware()
        system_prompt = self._build_system_prompt(
            selected_product_ids=bound_product_ids,
            image_url=image_url,
            input_mode=normalised_input_mode,
        )

        # A new Agent instance makes its middleware cache request-scoped.  The
        # LLM decides the high-level capability; Guard/middleware only enforce
        # call boundaries and loop limits.
        agent = create_agent(
            model=self._llm,
            checkpointer=_shopping_checkpointer,
            system_prompt=system_prompt,
            tools=_ALL_TOOLS,
            state_schema=ShoppingAgentState,
            middleware=[
                # The LLM still selects the capability.  This only requires a
                # real high-level product result before it may answer.
                RequireInitialShoppingToolMiddleware(),
                guard,
                # A bounded global limit protects against malformed tool loops.
                # The Guard still owns same-argument result reuse.
                ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
                ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
            ],
        )

        agent_messages = self._build_messages(question, messages)

        try:
            # Most normal turns are select-tool → tool-result → answer.  Agent
            # middleware contributes graph steps too, so 8 can reject that
            # healthy three-step flow before its final model response.  The
            # tool/model middleware still provides the real loop bounds.
            result = await agent.ainvoke(
                {
                    "messages": agent_messages,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "jwt_token": jwt_token,
                    "business_memory": effective_memory,
                    "selected_product_ids": bound_product_ids,
                    "image_url": image_url or "",
                    "input_mode": normalised_input_mode,
                },
                config={
                    "configurable": {"thread_id": str(uuid4())},
                    "recursion_limit": 12,
                },
            )
        except Exception as e:
            logger.exception("ShoppingAgent ainvoke failed")
            fallback = await self._run_restricted_fallback(
                question=question,
                conversation_id=conversation_id,
                user_id=user_id,
                jwt_token=jwt_token,
                business_memory=effective_memory,
                token_sink=token_sink,
            )
            if fallback is not None:
                return fallback
            return {
                "answer": "导购 Agent 处理失败，请稍后再试。",
                "product_cards": [],
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": str(e),
                "dispatch_source": "none",
                "tool_calls": guard.records,
            }

        collected_tool_calls = _extract_tool_calls(
            result.get("messages", []), guard_records=guard.records,
        )

        # A Shopping answer without any high-level ToolResult is not grounded
        # in real product data.  Never surface a fabricated "I found these"
        # response with empty cards; tool_choice=required above normally
        # prevents this, and this is the provider-agnostic final backstop.
        if not collected_tool_calls:
            logger.warning("shopping agent completed without a high-level tool call")
            return {
                "answer": "我需要先查询商城的实时商品信息，但这次查询没有成功，请稍后再试。",
                "product_cards": [],
                "task_type": "shopping",
                "sources": [],
                "tool_calls": [],
                "suggested_questions": [],
                "capability": None,
                "dispatch_source": "none",
                "model_call_count": _count_model_calls(result.get("messages", [])),
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": "ShoppingAgent completed without a high-level ToolResult.",
            }

        # ★ Phase 1a 关键变更：product_cards 优先从最近一次 ToolMessage 抽取，
        # 而不是无条件读 Store —— 避免"对比/详情"轮次误带上一轮推荐卡片。
        # 只有 ToolMessage 里没有 product_cards（LLM 没调工具，纯闲聊）时才回读 Store。
        tool_result = _extract_high_level_tool_result(result.get("messages", []))
        if tool_result and "product_cards" in tool_result:
            product_cards = tool_result.get("product_cards") or []
        else:
            product_cards = []

        # answer 从最后一条 AI 消息 content 提取
        answer = ""
        for m in reversed(result.get("messages", [])):
            mtype = getattr(m, "type", "")
            if mtype == "ai":
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content
                    break

        suggested_questions = build_preference_questions(
            effective_memory.get("user_preferences") or {}
        )

        action_to_capability = {
            "recommend": "recommend",
            "compare": "compare",
            "detail": "detail",
            "clarify": "clarify",
        }
        capability = action_to_capability.get(str((tool_result or {}).get("action") or ""))
        dispatch_source = "agent_tool_loop" if collected_tool_calls else "none"

        return {
            "answer": answer or "暂时没能找到合适的商品，能再说详细一点吗？",
            "product_cards": product_cards,
            "task_type": "shopping",
            "sources": [],
            "tool_calls": collected_tool_calls,
            "suggested_questions": suggested_questions,
            "capability": capability,
            "dispatch_source": dispatch_source,
            "model_call_count": _count_model_calls(result.get("messages", [])),
            "error": False,
        }

    async def _run_dispatched_capability(
        self,
        *,
        decision: DispatchDecision,
        question: str,
        conversation_id: Optional[str],
        user_id: Optional[int | str],
        jwt_token: Optional[str],
        business_memory: Dict[str, Any],
        token_sink: Optional[TokenSink] = None,
        dispatch_source: str = "restricted_rule_fallback",
    ) -> dict:
        """Execute a capability only after the Agent path has failed."""
        if decision.capability == "transaction_unsupported":
            return {
                "answer": "当前导购助手支持商品推荐、对比和详情咨询；请在商品卡片或商品详情页完成加购、下单和支付。",
                "task_type": "shopping",
                "product_cards": [], "sources": [], "suggested_questions": [], "error": False,
                "capability": decision.capability,
                "dispatch_source": dispatch_source,
                "tool_calls": [_dispatch_trace(decision, question, status="unsupported", dispatch_source=dispatch_source)],
            }

        context = ShoppingContext(
            conversation_id=conversation_id, user_id=user_id, jwt_token=jwt_token,
            is_logged_in=bool(user_id), business_memory=business_memory,
            last_product_cards=list(business_memory.get("last_product_cards") or []),
            selected_product_ids=list(business_memory.get("selected_product_ids") or []),
            last_focused_product=business_memory.get("last_focused_product"),
            user_preferences=dict(business_memory.get("user_preferences") or {}),
        )
        if decision.capability == "recommend":
            payload = (await RecommendCapability().run(question, context)).model_dump()
        elif decision.capability == "compare":
            payload = (await CompareCapability().run(question, context)).model_dump()
        elif decision.capability == "detail":
            payload = (await DetailCapability().run(question, context)).model_dump()
        else:
            payload = await UserShoppingContextCapability().run(context)

        return {
            "answer": await _compose_capability_answer(
                self._llm, decision.capability, question, payload,
                token_sink=token_sink,
            ),
            "task_type": "shopping",
            "product_cards": payload.get("product_cards") or [],
            "sources": [],
            "tool_calls": [_dispatch_trace(decision, question, status="completed", dispatch_source=dispatch_source)],
            "suggested_questions": build_preference_questions(business_memory.get("user_preferences") or {}),
            "capability": decision.capability,
            "dispatch_source": dispatch_source,
            "error": bool(payload.get("error", False)),
            "error_code": payload.get("error_code"),
            "message": payload.get("message"),
        }

    async def _run_restricted_fallback(
        self,
        *,
        question: str,
        conversation_id: Optional[str],
        user_id: Optional[int | str],
        jwt_token: Optional[str],
        business_memory: Dict[str, Any],
        token_sink: Optional[TokenSink],
    ) -> Optional[dict]:
        """Use the legacy dispatcher only as an observable failure fallback.

        This path is intentionally never reached before ``create_agent``.  The
        dispatcher receives no historical cards/focused product, so it cannot
        reintroduce a second cross-turn reference resolver.
        """
        decision = dispatch_shopping_capability(question, business_memory)
        if decision is None:
            return None
        logger.warning(
            "shopping restricted rule fallback capability=%s reason=%s",
            decision.capability,
            decision.reason,
        )
        return await self._run_dispatched_capability(
            decision=decision,
            question=question,
            conversation_id=conversation_id,
            user_id=user_id,
            jwt_token=jwt_token,
            business_memory=business_memory,
            token_sink=token_sink,
            dispatch_source="restricted_rule_fallback",
        )


def _minimal_business_memory(
    business_memory: Optional[Dict[str, Any]],
    *,
    selected_product_ids: Optional[List[int]],
) -> Dict[str, Any]:
    """Keep only execution-safe fields for a ShoppingAgent turn.

    Historical cards and focused products remain available to Router/Preparation
    but are deliberately excluded here.  This prevents a lower capability from
    silently becoming another context resolver.
    """
    raw = dict(business_memory or {})
    bound = selected_product_ids
    if bound is None:
        bound = raw.get("selected_product_ids") or []
    normalised_ids: list[int] = []
    for value in bound:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in normalised_ids:
            normalised_ids.append(product_id)
    preferences = raw.get("user_preferences")
    return {
        "selected_product_ids": normalised_ids,
        "user_preferences": dict(preferences) if isinstance(preferences, dict) else {},
    }


def _normalise_input_mode(image_url: Optional[str], requested: str) -> str:
    if not image_url:
        return "text"
    return "image" if str(requested or "").lower() == "image" else "multimodal"


def _count_model_calls(messages: list) -> int:
    return sum(1 for message in messages or [] if getattr(message, "type", "") == "ai")


def _dispatch_trace(
    decision: DispatchDecision,
    question: str,
    *,
    status: str,
    dispatch_source: str,
) -> dict:
    tool_by_capability = {
        "recommend": "recommend_products", "compare": "compare_products",
        "detail": "answer_product_detail", "user_context": "get_user_shopping_context",
        "transaction_unsupported": "transaction_unsupported",
    }
    name = tool_by_capability[decision.capability]
    return {"tool_name": name, "name": name, "input_params": {"query": question},
            "args": {"query": question}, "status": status,
            "dispatch_source": dispatch_source, "dispatch_reason": decision.reason}


async def _compose_capability_answer(
    llm: Any,
    capability: str,
    question: str,
    payload: Dict[str, Any],
    *,
    token_sink: Optional[TokenSink] = None,
) -> str:
    """A grounded deterministic fallback; the capability owns all business facts."""
    if payload.get("clarify_question"):
        return str(payload["clarify_question"])
    if payload.get("empty_reason"):
        return str(payload["empty_reason"])
    if payload.get("error"):
        return str(payload.get("message") or "当前请求暂时无法处理，请稍后再试。")
    if capability == "recommend":
        cards = payload.get("product_cards") or []
        if not cards:
            return "暂时没有找到符合条件的商品，可以补充预算、品类或使用场景。"
        lines = ["为你找到以下商品："]
        for card in cards[:3]:
            price = card.get("price") or card.get("base_price")
            reason = card.get("reason") or "符合当前需求"
            lines.append(f"- {card.get('title', '商品')}（{price} 元）：{reason}")
        fallback = "\n".join(lines)
    elif capability == "compare":
        suggestion = payload.get("suggestion") or {}
        fallback = str(suggestion.get("reason") or "已完成商品对比，详情请查看下方商品卡片。")
    elif capability == "detail":
        facts = payload.get("facts") or {}
        fallback = "商品信息：" + json.dumps(facts, ensure_ascii=False, default=str)
    else:
        data = payload.get("data") or {}
        return str(payload.get("message") or ("已获取你的购物上下文。" if data else "暂未获取到购物上下文。"))

    # The Dispatcher already chose and executed the Capability. One bounded
    # rendering call restores answer quality without reopening tool selection.
    if llm is None:
        return fallback
    evidence = {
        "product_cards": (payload.get("product_cards") or [])[:3],
        "comparison_rows": (payload.get("comparison_rows") or [])[:5],
        "suggestion": payload.get("suggestion") or {},
        "facts": payload.get("facts") or {},
    }
    prompt = (
        "你是电商导购的表达层。只依据给定结构化事实回答用户，不得编造商品、"
        "价格、库存、成分或功效；不要调用工具；回答要直接覆盖用户问题。"
        "若事实无法验证某项偏好，要明确说明。\n"
        f"用户问题：{question}\n能力：{capability}\n事实："
        + json.dumps(evidence, ensure_ascii=False, default=str)
    )
    messages = [
        SystemMessage(content="你只能根据提供的事实生成自然、简洁的中文回答。"),
        HumanMessage(content=prompt),
    ]
    if token_sink is None:
        try:
            response = await llm.ainvoke(messages)
            answer = str(getattr(response, "content", "") or "").strip()
            return answer or fallback
        except Exception:  # noqa: BLE001
            logger.warning("dispatched capability answer rendering failed", exc_info=True)
            return fallback

    # This is the public SSE path: stream genuine provider chunks.  Do not wait
    # for ainvoke() and simulate a typewriter from the final string.
    chunks: list[str] = []
    try:
        async for chunk in llm.astream(messages):
            content = _stream_text_content(getattr(chunk, "content", ""))
            if not content:
                continue
            chunks.append(content)
            _emit_token(token_sink, content)
        answer = "".join(chunks).strip()
        return answer or fallback
    except Exception:  # noqa: BLE001
        logger.warning("dispatched capability answer streaming failed", exc_info=True)
        if not chunks:
            return fallback
        # Persist exactly what the user has already seen if a provider stream
        # breaks after emitting partial text.
        suffix = "\n\n抱歉，回复生成中断了；你可以再试一次。"
        _emit_token(token_sink, suffix)
        return "".join(chunks).strip() + suffix


def _stream_text_content(content: Any) -> str:
    """Extract user-visible text from a provider stream chunk."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part["text"])
            for part in content
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text")
        )
    return ""


def _emit_token(token_sink: TokenSink, content: str) -> None:
    try:
        token_sink(content)
    except Exception:  # noqa: BLE001
        # Client disconnection must not invalidate the completed business result.
        logger.debug("shopping token sink unavailable", exc_info=True)


def _extract_tool_calls(
    messages: list,
    *,
    guard_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """从 create_agent 的 result["messages"] 里抽取工具调用记录。"""
    records_by_id = {
        str(record.get("tool_call_id")): record
        for record in (guard_records or [])
        if record.get("tool_call_id")
    }
    out: List[Dict[str, Any]] = []
    for m in messages or []:
        tcs = getattr(m, "tool_calls", None)
        if not tcs:
            continue
        for tc in tcs:
            if isinstance(tc, dict):
                call_id = tc.get("id")
                name = tc.get("name") or ""
                args = tc.get("args") or tc.get("arguments") or {}
            else:
                call_id = getattr(tc, "id", None)
                name = getattr(tc, "name", "") or ""
                args = getattr(tc, "args", None) or getattr(tc, "arguments", None) or {}
            if not name:
                continue
            normalized_args = args if isinstance(args, dict) else {}
            trace = records_by_id.get(str(call_id), {})
            out.append({
                "tool_call_id": call_id,
                "tool_name": name,
                "input_params": normalized_args,
                "status": trace.get("status") or "invoked",
                "capability": trace.get("capability"),
                "dispatch_source": trace.get("dispatch_source") or "agent_tool_loop",
                "args_hash": trace.get("args_hash"),
                "input_mode": trace.get("input_mode"),
                "duration_ms": trace.get("duration_ms"),
                "deduplicated": bool(trace.get("deduplicated", False)),
                "fallback_stage": trace.get("fallback_stage"),
                "error_code": trace.get("error_code"),
                # Backward-compatible aliases used by existing scripts/tests.
                "name": name,
                "args": normalized_args,
            })
    # A middleware block can happen before the provider tool call is preserved
    # in the final message list.  Keep it observable instead of silently
    # dropping it from the trace.
    seen_ids = {str(item.get("tool_call_id")) for item in out}
    for record in guard_records or []:
        if str(record.get("tool_call_id")) not in seen_ids:
            out.append(dict(record))
    return out


def _extract_high_level_tool_result(messages: list) -> Dict[str, Any]:
    """从消息列表里倒序找到最近一次 **高层 Tool** 返回的 dict。

    高层 Tool 返回的 JSON 里必定含 `action`（recommend/clarify/empty/compare/detail），
    用这个字段过滤掉旧的底层工具残留（如果消息 buffer 里混着的话）。
    """
    high_level_actions = {
        "recommend", "clarify", "empty", "compare", "detail"
    }
    for m in reversed(messages or []):
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not content:
            continue
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("action") in high_level_actions:
            return data
    return {}
