from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.infrastructure.persistence.memory import get_business_memory
from app.domain.shopping.preferences import build_preference_questions
from app.prompts.prompts import SHOPPING_AGENT_PROMPT
from app.application.assistant.state import ShoppingAgentState
from app.infrastructure.llm.middleware import build_summarization_middleware
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

# Phase 1a 关键变更：LLM 只面对 4 个高层 tool，底层 12 个工具全部退到 Capability 内部。
# 见 shopping/high_level_tools.py 和 shopping/capabilities/*。
_ALL_TOOLS = SHOPPING_HIGH_LEVEL_TOOLS

# 保留 summarization middleware（长对话压缩）。
# PreferenceLearningMiddleware 依然禁用 —— after_model 触发太密，代价高。
_SHOPPING_MIDDLEWARE = [
    build_summarization_middleware(),
]

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

    def _build_system_prompt(self, business_memory: Dict[str, Any]) -> str:
        """Return a domain-only prompt.

        The Router has already expanded cross-turn references into the current
        question and has bound any product set in ``business_memory`` for tools.
        Do not expose raw history or product candidates to the Shopping LLM a
        second time: that would recreate a competing context resolver.
        """
        return SHOPPING_AGENT_PROMPT

    def _build_messages(
        self, question: str, messages: List[Dict[str, Any]]
    ) -> list:
        """把 supervisor 传入的对话历史（dict）转成 langchain message 对象。"""
        out: list = []
        for m in messages or []:
            if not isinstance(m, dict):
                out.append(m)
                continue
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            content = str(content).strip()
            if not content:
                continue
            if role == "user":
                out.append(HumanMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
            elif role == "system":
                out.append(SystemMessage(content=content))
        return out

    async def run(
        self,
        *,
        question: str,
        messages: List[Dict[str, Any]],
        business_memory: Dict[str, Any],
        conversation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        jwt_token: Optional[str] = None,
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

        # 拿 Store memory + supervisor 传入的 business_memory 合并
        store_memory = await get_business_memory(conversation_id, user_id)
        effective_memory = {**store_memory, **business_memory} if business_memory else store_memory

        # High-certainty requests execute the real capability directly.  This is
        # intentionally before create_agent: the model should not be allowed to
        # freely choose a tool for an already deterministic business action.
        decision = dispatch_shopping_capability(question, effective_memory)
        if decision is not None:
            return await self._run_dispatched_capability(
                decision=decision,
                question=question,
                conversation_id=conversation_id,
                user_id=user_id,
                jwt_token=jwt_token,
                business_memory=effective_memory,
                token_sink=token_sink,
            )

        system_prompt = self._build_system_prompt(effective_memory)

        # create_agent 每次重建：system_prompt 依赖本次记忆快照。工具已单例。
        agent = create_agent(
            model=self._llm,
            checkpointer=_shopping_checkpointer,
            system_prompt=system_prompt,
            tools=_ALL_TOOLS,
            state_schema=ShoppingAgentState,
            middleware=_SHOPPING_MIDDLEWARE,
        )

        agent_messages = self._build_messages(question, messages)

        try:
            # recursion_limit=15：4 个高层 tool 场景下 3-5 步足够，15 是安全上限。
            result = await agent.ainvoke(
                {
                    "messages": agent_messages,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "jwt_token": jwt_token,
                    "business_memory": effective_memory,
                },
                config={
                    "configurable": {"thread_id": str(uuid4())},
                    "recursion_limit": 15,
                },
            )
        except Exception as e:
            logger.exception("ShoppingAgent ainvoke failed")
            # Store 兜底（可能 Capability 已经写过 last_product_cards）
            try:
                fallback_memory = await get_business_memory(conversation_id, user_id)
                fallback_cards = fallback_memory.get("last_product_cards") or []
            except Exception:  # noqa: BLE001
                fallback_cards = []
            return {
                "answer": (
                    "我已经为你找到了几款商品，但整理推荐语时遇到点问题。"
                    "你可以直接看下面的商品卡片，或者告诉我更具体的偏好我再帮你精选。"
                    if fallback_cards
                    else "导购 Agent 处理失败，请稍后再试。"
                ),
                "product_cards": fallback_cards,
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": str(e),
            }

        collected_tool_calls = _extract_tool_calls(result.get("messages", []))

        # ★ Phase 1a 关键变更：product_cards 优先从最近一次 ToolMessage 抽取，
        # 而不是无条件读 Store —— 避免"对比/详情"轮次误带上一轮推荐卡片。
        # 只有 ToolMessage 里没有 product_cards（LLM 没调工具，纯闲聊）时才回读 Store。
        tool_result = _extract_high_level_tool_result(result.get("messages", []))
        if tool_result and "product_cards" in tool_result:
            product_cards = tool_result.get("product_cards") or []
        else:
            fallback_memory = await get_business_memory(conversation_id, user_id)
            product_cards = fallback_memory.get("last_product_cards") or []

        # answer 从最后一条 AI 消息 content 提取
        answer = ""
        for m in reversed(result.get("messages", [])):
            mtype = getattr(m, "type", "")
            if mtype == "ai":
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content
                    break

        try:
            latest_memory = await get_business_memory(conversation_id, user_id)
        except Exception:  # noqa: BLE001
            latest_memory = effective_memory
        suggested_questions = build_preference_questions(
            latest_memory.get("user_preferences") or {}
        )

        return {
            "answer": answer or "暂时没能找到合适的商品，能再说详细一点吗？",
            "product_cards": product_cards,
            "task_type": "shopping",
            "sources": [],
            "tool_calls": collected_tool_calls,
            "suggested_questions": suggested_questions,
            "error": False,
        }

    async def _run_dispatched_capability(
        self,
        *,
        decision: DispatchDecision,
        question: str,
        conversation_id: Optional[str],
        user_id: Optional[int],
        jwt_token: Optional[str],
        business_memory: Dict[str, Any],
        token_sink: Optional[TokenSink] = None,
    ) -> dict:
        """Execute one capability without an LLM tool-selection loop."""
        if decision.capability == "transaction_unsupported":
            return {
                "answer": "当前导购助手支持商品推荐、对比和详情咨询；请在商品卡片或商品详情页完成加购、下单和支付。",
                "task_type": "shopping",
                "product_cards": [], "sources": [], "suggested_questions": [], "error": False,
                "capability": decision.capability,
                "dispatch_source": decision.source,
                "tool_calls": [_dispatch_trace(decision, question, status="unsupported")],
            }

        context = ShoppingContext(
            conversation_id=conversation_id, user_id=user_id, jwt_token=jwt_token,
            is_logged_in=bool(user_id), business_memory=business_memory,
            last_product_cards=list(business_memory.get("last_product_cards") or []),
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

        try:
            latest_memory = await get_business_memory(conversation_id, user_id)
        except Exception:  # noqa: BLE001
            latest_memory = business_memory
        return {
            "answer": await _compose_capability_answer(
                self._llm, decision.capability, question, payload,
                token_sink=token_sink,
            ),
            "task_type": "shopping",
            "product_cards": payload.get("product_cards") or [],
            "sources": [],
            "tool_calls": [_dispatch_trace(decision, question, status="completed")],
            "suggested_questions": build_preference_questions(latest_memory.get("user_preferences") or {}),
            "capability": decision.capability,
            "dispatch_source": decision.source,
            "error": bool(payload.get("error", False)),
            "error_code": payload.get("error_code"),
            "message": payload.get("message"),
        }


def _dispatch_trace(decision: DispatchDecision, question: str, *, status: str) -> dict:
    tool_by_capability = {
        "recommend": "recommend_products", "compare": "compare_products",
        "detail": "answer_product_detail", "user_context": "get_user_shopping_context",
        "transaction_unsupported": "transaction_unsupported",
    }
    name = tool_by_capability[decision.capability]
    return {"tool_name": name, "name": name, "input_params": {"query": question},
            "args": {"query": question}, "status": status,
            "dispatch_source": decision.source, "dispatch_reason": decision.reason}


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


def _extract_tool_calls(messages: list) -> List[Dict[str, Any]]:
    """从 create_agent 的 result["messages"] 里抽取工具调用记录。"""
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
            out.append({
                "tool_call_id": call_id,
                "tool_name": name,
                "input_params": normalized_args,
                "status": "invoked",
                # Backward-compatible aliases used by existing scripts/tests.
                "name": name,
                "args": normalized_args,
            })
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
