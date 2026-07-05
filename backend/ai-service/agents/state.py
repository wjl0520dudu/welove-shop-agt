# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Annotated, Any, NotRequired, TypedDict
from langchain_core.messages import AnyMessage
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