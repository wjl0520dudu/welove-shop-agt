# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Annotated, Any, NotRequired, TypedDict
from langchain_core.messages import AnyMessage
from langchain.agents import AgentState
from langgraph.graph import add_messages


class AssistantState(TypedDict):
    """Supervisor 共享状态。messages 通过 add_messages reducer 自动累积，
    checkpointer 负责跨轮持久化，所有子节点共享同一份对话记忆。
    """
    # ── 核心累积字段 ──
    messages: Annotated[list[AnyMessage], add_messages]

    # ── 本轮输入，每次 run() 覆盖 ──
    question: NotRequired[str]
    conversation_id: NotRequired[str]
    user_id: NotRequired[int | str]
    jwt_token: NotRequired[str]
    gender: NotRequired[str]
    skin_type: NotRequired[str]
    preference_tags: NotRequired[list[str] | None]
    # 多模态输入：单张图片 URL（可以是 OSS 绝对 URL，也可以是相对路径，
    # 后端调用 DashScope 前会走 _normalize_image_url 拼上 IMAGE_BASE_URL）。
    # simple 请求有图时 shopping_node 走多模态链路；complex 请求必须由
    # active_subtask.use_image=true 才能消费图片，避免图片污染知识子任务。
    # TODO(base64): 后续如支持前端直传 base64，会先上传到 OSS 转成 URL 再进这个字段。
    image_url: NotRequired[str]
    # Canonical recent messages and their persisted presentation artifacts are
    # supplied by chat-service on every turn.  They are not LangGraph messages:
    # ContextResolver consumes the structured cards/image metadata first.
    conversation_history: NotRequired[list[dict[str, Any]]]
    context_resolution: NotRequired[dict[str, Any]]
    canonical_question: NotRequired[str]
    # Router-owned image retrieval semantics.  This is deliberately separate
    # from the presence of text: a phrase such as “帮我找这个” can be a pure
    # image search rather than a text/image retrieval constraint.
    input_mode: NotRequired[str]

    # ── 路由节点产出 ──
    route: NotRequired[str]
    route_reason: NotRequired[str]
    route_confidence: NotRequired[float]
    route_source: NotRequired[str]
    rule_route: NotRequired[str]
    rule_confidence: NotRequired[float]
    rule_reason: NotRequired[str]
    llm_route: NotRequired[str]
    llm_confidence: NotRequired[float]
    llm_reason: NotRequired[str]
    route_fallback_used: NotRequired[bool]
    route_clarification: NotRequired[str]

    # ── 业务节点产出 ──
    answer: NotRequired[str]
    task_type: NotRequired[str]
    product_cards: NotRequired[list[dict[str, Any]]]
    sources: NotRequired[list[dict[str, Any]]]
    # Raw chunks are retained only by the in-process result for offline RAGAS.
    # ``api.response_adapter`` intentionally does not expose them to clients.
    retrieved_contexts: NotRequired[list[str]]
    tool_calls: NotRequired[list[dict[str, Any]]]
    suggested_questions: NotRequired[list[str]]
    capability: NotRequired[str]
    dispatch_source: NotRequired[str]
    model_call_count: NotRequired[int]
    shopping_runtime: NotRequired[str]
    skill_reads: NotRequired[list[str]]
    script_calls: NotRequired[list[dict[str, Any]]]

    # ── 编排元数据 ──
    run_id: NotRequired[str]
    trace_id: NotRequired[str]
    result: NotRequired[dict[str, Any]]
    error: NotRequired[bool]
    error_code: NotRequired[str]
    message: NotRequired[str]
    business_memory: NotRequired[dict[str, Any]]

    # ── Orchestrator 复杂问题编排 ──
    original_question: NotRequired[str]
    orchestrator_mode: NotRequired[str]          # simple | complex
    orchestrator_reason: NotRequired[str]
    sub_questions: NotRequired[list[dict[str, Any]]]
    active_subtask: NotRequired[dict[str, Any]]
    current_subquestion_index: NotRequired[int]
    sub_results: NotRequired[list[dict[str, Any]]]
    task_levels: NotRequired[list[list[str]]]
    dependency_context: NotRequired[list[dict[str, Any]]]
    # In-process callback used only while a complex DAG task is executing.
    # It is never persisted or exposed through the public response contract.
    subtask_token_sink: NotRequired[Any]
    orchestrator_plan_error: NotRequired[str]


class ShoppingAgentState(AgentState):
    """ShoppingAgent 内部 state：继承 create_agent 的 AgentState（含 messages），
    额外携带 conversation_id / user_id / jwt_token 给 ToolRuntime 里的工具读取。

    工具通过 `runtime.state["conversation_id"]` 拿到当前上下文，无需闭包捕获。
    对应教程 05 的模式。

    jwt_token 用于工具调 Java 后端接口时透传认证（如 user_tools 里的
    get_user_favorites / get_user_orders 等，Java 侧走 JwtFilter 校验）。
    """
    conversation_id: NotRequired[str]
    user_id: NotRequired[int | str]
    jwt_token: NotRequired[str]
    business_memory: NotRequired[dict[str, Any]]
    # Router-owned binding and image scope.  Shopping tools may consume these
    # values but must not infer a new binding from raw history.
    selected_product_ids: NotRequired[list[int]]
    image_url: NotRequired[str]
    input_mode: NotRequired[str]


class KnowledgeAgentState(AgentState):
    """KnowledgeAgent 内部 state：仅携带当前问题的会话隔离信息。

    跨轮实体消解由主路由完成；KnowledgeAgent 不读取历史业务记忆。
    """
    conversation_id: NotRequired[str]
    user_id: NotRequired[int | str]
