from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.domain.shopping.preferences import build_preference_questions
from app.prompts.prompts import SHOPPING_AGENT_PROMPT
from app.application.assistant.state import ShoppingAgentState
from app.infrastructure.errors import ErrorCode
from app.infrastructure.persistence.memory import remember_pending_multimodal_choice
from app.domain.shopping.capabilities import (
    CompareCapability,
    DetailCapability,
    RecommendCapability,
    UserShoppingContextCapability,
)
from app.domain.shopping.dispatcher import DispatchDecision, dispatch_shopping_capability
from app.domain.shopping.high_level_tools import (
    SHOPPING_HIGH_LEVEL_TOOLS,
    SHOPPING_ROLLBACK_TOOLS,
    shopping_candidate_session,
)
from app.domain.shopping.multimodal_consistency import (
    assess_multimodal_consistency,
    build_multimodal_conflict_question,
)
from app.domain.shopping.script_tools import SHOPPING_SCRIPT_TOOLS
from app.domain.shopping.schemas import ShoppingContext
from app.domain.shopping.skill_observability import (
    extract_shopping_script_calls,
    extract_shopping_skill_reads,
)
from app.domain.shopping.tool_guard import (
    RequireInitialShoppingToolMiddleware,
    ShoppingToolGuardMiddleware,
    RequireMultimodalConsistencyMiddleware,
)
from app.infrastructure.config import config
from app.infrastructure.observability.langsmith import child_run_config

# 人工回滚链保留旧的一体化 Tool；DeepAgent 主链使用 S4/S5 窄 Tool。
_ALL_TOOLS = SHOPPING_ROLLBACK_TOOLS
_DEEP_AGENT_BUSINESS_TOOLS = SHOPPING_HIGH_LEVEL_TOOLS
_BUSINESS_TOOL_NAMES = frozenset(
    str(getattr(tool, "name", "") or "")
    for tool in [*_ALL_TOOLS, *_DEEP_AGENT_BUSINESS_TOOLS]
)


def _tools_for_input_mode(
    tools: list,
    *,
    include_multimodal_consistency: bool,
) -> list:
    """Keep the visual preflight Tool off non-multimodal model surfaces."""
    if include_multimodal_consistency:
        return list(tools)
    return [
        tool for tool in tools
        if str(getattr(tool, "name", "") or "") != "check_multimodal_consistency"
    ]


def _deep_agent_tools(*, include_multimodal_consistency: bool = True) -> list:
    """Return the DeepAgent surface without changing the rollback runtime."""
    tools = _tools_for_input_mode(
        list(_DEEP_AGENT_BUSINESS_TOOLS),
        include_multimodal_consistency=include_multimodal_consistency,
    )
    if str(config.SHOPPING_SKILL_SCRIPT_MODE).lower() == "controlled":
        existing = {str(getattr(tool, "name", "") or "") for tool in tools}
        tools.extend(
            tool for tool in SHOPPING_SCRIPT_TOOLS
            if str(getattr(tool, "name", "") or "") not in existing
        )
    return tools

logger = logging.getLogger("ai-service.shopping.agent")

TokenSink = Callable[[str], None]

# ShoppingAgent 独立 checkpointer，跟主图/router/knowledge 隔离。
_shopping_checkpointer = InMemorySaver()


