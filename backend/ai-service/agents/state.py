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

    # ── 路由节点产出 ──
    route: NotRequired[str]
    route_reason: NotRequired[str]

    # ── 业务节点产出 ──
    answer: NotRequired[str]
    task_type: NotRequired[str]
    product_cards: NotRequired[list[dict[str, Any]]]
    sources: NotRequired[list[dict[str, Any]]]
    tool_calls: NotRequired[list[dict[str, Any]]]

    # ── 编排元数据 ──
    run_id: NotRequired[str]
    trace_id: NotRequired[str]
    result: NotRequired[dict[str, Any]]
    error: NotRequired[bool]
    error_code: NotRequired[str]
    message: NotRequired[str]
    business_memory: NotRequired[dict[str, Any]]


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


class KnowledgeAgentState(AgentState):
    """KnowledgeAgent 内部 state：继承 AgentState（含 messages），额外携带
    conversation_id / user_id 给 ToolRuntime 里的工具读取。

    KnowledgeAgent 也挂了 resolve_reference（跨 shopping/knowledge 的指代消解），
    resolve_reference 要从 runtime.state 拿 conversation_id 去读 Store 里的
    last_knowledge_entities / last_product_cards。

    KnowledgeAgent 不调 Java 后端，所以不需要 jwt_token。
    """
    conversation_id: NotRequired[str]
    user_id: NotRequired[int | str]
