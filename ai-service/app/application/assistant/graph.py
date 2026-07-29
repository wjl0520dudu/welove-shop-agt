# -*- coding: utf-8 -*-
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.infrastructure.persistence.memory import get_business_memory, remember_product_cards, remember_user_preferences
from app.application.assistant.schemas import IntentDecision, OrchestratorDecision
from app.prompts.prompts import ORCHESTRATOR_PROMPT, ROUTER_PROMPT
from app.application.assistant.state import AssistantState
from app.infrastructure.persistence import runtime as _runtime
from app.application.assistant.nodes import make_nodes
from app.application.assistant.context_resolver import resolve_turn_context
from app.application.assistant.orchestration import (
    PlanValidationError,
    TaskEvidence,
    TaskExecutionResult,
    build_task_levels,
    dependency_business_memory,
    dependency_payload,
    format_dependency_message,
    scope_task_images,
)
from app.application.assistant.router import (
    normalize_llm_decision,
)
from app.infrastructure.config import config
from app.infrastructure.errors import ErrorCode
from app.application.assistant.router_tools import format_business_memory_for_router

logger = logging.getLogger("ai-service.assistant.graph")

class AssistantGraph:
    """Supervisor 编排图：route_intent 路由 -> 子节点 -> format_response。
    主图持有 checkpointer 与 messages 状态，子 agent 不单独 checkpoint。
    子 agent 实例通过 make_nodes 闭包持有，不放进可序列化的 state。
    """

    def __init__(self, llm, shopping_agent=None, knowledge_agent=None):
        self.llm = llm
        self.shopping_agent = shopping_agent
        self.knowledge_agent = knowledge_agent
        self._nodes = make_nodes(llm, shopping_agent, knowledge_agent)
        # 路由器：单次结构化分类，不走 agent 循环。
        # 原先用 create_agent(response_format=ToolStrategy) 会多一次 LLM 往返
        # （schema 注册成工具 → 模型 tool_call → 回 ToolMessage → 再调一次模型 = 2 次）。
        # with_structured_output 是直链：模型一次产出结构化结果，LangChain 客户端解析 = 1 次。
        # method="function_calling" 走工具调用（与原 ToolStrategy 同机制，已验证兼容当前代理）。
        self._router_llm = (
            llm.with_structured_output(IntentDecision, method="function_calling")
            if llm is not None
            else None
        )
        self._orchestrator_llm = (
            _build_structured_llm(llm, OrchestratorDecision, preferred_method="json_schema")
            if llm is not None
            else None
        )
        self.graph = self._build()

    def _build(self):
        g = StateGraph(AssistantState)
        g.add_node("resolve_context", self._resolve_context)
        g.add_node("route_intent", self._route)
        g.add_node("plan_complex", self._plan_complex)
        g.add_node("shopping", self._nodes["shopping_node"])
        g.add_node("knowledge", self._nodes["knowledge_node"])
        g.add_node("chitchat", self._nodes["chitchat_node"])
        g.add_node("unknown", self._nodes["unknown_node"])
        g.add_node("execute_dag", self._execute_dag)
        g.add_node("synthesize_final", self._synthesize_final)
        g.add_node("format_response", self._nodes["format_response"])

        g.add_edge(START, "resolve_context")
        g.add_edge("resolve_context", "route_intent")
        g.add_conditional_edges(
            "route_intent",
            self._after_route,
            {
                "shopping": "shopping",
                "knowledge": "knowledge",
                "chitchat": "chitchat",
                "unknown": "unknown",
                "complex": "plan_complex",
            },
        )
        g.add_conditional_edges(
            "plan_complex",
            self._after_plan,
            {"complex": "execute_dag", "invalid": "format_response"},
        )
        for n in ("shopping", "knowledge", "chitchat", "unknown"):
            g.add_edge(n, "format_response")
        g.add_edge("execute_dag", "synthesize_final")
        g.add_edge("synthesize_final", "format_response")
        g.add_edge("format_response", END)
        # 从 runtime 模块动态读，确保拿到的是 init_runtime() 覆盖后的实例
        return g.compile(checkpointer=_runtime.checkpointer, store=_runtime.store)

    async def _resolve_context(self, state: AssistantState) -> dict:
        """Build one scoped, turn-level context before routing.

        Product cards in chat history are persisted UI artifacts and therefore
        more reliable than the single mutable Store slot.  The resolver writes
        only a state-local snapshot; it never overwrites durable memory merely
        because a user asked a follow-up.
        """
        try:
            persisted = await get_business_memory(
                state.get("conversation_id"), state.get("user_id"),
            )
        except Exception:  # noqa: BLE001
            logger.warning("context resolver: business memory unavailable", exc_info=True)
            persisted = {}
        resolved = resolve_turn_context(
            question=state.get("question", ""),
            conversation_history=state.get("conversation_history") or [],
            business_memory={**persisted, **dict(state.get("business_memory") or {})},
        )
        return resolved

    async def _plan_complex(self, state: AssistantState) -> dict:
        """Generate a DAG only after the Router has declared this turn complex."""
        question = (state.get("canonical_question") or state.get("question") or "").strip()
        if not question:
            return self._invalid_plan_state("", "复杂请求缺少完整问题", [], "canonical_question is empty")
        if self._orchestrator_llm is None:
            return self._invalid_plan_state(question, "编排模型未配置", [], "planner LLM is not configured")

        # The Router already consumed full conversation history and resolved
        # references.  Planner only needs the canonical request, the prepared
        # structural context, and image scope; it must not repeat top-level
        # semantic understanding with a second history read.
        messages: list = [SystemMessage(content=ORCHESTRATOR_PROMPT)]
        if state.get("image_url"):
            messages.append(SystemMessage(content=(
                "本轮用户携带了一张参考图片。请严格按任务粒度设置 use_image："
                "只有图片检索 shopping 子任务可为 true，knowledge/chitchat 和依赖后续任务必须为 false。"
            )))
        context_text = format_business_memory_for_router(state.get("business_memory") or {})
        if context_text:
            messages.append(SystemMessage(content=context_text))
        messages.append(HumanMessage(content=question))

        try:
            decision = await self._orchestrator_llm.ainvoke(
                messages,
                config={"tags": ["ai_internal"]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("planner: structured plan generation failed", exc_info=True)
            return self._invalid_plan_state(question, "复杂任务规划失败", [], str(exc))

        if decision is None:
            return self._invalid_plan_state(question, "复杂任务规划失败", [], "planner returned empty result")

        normalized = self._normalize_orchestrator_decision(
            question, decision, has_image=bool(state.get("image_url")),
        )
        if normalized.get("orchestrator_plan_error"):
            repair_messages = [
                *messages,
                SystemMessage(content=(
                    "上一次任务计划无法执行，错误为："
                    f"{normalized['orchestrator_plan_error']}。请重新生成无重复 ID、无非法依赖、"
                    "无环且不超过限制的完整任务计划。"
                )),
            ]
            try:
                repaired = await self._orchestrator_llm.ainvoke(
                    repair_messages,
                    config={"tags": ["ai_internal"]},
                )
                if repaired is not None:
                    normalized = self._normalize_orchestrator_decision(
                        question, repaired, has_image=bool(state.get("image_url")),
                    )
            except Exception:  # noqa: BLE001
                logger.warning("planner: invalid plan repair failed", exc_info=True)
        return normalized

    def _normalize_orchestrator_decision(
        self,
        question: str,
        decision: Any,
        *,
        has_image: bool = False,
    ) -> dict:
        mode = str(_decision_value(decision, "mode", "simple") or "simple").lower()
        reason = str(_decision_value(decision, "reason", "") or "")
        raw_tasks = _decision_value(decision, "tasks", []) or []
        tasks = _normalize_tasks(raw_tasks)
        if mode != "complex" or len(tasks) < 2:
            return self._invalid_plan_state(
                question,
                reason or "复杂任务未生成有效计划",
                tasks,
                "Planner must return mode=complex with at least two tasks",
            )
        try:
            tasks = scope_task_images(tasks, has_image=has_image)
            levels = build_task_levels(
                tasks,
                max_tasks=config.ORCHESTRATOR_MAX_TASKS,
                max_depth=config.ORCHESTRATOR_MAX_DEPTH,
            )
        except PlanValidationError as exc:
            return self._invalid_plan_state(question, reason, tasks, str(exc))
        return {
            "original_question": question,
            "orchestrator_mode": "complex",
            "orchestrator_reason": reason or "检测到多任务请求",
            "sub_questions": tasks,
            "sub_results": [],
            "current_subquestion_index": 0,
            "task_levels": levels,
        }

    @staticmethod
    def _invalid_plan_state(
        question: str,
        reason: str,
        tasks: list[dict[str, Any]],
        error: str,
    ) -> dict:
        answer = "这个复合问题的任务依赖暂时无法安全执行，请换一种更明确的说法后再试。"
        return {
            "original_question": question,
            "orchestrator_mode": "complex",
            "orchestrator_reason": reason or "任务计划无效",
            "orchestrator_plan_error": error,
            "sub_questions": tasks,
            "sub_results": [],
            "task_levels": [],
            "answer": answer,
            # ``orchestrator`` is an internal implementation detail. The
            # Router already classified this as a complex request, so keep the
            # public result semantic even when planning fails.
            "task_type": "complex",
            "product_cards": [],
            "sources": [],
            "retrieved_contexts": [],
            "tool_calls": [],
            "route": "complex",
            "route_reason": reason or "任务计划无效",
            "error": True,
            "error_code": ErrorCode.ORCHESTRATOR_PLAN_INVALID,
            "message": error,
            "messages": [AIMessage(content=answer)],
        }

    @staticmethod
    def _after_route(state: AssistantState) -> str:
        if state.get("orchestrator_mode") == "complex":
            return "complex"
        route = str(state.get("route") or "unknown")
        return route if route in {"shopping", "knowledge", "chitchat"} else "unknown"

    @staticmethod
    def _after_plan(state: AssistantState) -> str:
        if state.get("orchestrator_plan_error"):
            return "invalid"
        if state.get("orchestrator_mode") == "complex" and len(state.get("sub_questions") or []) >= 2:
            return "complex"
        return "invalid"

    async def _execute_dag(self, state: AssistantState) -> dict:
        """按拓扑层执行任务：同层并发、跨层等待、每个任务使用隔离状态。"""
        try:
            tasks = scope_task_images(
                list(state.get("sub_questions") or []),
                has_image=bool(state.get("image_url")),
            )
            levels = build_task_levels(
                tasks,
                max_tasks=config.ORCHESTRATOR_MAX_TASKS,
                max_depth=config.ORCHESTRATOR_MAX_DEPTH,
            )
        except PlanValidationError as exc:
            return {
                "sub_questions": list(state.get("sub_questions") or []),
                "sub_results": [],
                "task_levels": [],
                "orchestrator_plan_error": str(exc),
            }

        task_by_id = {str(task["id"]): task for task in tasks}
        result_by_id: dict[str, dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(max(1, config.ORCHESTRATOR_MAX_CONCURRENCY))
        try:
            base_memory = await get_business_memory(state.get("conversation_id"), state.get("user_id"))
        except Exception:  # noqa: BLE001
            logger.warning("orchestrator: 读取基础业务记忆失败，任务按空记忆执行", exc_info=True)
            base_memory = {}

        for level_index, task_ids in enumerate(levels):
            level_results = await asyncio.gather(
                *(
                    self._execute_subtask(
                        parent_state=state,
                        task=task_by_id[task_id],
                        level_index=level_index,
                        result_by_id=result_by_id,
                        base_memory=base_memory,
                        semaphore=semaphore,
                    )
                    for task_id in task_ids
                ),
                return_exceptions=True,
            )
            for task_id, result in zip(task_ids, level_results):
                if isinstance(result, BaseException):
                    logger.error(
                        "orchestrator: 子任务出现未捕获异常 task_id=%s: %s",
                        task_id,
                        result,
                    )
                    task = task_by_id[task_id]
                    result_by_id[task_id] = self._failed_task_result(
                        task,
                        level_index=level_index,
                        error_code=ErrorCode.ASSISTANT_ERROR,
                        message=str(result),
                    )
                else:
                    result_by_id[task_id] = result

        ordered_results = [result_by_id[str(task["id"])] for task in tasks]
        cards = _dedupe_product_cards(
            card
            for result in ordered_results
            if result.get("status") == "success"
            for card in (result.get("product_cards") or [])
        )
        if cards:
            try:
                await remember_product_cards(
                    state.get("conversation_id"), state.get("user_id"), cards,
                )
            except Exception:  # noqa: BLE001
                logger.warning("orchestrator: 聚合商品卡片写入业务记忆失败", exc_info=True)

        return {
            "sub_questions": tasks,
            "sub_results": ordered_results,
            "task_levels": levels,
        }

    async def _execute_subtask(
        self,
        *,
        parent_state: AssistantState,
        task: dict[str, Any],
        level_index: int,
        result_by_id: dict[str, dict[str, Any]],
        base_memory: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> dict[str, Any]:
        dependencies = [result_by_id[dep_id] for dep_id in (task.get("depends_on") or [])]
        failed_dependencies = [
            result for result in dependencies if result.get("status") != "success"
        ]
        if failed_dependencies:
            failed_ids = [str(result.get("id")) for result in failed_dependencies]
            return self._failed_task_result(
                task,
                level_index=level_index,
                status="blocked",
                error_code=ErrorCode.ORCHESTRATOR_DEPENDENCY_FAILED,
                message="前置任务未成功: " + ", ".join(failed_ids),
                dependency_ids=[str(result.get("id")) for result in dependencies],
            )

        payloads = [dependency_payload(result) for result in dependencies]
        task_messages = list(parent_state.get("messages") or [])
        if payloads:
            task_messages.append(SystemMessage(content=format_dependency_message(payloads)))
        task_messages.append(HumanMessage(content=str(task.get("question") or "")))

        task_memory = dependency_business_memory(base_memory, payloads)
        task_state: AssistantState = {
            "question": str(task.get("question") or ""),
            "original_question": parent_state.get("original_question") or parent_state.get("question") or "",
            "conversation_id": parent_state.get("conversation_id"),
            "user_id": parent_state.get("user_id"),
            "jwt_token": parent_state.get("jwt_token"),
            "run_id": parent_state.get("run_id"),
            "trace_id": parent_state.get("trace_id"),
            "messages": task_messages,
            "active_subtask": task,
            "dependency_context": payloads,
            "business_memory": task_memory,
            "orchestrator_mode": "complex",
            "error": False,
        }
        if task.get("use_image") and parent_state.get("image_url"):
            task_state["image_url"] = parent_state["image_url"]

        started = time.perf_counter()
        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    self._run_business_task(task_state),
                    timeout=max(0.01, config.ORCHESTRATOR_TASK_TIMEOUT_SECONDS),
                )
        except asyncio.TimeoutError:
            return self._failed_task_result(
                task,
                level_index=level_index,
                status="timeout",
                error_code=ErrorCode.ORCHESTRATOR_TASK_TIMEOUT,
                message=f"子任务执行超过 {config.ORCHESTRATOR_TASK_TIMEOUT_SECONDS:g} 秒",
                duration_ms=int((time.perf_counter() - started) * 1000),
                dependency_ids=[str(result.get("id")) for result in dependencies],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("orchestrator: 子任务执行失败 task_id=%s", task.get("id"))
            return self._failed_task_result(
                task,
                level_index=level_index,
                error_code=ErrorCode.ASSISTANT_ERROR,
                message=str(exc),
                duration_ms=int((time.perf_counter() - started) * 1000),
                dependency_ids=[str(result.get("id")) for result in dependencies],
            )

        has_error = bool(result.get("error"))
        task_result = {
            "id": task.get("id"),
            "question": task.get("question") or "",
            "intent_hint": task.get("intent_hint"),
            "depends_on": task.get("depends_on") or [],
            "use_image": bool(task.get("use_image")),
            "level": level_index,
            "status": "failed" if has_error else "success",
            "dependency_ids": [str(dep.get("id")) for dep in dependencies],
            "route": result.get("route"),
            "route_reason": result.get("route_reason"),
            "route_confidence": result.get("route_confidence"),
            "route_source": result.get("route_source"),
            "rule_route": result.get("rule_route"),
            "rule_confidence": result.get("rule_confidence"),
            "rule_reason": result.get("rule_reason"),
            "llm_route": result.get("llm_route"),
            "llm_confidence": result.get("llm_confidence"),
            "llm_reason": result.get("llm_reason"),
            "route_fallback_used": bool(result.get("route_fallback_used")),
            "task_type": result.get("task_type") or result.get("route") or "unknown",
            "answer": result.get("answer", ""),
            "product_cards": result.get("product_cards", []),
            "sources": result.get("sources", []),
            "retrieved_contexts": result.get("retrieved_contexts", []),
            "tool_calls": result.get("tool_calls", []),
            "suggested_questions": result.get("suggested_questions", []),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "error": has_error,
            "error_code": result.get("error_code"),
            "message": result.get("message"),
        }
        evidence = [
            TaskEvidence(kind="product", ref_id=str(card.get("product_id") or card.get("id") or ""), facts=card).model_dump()
            for card in task_result["product_cards"] if isinstance(card, dict)
        ] + [
            TaskEvidence(kind="knowledge_source", ref_id=str(source.get("doc_id") or source.get("url") or source.get("title") or ""), facts=source).model_dump()
            for source in task_result["sources"] if isinstance(source, dict)
        ]
        task_result["evidence"] = evidence
        task_result["execution_contract"] = TaskExecutionResult(
            task_id=str(task_result["id"]), route=str(task_result["route"] or "unknown"),
            capability=result.get("capability"), status=str(task_result["status"]),
            answer=str(task_result["answer"]), evidence=[TaskEvidence.model_validate(item) for item in evidence],
            product_cards=task_result["product_cards"], sources=task_result["sources"],
            hard_constraints_satisfied=not bool(result.get("hard_constraint_violation")),
        ).model_dump()
        return task_result

    async def _run_business_task(self, task_state: AssistantState) -> dict[str, Any]:
        # Planner has already assigned the domain for every DAG task.  Do not
        # send subtasks back through the top-level Router or re-read history.
        task = task_state.get("active_subtask") or {}
        route = str(task.get("intent_hint") or "unknown")
        if route not in {"shopping", "knowledge", "chitchat"}:
            route = "unknown"
        route_result = _route_result(
            route=route,
            confidence=1.0 if route != "unknown" else 0.0,
            source="planner",
            reason="Planner assigned subtask domain" if route != "unknown" else "Planner did not assign a runnable domain",
            mode="simple",
            canonical_question=str(task_state.get("question") or ""),
            business_memory=dict(task_state.get("business_memory") or {}),
        )
        node_key = f"{route}_node"
        if node_key not in self._nodes:
            route = "unknown"
            node_key = "unknown_node"
        node_result = await self._nodes[node_key](
            {**task_state, **route_result, "route": route},
        )
        return {**node_result, **route_result, "route": route}

    @staticmethod
    def _failed_task_result(
        task: dict[str, Any],
        *,
        level_index: int,
        error_code: str,
        message: str,
        status: str = "failed",
        duration_ms: int = 0,
        dependency_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        answer = (
            "这一部分依赖的前置任务没有成功，暂时无法继续。"
            if status == "blocked"
            else "这一部分暂时处理失败，请稍后再试。"
        )
        return {
            "id": task.get("id"),
            "question": task.get("question") or "",
            "intent_hint": task.get("intent_hint"),
            "depends_on": task.get("depends_on") or [],
            "use_image": bool(task.get("use_image")),
            "level": level_index,
            "status": status,
            "dependency_ids": dependency_ids or [],
            "route": task.get("intent_hint") or "unknown",
            "route_reason": message,
            "task_type": task.get("intent_hint") or "unknown",
            "answer": answer,
            "product_cards": [],
            "sources": [],
            "tool_calls": [],
            "duration_ms": duration_ms,
            "error": True,
            "error_code": error_code,
            "message": message,
        }

    def _synthesize_final(self, state: AssistantState) -> dict:
        if state.get("orchestrator_plan_error"):
            return self._invalid_plan_state(
                state.get("original_question") or state.get("question") or "",
                state.get("orchestrator_reason") or "任务计划无效",
                list(state.get("sub_questions") or []),
                str(state.get("orchestrator_plan_error")),
            )
        sub_results = state.get("sub_results") or []
        answer = _build_orchestrator_answer(sub_results)
        product_cards = _dedupe_product_cards(
            card
            for result in sub_results
            for card in (result.get("product_cards") or [])
        )
        sources = _dedupe_sources(
            source
            for result in sub_results
            for source in (result.get("sources") or [])
        )
        retrieved_contexts = list(dict.fromkeys(
            str(context)
            for result in sub_results
            for context in (result.get("retrieved_contexts") or [])
            if str(context).strip()
        ))[:10]
        tool_calls = [
            call
            for result in sub_results
            for call in (result.get("tool_calls") or [])
        ]
        suggested_questions = list(dict.fromkeys(
            question
            for result in sub_results
            for question in (result.get("suggested_questions") or [])
            if question
        ))[:4]
        has_error = any(bool(r.get("error")) for r in sub_results)
        return {
            "answer": answer,
            # Planner/DAG metadata remains available for observability, but
            # must not overwrite the Router's public semantic route.
            "task_type": "complex",
            "product_cards": product_cards,
            "sources": sources,
            "retrieved_contexts": retrieved_contexts,
            "tool_calls": tool_calls,
            "suggested_questions": suggested_questions,
            "route": "complex",
            "route_reason": state.get("orchestrator_reason"),
            "error": has_error,
            "error_code": ErrorCode.ORCHESTRATOR_PARTIAL_ERROR if has_error else None,
            "message": "部分子任务处理失败" if has_error else None,
            "messages": [AIMessage(content=answer)],
        }

    async def _route(self, state: AssistantState) -> dict:
        question = (state.get("question") or "").strip()
        image_url = (state.get("image_url") or "").strip()
        if not question and not image_url:
            return _route_result(
                route="unknown",
                confidence=0.0,
                source="fallback",
                reason="问题为空，需要用户补充需求",
                fallback_used=True,
            )

        # resolve_context has already prepared the full supplied conversation
        # history and its structural artifacts.  Router is the only semantic
        # reader of that context on the top-level path.
        history_messages = state.get("messages") or [HumanMessage(question)]
        memory: dict[str, Any] = dict(state.get("business_memory") or {})
        router_messages: list = [SystemMessage(content=ROUTER_PROMPT)]
        if image_url:
            router_messages.append(SystemMessage(content=(
                "本轮用户上传了参考图片。图片本身可用于后续 shopping 检索；"
                "请结合用户文字和完整对话判断领域与 simple/complex，不要忽略图片输入。"
            )))
        context_text = format_business_memory_for_router(memory)
        if context_text:
            router_messages.append(SystemMessage(content=context_text))
        router_messages.extend(history_messages)

        if self._router_llm is None:
            return _route_result(
                route="unknown", confidence=0.0, source="fallback",
                reason="路由模型未配置", fallback_used=True,
            )

        try:
            decision = await self._router_llm.ainvoke(
                router_messages,
                config={"tags": ["ai_internal"]},
            )
        except Exception:  # noqa: BLE001
            logger.warning("router: structured routing failed", exc_info=True)
            return _route_result(
                route="unknown", confidence=0.0, source="fallback",
                reason="结构化路由调用失败", fallback_used=True,
            )
        if decision is None:
            return _route_result(
                route="unknown", confidence=0.0, source="fallback",
                reason="结构化路由返回空结果", fallback_used=True,
            )

        try:
            normalized = normalize_llm_decision(decision)
        except Exception:  # noqa: BLE001
            logger.warning("router: structured routing output could not be normalized", exc_info=True)
            return _route_result(
                route="unknown", confidence=0.0, source="fallback",
                reason="结构化路由结果无法解析", fallback_used=True,
            )
        llm_trace = {
            "route": normalized.task_type,
            "mode": normalized.mode,
            "confidence": normalized.confidence,
            "reason": normalized.reason,
        }
        canonical_question = normalized.canonical_question or question
        routed_memory = {
            **memory,
            "selected_product_ids": list(normalized.resolved_product_ids or []),
            "resolved_knowledge_entities": list(normalized.resolved_knowledge_entities or []),
        }
        if normalized.mode == "complex":
            return _route_result(
                route="unknown",
                confidence=normalized.confidence,
                source="llm",
                reason=normalized.reason or "LLM identified a complex request",
                llm=llm_trace,
                mode="complex",
                canonical_question=canonical_question,
                business_memory=routed_memory,
            )
        if normalized.task_type == "unknown":
            return _route_result(
                route="unknown",
                confidence=normalized.confidence,
                source="fallback",
                reason=normalized.reason or "LLM could not determine the request",
                llm=llm_trace,
                fallback_used=True,
                canonical_question=canonical_question,
                business_memory=routed_memory,
            )
        return _route_result(
            route=normalized.task_type,
            confidence=normalized.confidence,
            source="llm",
            reason=normalized.reason or "LLM structured router",
            llm=llm_trace,
            mode="simple",
            canonical_question=canonical_question,
            business_memory=routed_memory,
        )

    def _make_initial_state(self, **kwargs) -> tuple[AssistantState, str, str]:
        """构造主图初始 state。返回 (state, run_id, trace_id)。"""
        run_id = kwargs.get("run_id") or str(uuid4())
        trace_id = kwargs.get("trace_id") or str(uuid4())
        question = kwargs.get("question", "") or ""
        image_url = (kwargs.get("image_url") or "").strip() or None
        # 纯图搜索时 question 可能为空，此时给 messages 一个占位描述，
        # 让 checkpointer / summarization middleware 能有内容处理；
        # 若 question 非空，直接透传给 HumanMessage。
        human_content = question.strip() or "[用户上传了一张图片，未附文字说明]"
        conversation_history = _normalize_conversation_history(
            kwargs.get("conversation_history") or [], question, image_url,
        )
        state: AssistantState = {
            "question": question,
            "conversation_id": kwargs.get("conversation_id"),
            "user_id": kwargs.get("user_id"),
            "jwt_token": kwargs.get("jwt_token"),
            "gender": kwargs.get("gender"),
            "skin_type": kwargs.get("skin_type"),
            "preference_tags": kwargs.get("preference_tags"),
            # 每轮都显式覆盖，避免 checkpointer 把上一轮图片/子任务带到本轮。
            "image_url": image_url or "",
            "active_subtask": {},
            "dependency_context": [],
            "orchestrator_plan_error": "",
            "task_levels": [],
            "sub_questions": [],
            "sub_results": [],
            "route": "",
            "route_reason": "",
            "route_confidence": None,
            "route_source": "",
            "rule_route": None,
            "rule_confidence": None,
            "rule_reason": "",
            "llm_route": None,
            "llm_confidence": None,
            "llm_reason": "",
            "route_fallback_used": False,
            "answer": "",
            "task_type": "",
            "product_cards": [],
            "sources": [],
            "retrieved_contexts": [],
            "tool_calls": [],
            "suggested_questions": [],
            "run_id": run_id,
            "trace_id": trace_id,
            "conversation_history": conversation_history,
            "context_resolution": {},
            # Router receives the complete history supplied by chat-service;
            # structured card/image artifacts remain available separately.
            "messages": _history_to_messages(conversation_history) or [HumanMessage(content=human_content)],
            "error": False,
            "error_code": None,
            "message": None,
        }
        return state, run_id, trace_id

    @staticmethod
    async def _sync_request_profile(state: AssistantState) -> None:
        """Persist profile fields already carried by chat-service without another API call."""
        if not state.get("user_id"):
            return
        profile = {
            key: value
            for key, value in {
                "gender": state.get("gender"),
                "skin_type": state.get("skin_type"),
                "preference_tags": state.get("preference_tags"),
            }.items()
            if value is not None
        }
        if not profile:
            return
        try:
            await remember_user_preferences(
                state.get("conversation_id"), state.get("user_id"), profile,
            )
        except Exception:  # noqa: BLE001
            logger.warning("profile preference sync failed", exc_info=True)

    async def run(self, **kwargs) -> dict:
        state, run_id, trace_id = self._make_initial_state(**kwargs)
        await self._sync_request_profile(state)
        conversation_id = state.get("conversation_id")
        final = await self.graph.ainvoke(state, config={"configurable": {"thread_id": conversation_id}})
        result = final.get("result") or {}
        result.setdefault("run_id", run_id)
        result.setdefault("trace_id", trace_id)
        return result

    async def astream(self, **kwargs) -> AsyncIterator[Dict[str, Any]]:
        """流式版本的 run()，逐步 yield 结构化事件 dict。

        每个 yield 是 `{"type": "<event_type>", "data": {...}}`。
        由 api/assistant_routes.py 的 SSE 端点转成 `event: <type>\\ndata: {...}\\n\\n`。

        事件类型：
        - start        请求开始
        - route        路由决策完成（shopping / knowledge / chitchat / unknown）
        - token        LLM 增量 token（重复多次）
        - tool_call    工具被调用
        - tool_result  工具返回
        - final        最终完整响应（跟 /run 一致）
        - error        出错
        - done         结束标志（前端可关流）

        用 stream_mode=["updates", "messages"] + subgraphs=True，同时拿到：
        - updates: 每个节点结束时的 state 增量（用于 route / tool_call / tool_result）
        - messages: 主图 + 子图 LLM 产生的每个 AIMessageChunk（token 流）
        - subgraphs: 让子图（ShoppingAgent 内的 create_agent）事件冒泡
        """
        state, run_id, trace_id = self._make_initial_state(**kwargs)
        await self._sync_request_profile(state)
        conversation_id = state.get("conversation_id")

        # start 事件：告诉前端 trace_id / run_id
        yield {
            "type": "start",
            "data": {
                "run_id": run_id,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
            },
        }

        final_result: Dict[str, Any] = {}
        # LangGraph subgraphs=True 时事件格式为 (namespace_tuple, mode, payload)
        # namespace_tuple: 空 = 主图，(node_name, task_id) = 子图
        async for chunk in self.graph.astream(
            state,
            config={"configurable": {"thread_id": conversation_id}},
            stream_mode=["updates", "messages", "custom"],
            subgraphs=True,
        ):
            # 兼容 subgraphs=True/False 两种输出结构
            if isinstance(chunk, tuple) and len(chunk) == 3:
                namespace, mode, payload = chunk
            elif isinstance(chunk, tuple) and len(chunk) == 2:
                namespace = ()
                mode, payload = chunk
            else:
                continue

            if mode == "messages":
                # payload = (message_chunk, metadata_dict)
                msg_chunk, meta = payload
                async for event in self._translate_message_event(msg_chunk, meta, namespace):
                    yield event

            elif mode == "custom":
                # Domain nodes publish genuine model chunks through
                # langgraph.config.get_stream_writer().
                if isinstance(payload, dict) and payload.get("type") == "token":
                    data = payload.get("data") or {}
                    if isinstance(data, dict) and data.get("content"):
                        yield {"type": "token", "data": {"content": str(data["content"])}}

            elif mode == "updates":
                # payload = {node_name: {state_delta_key: value, ...}}
                for node_name, node_output in (payload or {}).items():
                    async for event in self._translate_update_event(node_name, node_output):
                        yield event
                    # format_response 节点会把整个 result 写到 state["result"]
                    if node_name == "format_response" and isinstance(node_output, dict):
                        final_result = node_output.get("result") or final_result

        # final 事件：完整响应
        final_result.setdefault("run_id", run_id)
        final_result.setdefault("trace_id", trace_id)
        yield {"type": "final", "data": final_result}

        # done 事件：前端可关流
        yield {"type": "done", "data": {}}

    async def _translate_message_event(
        self,
        msg_chunk,
        meta,
        namespace=(),
    ) -> AsyncIterator[Dict[str, Any]]:
        """把 messages 流的 AIMessageChunk 翻译成 token 事件。"""
        # 只流式 LLM 的增量 chunk（AIMessageChunk）。节点写回 state 的完整 AIMessage 会被
        # messages 流再整段发一次，与已逐 token 流过的内容重复（答案发两遍），这里跳过。
        if not isinstance(msg_chunk, AIMessageChunk):
            return
        content = getattr(msg_chunk, "content", "")
        if self._should_suppress_token(meta, namespace, content):
            return
        # content 可能是 str，也可能是 list（多模态 / tool_call 结构）
        if isinstance(content, str) and content:
            yield {"type": "token", "data": {"content": content}}
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    yield {"type": "token", "data": {"content": part["text"]}}

    def _should_suppress_token(self, meta, namespace, content: Any) -> bool:
        """过滤不应展示给用户的 messages 流片段。"""
        meta = meta or {}
        namespace = namespace or ()

        # 内部结构化调用（如槽位抽取 with_structured_output）会打 ai_internal tag。
        # 不同 LangChain/LangGraph 版本可能把 tags 放在顶层或 metadata/config 下，统一兼容。
        tags = _collect_tags(meta)
        if "ai_internal" in tags:
            return True

        # Tool 节点里的内部 LLM 调用不应进入聊天气泡；否则会把 ShoppingNeed JSON
        # 之类的中间产物按 token 泄漏给前端。
        graph_node = str(meta.get("langgraph_node") or "")
        graph_path = _flatten_namespace(meta.get("langgraph_path") or ())
        namespace_text = " ".join(_flatten_namespace(namespace))
        if graph_node in {"tools", "tool"} or "tools" in graph_path or "tools" in namespace_text:
            return True

        # 主图业务节点返回的 {"messages": [AIMessage(content=完整答案)]} 会被 messages
        # stream 再发一次；这个片段不是 LLM 增量，而是节点回写的完整答案，必须过滤。
        main_nodes = {
            "route_intent",
            "plan_complex",
            "shopping",
            "knowledge",
            "chitchat",
            "unknown",
            "execute_dag",
            "synthesize_final",
            "format_response",
        }
        if not namespace and graph_node in main_nodes:
            return True

        return False

    async def _translate_update_event(self, node_name: str, node_output) -> AsyncIterator[Dict[str, Any]]:
        """把 updates 流翻译成 route / tool_call / tool_result 事件。"""
        if not isinstance(node_output, dict):
            return

        # 1. 路由节点产出 route 字段
        if node_name == "route_intent" and "route" in node_output:
            yield {
                "type": "route",
                "data": {
                    "task_type": node_output.get("route"),
                    "reason": node_output.get("route_reason"),
                    "confidence": node_output.get("route_confidence"),
                    "source": node_output.get("route_source"),
                    "rule_route": node_output.get("rule_route"),
                    "rule_confidence": node_output.get("rule_confidence"),
                    "llm_route": node_output.get("llm_route"),
                    "llm_confidence": node_output.get("llm_confidence"),
                    "fallback_used": bool(node_output.get("route_fallback_used")),
                },
            }

        if node_name == "plan_complex" and node_output.get("orchestrator_mode") == "complex":
            yield {
                "type": "orchestrator_plan",
                "data": {
                    "mode": "complex",
                    "reason": node_output.get("orchestrator_reason"),
                    "tasks": node_output.get("sub_questions") or [],
                },
            }

        if node_name == "prepare_subtask" and node_output.get("subtask_heading"):
            active = node_output.get("active_subtask") or {}
            yield {
                "type": "orchestrator_subtask",
                "data": {
                    "task": active,
                    "heading": node_output.get("subtask_heading"),
                },
            }

        if node_name == "execute_dag" and node_output.get("sub_results"):
            sub_results = node_output.get("sub_results") or []
            for result in sub_results:
                yield {
                    "type": "orchestrator_subtask",
                    "data": {
                        "task": {
                            "id": result.get("id"),
                            "question": result.get("question"),
                            "depends_on": result.get("depends_on") or [],
                            "use_image": bool(result.get("use_image")),
                        },
                        "status": result.get("status"),
                        "route": result.get("route"),
                        "route_confidence": result.get("route_confidence"),
                        "route_source": result.get("route_source"),
                        "fallback_used": bool(result.get("route_fallback_used")),
                        "duration_ms": result.get("duration_ms"),
                        "error_code": result.get("error_code"),
                    },
                }
            # Keep DAG telemetry out of the user token stream.  The only user
            # facing answer for a complex request is the final synthesized one.

        # 2. 子节点消息里可能含 ToolMessage（工具返回）—— 用于 tool_result
        # 主图节点自己不会直接调工具，工具都在子图（ShoppingAgent 等）内部。
        # subgraphs=True 时子图消息会在 messages 流里冒泡，这里 updates 流一般看不到。
        # 保留结构，未来如果有主图直接调工具的场景可以在这里补充。
        _ = node_name  # 静默 lint


def _route_result(
    *,
    route: str,
    confidence: float,
    source: str,
    reason: str,
    llm: dict[str, Any] | None = None,
    fallback_used: bool = False,
    mode: str = "simple",
    canonical_question: str = "",
    business_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one stable routing trace for graph state, API and offline evals."""
    llm_data = llm or {}
    result = {
        "route": route,
        "route_reason": reason,
        "route_confidence": max(0.0, min(1.0, float(confidence or 0.0))),
        "route_source": source,
        # Preserve response compatibility while removing deterministic routing.
        "rule_route": None,
        "rule_confidence": None,
        "rule_reason": "",
        "llm_route": llm_data.get("route"),
        "llm_confidence": llm_data.get("confidence"),
        "llm_reason": llm_data.get("reason", ""),
        "route_fallback_used": bool(fallback_used),
        "orchestrator_mode": mode,
        "orchestrator_reason": reason if mode == "complex" else "",
    }
    if canonical_question:
        # Replacing state.question here is intentional: child Agents receive the
        # already-resolved turn, not raw conversational shorthand.
        result["question"] = canonical_question
        result["canonical_question"] = canonical_question
    if business_memory is not None:
        result["business_memory"] = business_memory
    return result


def _decision_value(decision: Any, key: str, default: Any = None) -> Any:
    if isinstance(decision, dict):
        return decision.get(key, default)
    return getattr(decision, key, default)


def _build_structured_llm(llm: Any, schema: Any, *, preferred_method: str):
    try:
        return llm.with_structured_output(schema, method=preferred_method)
    except Exception:  # noqa: BLE001
        logger.warning(
            "structured output method=%s unavailable for %s, fallback to function_calling",
            preferred_method,
            getattr(schema, "__name__", str(schema)),
            exc_info=True,
        )
        return llm.with_structured_output(schema, method="function_calling")


def _normalize_tasks(raw_tasks: list) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(raw_tasks, start=1):
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif hasattr(item, "dict"):
            data = item.dict()
        elif isinstance(item, dict):
            data = dict(item)
        else:
            continue

        question = str(data.get("question") or "").strip()
        task_id = str(data.get("id") or f"t{index}").strip() or f"t{index}"
        depends_on = data.get("depends_on") or []

        tasks.append({
            "id": task_id,
            "question": question,
            "intent_hint": data.get("intent_hint"),
            "depends_on": (
                [str(v).strip() for v in depends_on]
                if isinstance(depends_on, list)
                else depends_on
            ),
            "use_image": data.get("use_image"),
            "reason": str(data.get("reason") or ""),
        })
    return tasks


def _format_subtask_heading(index: int, total: int, question: str) -> str:
    prefix = "我会分成几个部分依次回答：\n\n" if index == 0 else "\n\n"
    return f"{prefix}{index + 1}. {question}\n"


def _build_orchestrator_answer(sub_results: list[dict[str, Any]]) -> str:
    if not sub_results:
        return "我暂时没能完成这个复合问题的拆解，请你换个方式再问一次。"

    parts = ["我会分成几个部分依次回答："]
    for index, result in enumerate(sub_results, start=1):
        question = result.get("question") or f"第 {index} 个问题"
        answer = (result.get("answer") or "").strip()
        if not answer:
            if result.get("error"):
                answer = "这一部分暂时处理失败，请稍后再试。"
            else:
                answer = "这一部分暂时没有得到明确结果。"
        parts.append(f"{index}. {question}\n{answer}")
    return "\n\n".join(parts)


def _dedupe_product_cards(cards_iter) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in cards_iter:
        if not isinstance(card, dict):
            continue
        key = str(card.get("product_id") or card.get("id") or card.get("title") or len(out))
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def _dedupe_sources(sources_iter) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources_iter:
        if hasattr(source, "model_dump"):
            source = source.model_dump()
        elif hasattr(source, "dict"):
            source = source.dict()
        if not isinstance(source, dict):
            continue
        key = str(
            source.get("url")
            or source.get("doc_id")
            or source.get("doc")
            or source.get("doc_name")
            or source.get("title")
            or len(out)
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out


def _normalize_conversation_history(
    raw_history: list[Any], question: str, image_url: str | None,
) -> list[dict[str, Any]]:
    """Normalize Java message DTOs without truncating the supplied history."""
    out: list[dict[str, Any]] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in {"user", "assistant", "system"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content and not item.get("image_url"):
            continue
        out.append({
            "id": item.get("id"),
            "role": role,
            "content": content,
            "image_url": item.get("image_url") or item.get("imageUrl") or "",
            "product_cards": item.get("product_cards") or item.get("productCards") or [],
            "task_type": item.get("task_type") or item.get("taskType") or "",
            "agent_meta": item.get("agent_meta") or item.get("agentMeta") or {},
        })
    # Direct callers/tests may not be chat-service.  Keep current turn present
    # exactly once in that case.
    if not out or out[-1].get("role") != "user" or out[-1].get("content") != (question or "").strip():
        out.append({"role": "user", "content": (question or "").strip(), "image_url": image_url or ""})
    return out


def _history_to_messages(history: list[dict[str, Any]]) -> list:
    """Convert the textual portion of persisted history into LangChain messages."""
    messages: list = []
    for item in history:
        content = str(item.get("content") or "").strip()
        if item.get("image_url") and not content:
            content = "[用户上传了一张图片]"
        if not content:
            continue
        message_id = str(item.get("id")) if item.get("id") is not None else None
        role = item.get("role")
        if role == "user":
            messages.append(HumanMessage(content=content, id=message_id))
        elif role == "assistant":
            messages.append(AIMessage(content=content, id=message_id))
        elif role == "system":
            messages.append(SystemMessage(content=content, id=message_id))
    return messages


def _collect_tags(meta: Dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    stack = [meta]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "tags" and isinstance(value, (list, tuple, set)):
                    tags.update(str(v) for v in value)
                elif key in {"metadata", "config"} and isinstance(value, dict):
                    stack.append(value)
        elif isinstance(item, (list, tuple, set)):
            tags.update(str(v) for v in item)
    return tags


def _flatten_namespace(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, (list, tuple, set)):
        for part in value:
            out.extend(_flatten_namespace(part))
    elif value is not None:
        out.append(str(value))
    return out