class ShoppingAgent:
    """Skill-driven ShoppingAgent with controlled, factual business tools.

    DeepAgent 主链按需读取 Shopping Skill。推荐任务由候选召回和结果终结
    组成；比较与详情统一读取 Router 已绑定商品事实。关闭 DeepAgent 时仍可
    人工回滚到旧的一体化 Tool。
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
        image_note = "有；仅商品发现 Skill 的候选召回步骤可以使用" if image_url else "无"
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
        run_config: RunnableConfig | None = None,
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
                "shopping_runtime": (
                    "deep_agent" if config.SHOPPING_DEEP_AGENT_ENABLED
                    else "langchain_agent"
                ),
                "skill_reads": [],
                "script_calls": [],
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
        multimodal_guard = RequireMultimodalConsistencyMiddleware()
        system_prompt = self._build_system_prompt(
            selected_product_ids=bound_product_ids,
            image_url=image_url,
            input_mode=normalised_input_mode,
        )
        agent_messages = self._build_messages(question, messages)
        shopping_runtime = "langchain_agent"
        skill_source = "/skills/shopping-agent/"

        try:
            # A new Agent instance makes middleware state request-scoped.  The
            # rollout switch changes only the runtime harness; the LLM still
            # sees the same four high-level Shopping business tools.
            if config.SHOPPING_DEEP_AGENT_ENABLED:
                from app.domain.shopping.deep_agent import (
                    SHOPPING_DEEP_AGENT_RUNTIME,
                    ShoppingDeepAgentAdapter,
                )

                deep_runtime = ShoppingDeepAgentAdapter(
                    llm=self._llm,
                    tools=_deep_agent_tools(
                        include_multimodal_consistency=(normalised_input_mode == "multimodal"),
                    ),
                    checkpointer=_shopping_checkpointer,
                    skills_root=config.SHOPPING_SKILLS_ROOT,
                ).build(
                    system_prompt=system_prompt,
                    guard=guard,
                    multimodal_guard=multimodal_guard,
                )
                agent = deep_runtime.graph
                skill_source = deep_runtime.skill_source
                shopping_runtime = SHOPPING_DEEP_AGENT_RUNTIME
            else:
                agent = create_agent(
                    model=self._llm,
                    checkpointer=_shopping_checkpointer,
                    system_prompt=system_prompt,
                    tools=_tools_for_input_mode(
                        list(_ALL_TOOLS),
                        include_multimodal_consistency=(normalised_input_mode == "multimodal"),
                    ),
                    state_schema=ShoppingAgentState,
                    middleware=[
                        RequireInitialShoppingToolMiddleware(),
                        multimodal_guard,
                        guard,
                        ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
                        ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
                    ],
                )

            # Most normal turns are select-tool → tool-result → answer.  Agent
            # middleware contributes graph steps too, so 8 can reject that
            # healthy three-step flow before its final model response.  The
            # tool/model middleware still provides the real loop bounds.
            agent_input = {
                "messages": agent_messages,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "jwt_token": jwt_token,
                "business_memory": effective_memory,
                "selected_product_ids": bound_product_ids,
                "image_url": image_url or "",
                "input_mode": normalised_input_mode,
            }
            agent_config = child_run_config(
                run_config,
                run_name="shopping-agent.tool-loop",
                tags=["runtime:" + shopping_runtime],
                metadata={"shopping_runtime": shopping_runtime},
                # The child graph needs an isolated checkpoint thread.  Its
                # callbacks/tags still come from the assistant request config,
                # so LangSmith renders it below the parent trace.
                thread_id=str(uuid4()),
                # Deep Agents adds Skill/filesystem middleware graph steps.
                # ToolCallLimit and ModelCallLimit remain the actual loop
                # guards; this only prevents a healthy bounded run from being
                # cut off before its final model response.
                recursion_limit=40 if shopping_runtime == "deep_agent" else 12,
            )
            with shopping_candidate_session():
                if token_sink is None:
                    result = await agent.ainvoke(agent_input, config=agent_config)
                else:
                    result = {}
                    async for mode, payload in agent.astream(
                        agent_input,
                        config=agent_config,
                        stream_mode=["values", "messages"],
                    ):
                        if mode == "values" and isinstance(payload, dict):
                            result = payload
                        elif mode == "messages":
                            message, metadata = payload
                            if isinstance(message, AIMessageChunk) and _is_user_visible_stream_chunk(message, metadata):
                                content = _stream_text_content(message.content)
                                if content:
                                    _emit_token(token_sink, content)
        except Exception as e:
            logger.exception("ShoppingAgent ainvoke failed")
            fallback = await self._run_restricted_fallback(
                question=question,
                conversation_id=conversation_id,
                user_id=user_id,
                jwt_token=jwt_token,
                business_memory=effective_memory,
                image_url=image_url,
                input_mode=normalised_input_mode,
                token_sink=token_sink,
                run_config=run_config,
            )
            if fallback is not None:
                fallback["shopping_runtime"] = shopping_runtime
                fallback["skill_reads"] = []
                fallback["script_calls"] = []
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
                "shopping_runtime": shopping_runtime,
                "skill_reads": [],
                "script_calls": [],
            }

        result_messages = result.get("messages", [])
        skill_reads = extract_shopping_skill_reads(
            result_messages,
            skill_source=skill_source,
        ) if shopping_runtime == "deep_agent" else []
        script_calls = extract_shopping_script_calls(
            result_messages,
        ) if shopping_runtime == "deep_agent" else []
        collected_tool_calls = _extract_tool_calls(
            result_messages,
            guard_records=[*multimodal_guard.records, *guard.records],
            allowed_tool_names=_BUSINESS_TOOL_NAMES,
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
                "model_call_count": _count_model_calls(result_messages),
                "shopping_runtime": shopping_runtime,
                "skill_reads": skill_reads,
                "script_calls": script_calls,
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": "ShoppingAgent completed without a high-level ToolResult.",
            }

        # ★ Phase 1a 关键变更：product_cards 优先从最近一次 ToolMessage 抽取，
        # 而不是无条件读 Store —— 避免"对比/详情"轮次误带上一轮推荐卡片。
        # 只有 ToolMessage 里没有 product_cards（LLM 没调工具，纯闲聊）时才回读 Store。
        tool_result = _extract_high_level_tool_result(result_messages)
        if tool_result and "product_cards" in tool_result:
            product_cards = tool_result.get("product_cards") or []
        else:
            product_cards = []

        # answer 从最后一条 AI 消息 content 提取
        answer = ""
        for m in reversed(result_messages):
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
            "compare_facts": "compare",
            "detail": "detail",
            "detail_facts": "detail",
            "clarify": "clarify",
        }
        capability = action_to_capability.get(str((tool_result or {}).get("action") or ""))
        dispatch_source = "agent_tool_loop" if collected_tool_calls else "none"

        if (
            (tool_result or {}).get("action") == "clarify"
            and (tool_result or {}).get("multimodal_consistency") == "conflict"
            and image_url
        ):
            try:
                await remember_pending_multimodal_choice(
                    conversation_id,
                    user_id,
                    {
                        "image_url": image_url,
                        "image_subject": (tool_result or {}).get("image_subject"),
                        "text_target": (tool_result or {}).get("text_target"),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.warning("could not persist pending multimodal choice", exc_info=True)

        return {
            "answer": answer or "暂时没能找到合适的商品，能再说详细一点吗？",
            "product_cards": product_cards,
            "task_type": "shopping",
            "sources": [],
            "tool_calls": collected_tool_calls,
            "suggested_questions": suggested_questions,
            "capability": capability,
            "dispatch_source": dispatch_source,
            "model_call_count": _count_model_calls(result_messages),
            "shopping_runtime": shopping_runtime,
            "skill_reads": skill_reads,
            "script_calls": script_calls,
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
        image_url: Optional[str] = None,
        input_mode: str = "text",
        token_sink: Optional[TokenSink] = None,
        dispatch_source: str = "restricted_rule_fallback",
        run_config: RunnableConfig | None = None,
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
            image_url=image_url or None,
            input_mode=_normalise_input_mode(image_url, input_mode),
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
                run_config=run_config,
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
        image_url: Optional[str],
        input_mode: str,
        token_sink: Optional[TokenSink],
        run_config: RunnableConfig | None = None,
    ) -> Optional[dict]:
        """Use the legacy dispatcher only as an observable failure fallback.

        This path is intentionally never reached before ``create_agent``.  The
        dispatcher receives no historical cards/focused product, so it cannot
        reintroduce a second cross-turn reference resolver.
        """
        decision = dispatch_shopping_capability(question, business_memory)
        if decision is None:
            return None

        # The legacy failure fallback must never silently discard a Router
        # scoped image.  Otherwise a primary DeepAgent error could turn a
        # verified image/text conflict into an unrelated text recommendation.
        normalised_input_mode = _normalise_input_mode(image_url, input_mode)
        if (
            decision.capability == "recommend"
            and normalised_input_mode == "multimodal"
            and image_url
        ):
            assessment = await assess_multimodal_consistency(
                query=question,
                image_url=image_url,
            )
            if assessment.decision == "conflict":
                clarify_question = build_multimodal_conflict_question(assessment)
                return {
                    "answer": clarify_question,
                    "task_type": "shopping",
                    "product_cards": [],
                    "sources": [],
                    "suggested_questions": [],
                    "capability": "clarify",
                    "dispatch_source": "restricted_multimodal_fallback",
                    "tool_calls": [{
                        "tool_name": "check_multimodal_consistency",
                        "name": "check_multimodal_consistency",
                        "input_params": {"query": question},
                        "args": {"query": question},
                        "status": "clarify",
                        "dispatch_source": "restricted_multimodal_fallback",
                        "input_mode": "multimodal",
                        "duration_ms": assessment.duration_ms,
                        "decision": assessment.decision,
                    }],
                    "error": False,
                }
            # A concrete text target remains usable when visual analysis is
            # uncertain, exactly like the main Tool path.  Vague text keeps
            # the existing multimodal retrieval intact.
            if assessment.decision == "uncertain" and assessment.text_target.strip():
                image_url = None
                normalised_input_mode = "text"
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
            image_url=image_url,
            input_mode=normalised_input_mode,
            token_sink=token_sink,
            dispatch_source="restricted_rule_fallback",
            run_config=run_config,
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
    run_config: RunnableConfig | None = None,
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
            response = await llm.ainvoke(
                messages,
                config=child_run_config(
                    run_config,
                    run_name="shopping-agent.fallback-render",
                    tags=["agent:shopping", "stage:fallback-render"],
                ),
            )
            answer = str(getattr(response, "content", "") or "").strip()
            return answer or fallback
        except Exception:  # noqa: BLE001
            logger.warning("dispatched capability answer rendering failed", exc_info=True)
            return fallback

    # This is the public SSE path: stream genuine provider chunks.  Do not wait
    # for ainvoke() and simulate a typewriter from the final string.
    chunks: list[str] = []
    try:
        async for chunk in llm.astream(
            messages,
            config=child_run_config(
                run_config,
                run_name="shopping-agent.fallback-render",
                tags=["agent:shopping", "stage:fallback-render"],
            ),
        ):
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


def _is_user_visible_stream_chunk(message: AIMessageChunk, metadata: Any) -> bool:
    """Exclude nested Judge/tool chunks from the public SSE stream."""
    if "ai_internal" in _stream_tags(metadata):
        return False
    if getattr(message, "tool_call_chunks", None) or getattr(message, "tool_calls", None):
        return False
    node = str((metadata or {}).get("langgraph_node") or "") if isinstance(metadata, dict) else ""
    return node not in {"tools", "tool"}


def _stream_tags(metadata: Any) -> set[str]:
    tags: set[str] = set()
    pending = [metadata]
    while pending:
        value = pending.pop()
        if not isinstance(value, dict):
            continue
        for key, item in value.items():
            if key == "tags" and isinstance(item, (list, tuple, set)):
                tags.update(str(tag) for tag in item)
            elif key in {"config", "metadata"} and isinstance(item, dict):
                pending.append(item)
    return tags


def _extract_tool_calls(
    messages: list,
    *,
    guard_records: Optional[List[Dict[str, Any]]] = None,
    allowed_tool_names: Optional[set[str] | frozenset[str]] = None,
) -> List[Dict[str, Any]]:
    """从 create_agent 的 result["messages"] 里抽取工具调用记录。"""
    records_by_id = {
        str(record.get("tool_call_id")): record
        for record in (guard_records or [])
        if record.get("tool_call_id")
    }
    failed_tool_call_ids = {
        str(getattr(message, "tool_call_id", "") or "")
        for message in (messages or [])
        if getattr(message, "type", "") == "tool"
        and getattr(message, "status", None) == "error"
    }
    # A multimodal discovery call may be intercepted before the retrieval
    # handler runs because the preflight found a verified image/text conflict.
    # It is an internal attempted call, not a user-visible business execution;
    # expose the preflight record only and do not make observability claim a
    # candidate retrieval took place.
    multimodal_conflict_call_ids: set[str] = set()
    for message in messages or []:
        if getattr(message, "type", "") != "tool":
            continue
        try:
            payload = json.loads(str(getattr(message, "content", "") or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("action") == "clarify"
            and payload.get("multimodal_consistency") == "conflict"
        ):
            multimodal_conflict_call_ids.add(
                str(getattr(message, "tool_call_id", "") or "")
            )
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
            if allowed_tool_names is not None and name not in allowed_tool_names:
                continue
            # Skill-contract rejections are internal correction steps, not
            # successful public Shopping business executions.
            if str(call_id) in failed_tool_call_ids or str(call_id) in multimodal_conflict_call_ids:
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
        record_name = str(record.get("tool_name") or record.get("name") or "")
        if allowed_tool_names is not None and record_name not in allowed_tool_names:
            continue
        if str(record.get("tool_call_id")) not in seen_ids:
            out.append(dict(record))
    return out


def _extract_high_level_tool_result(messages: list) -> Dict[str, Any]:
    """从消息列表里倒序找到最近一次 **高层 Tool** 返回的 dict。

    高层 Tool 返回的 JSON 里必定含 `action`（recommend/clarify/empty/compare/detail），
    用这个字段过滤掉旧的底层工具残留（如果消息 buffer 里混着的话）。
    """
    high_level_actions = {
        "recommend", "clarify", "empty", "compare", "detail",
        "compare_facts", "detail_facts",
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
