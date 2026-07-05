from __future__ import annotations
from uuid import uuid4
from langgraph.graph import END, START, StateGraph
from agents.state import AssistantState
from agents.runtime import checkpointer, run_config
from agents.memory import get_business_memory
from assistant.router import classify_intent
from assistant.nodes import make_nodes


class AssistantGraph:
    """Supervisor 编排图：route_intent 路由 -> 子节点 -> format_response。

    主图持有 checkpointer 与 messages 状态，子 agent 不再单独 checkpoint。
    子 agent 实例通过 make_nodes 闭包持有，不放进可序列化的 state。
    """

    def __init__(self, llm, shopping_agent=None, knowledge_agent=None):
        self.llm = llm
        self.shopping_agent = shopping_agent
        self.knowledge_agent = knowledge_agent
        self._nodes = make_nodes(llm, shopping_agent, knowledge_agent)
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

    async def _route(self, state: AssistantState) -> AssistantState:
        decision = await classify_intent(
            self.llm,
            question=state["question"],
            messages=state.get("messages", []),
            business_memory=state.get("business_memory", {}),
        )
        return {**state, "route": decision.task_type, "route_reason": decision.reason}

    async def run(self, **kwargs) -> dict:
        conversation_id = kwargs.get("conversation_id")
        user_id = kwargs.get("user_id")
        state: AssistantState = {
            "question": kwargs.get("question", ""),
            "context": kwargs.get("context", ""),
            "conversation_id": conversation_id,
            "user_id": user_id,
            "jwt_token": kwargs.get("jwt_token"),
            "run_id": kwargs.get("run_id") or str(uuid4()),
            "trace_id": kwargs.get("trace_id") or str(uuid4()),
            "messages": [],
            "business_memory": get_business_memory(conversation_id, user_id),
            "error": False,
        }
        final = await self.graph.ainvoke(state, config=run_config(conversation_id, user_id))
        result = final.get("result") or {}
        result.setdefault("run_id", state["run_id"])
        result.setdefault("trace_id", state["trace_id"])
        return result
