# -*- coding: utf-8 -*-
from __future__ import annotations
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agents.schemas import IntentDecision
from agents.prompts import ROUTER_PROMPT
from agents.state import AssistantState
from agents.runtime import checkpointer
from assistant.nodes import make_nodes
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy

# 路由器专用 checkpointer，独立于主图 checkpointer，避免消息污染
_router_checkpointer = InMemorySaver()


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
        # 路由器使用独立 checkpointer + 每次唯一 thread_id，确保：
        # 1. ainvoke 正常工作（notebook 验证 checkpointer=None 会报 TypeError）
        # 2. router 不会看到自己上轮的 tool_call 消息（避免 LLM 被污染）
        self._router = create_agent(
            model=llm,
            checkpointer=_router_checkpointer,
            system_prompt=ROUTER_PROMPT,
            response_format=ToolStrategy(IntentDecision),
        )
        self.graph = self._build()

    def _build(self):
        g = StateGraph(AssistantState)
        g.add_node("route_intent", self._route)
        g.add_node("shopping", self._nodes["shopping_node"])
        g.add_node("knowledge", self._nodes["knowledge_node"])
        g.add_node("chitchat", self._nodes["chitchat_node"])
        g.add_node("unknown", self._nodes["unknown_node"])
        g.add_node("format_response", self._nodes["format_response"])
        g.add_edge(START, "route_intent")
        g.add_conditional_edges("route_intent", lambda s: s.get("route") or "unknown",
                                {"shopping": "shopping", "knowledge": "knowledge",
                                 "chitchat": "chitchat", "unknown": "unknown"})
        for n in ("shopping", "knowledge", "chitchat", "unknown"):
            g.add_edge(n, "format_response")
        g.add_edge("format_response", END)
        return g.compile(checkpointer=checkpointer)

    async def _route(self, state: AssistantState) -> dict:
        question = state.get("question")
        if not question:
            return {"route": "unknown", "route_reason": "问题为空"}

        # 直接传 state["messages"]（已通过主图 checkpointer 合并了历史）
        # 不要再拼接第二次 question，否则问题出现两次。
        messages = state.get("messages") or [HumanMessage(question)]

        # 使用独立 checkpointer + 唯一 thread_id，确保每次路由调用都从干净状态开始
        # 避免 router 自己上轮的 tool_call 消息污染本次分类。
        decision = await self._router.ainvoke(
            {"messages": messages},
            config={"configurable": {"thread_id": str(uuid4())}},
        )
        structured = decision.get("structured_response")
        if structured is None:
            return {"route": "unknown", "route_reason": "路由分类失败"}
        return {"route": structured.task_type, "route_reason": structured.reason}

    async def run(self, **kwargs) -> dict:
        conversation_id = kwargs.get("conversation_id")
        user_id = kwargs.get("user_id")
        question = kwargs.get("question", "")
        state: AssistantState = {
            "question": question,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "jwt_token": kwargs.get("jwt_token"),
            "run_id": kwargs.get("run_id") or str(uuid4()),
            "trace_id": kwargs.get("trace_id") or str(uuid4()),
            "messages": [HumanMessage(content=question)],
            "error": False,
        }
        final = await self.graph.ainvoke(state, config={"configurable": {"thread_id": conversation_id}})
        result = final.get("result") or {}
        result.setdefault("run_id", state["run_id"])
        result.setdefault("trace_id", state["trace_id"])
        return result
