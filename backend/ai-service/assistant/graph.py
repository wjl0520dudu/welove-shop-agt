# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from typing import Any, AsyncIterator, Dict
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agents.memory import get_business_memory
from agents.schemas import IntentDecision
from agents.prompts import ROUTER_PROMPT
from agents.state import AssistantState
from agents import runtime as _runtime  # 用模块引用，运行时动态读 checkpointer/store
from assistant.nodes import make_nodes
from tools.router_tools import format_business_memory_for_router

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
        # 从 runtime 模块动态读，确保拿到的是 init_runtime() 覆盖后的实例
        return g.compile(checkpointer=_runtime.checkpointer, store=_runtime.store)

    async def _route(self, state: AssistantState) -> dict:
        question = state.get("question")
        if not question:
            return {"route": "unknown", "route_reason": "问题为空"}

        # 直接传 state["messages"]（已通过主图 checkpointer 合并了历史）
        # 不要再拼接第二次 question，否则问题出现两次。
        history_messages = state.get("messages") or [HumanMessage(question)]

        # 把业务上下文（上轮推荐商品、当前关注商品、用户偏好）塞进 Router 的 messages，
        # 让分类能看到"用户在指代什么"。例如 "第二个多少钱" 单看这句无法分类，
        # 但看到 last_product_cards 就能判断这是 shopping 场景（追问具体商品）。
        cid = state.get("conversation_id")
        uid = state.get("user_id")
        context_text = ""
        try:
            memory = await get_business_memory(cid, uid)
            context_text = format_business_memory_for_router(memory)
        except Exception:  # noqa: BLE001
            # Store 读取失败不阻塞分类，退化到纯 messages 分类
            logger.warning("router: 读取 business_memory 失败，退化到纯分类", exc_info=True)

        # ROUTER_PROMPT 作为首条 system 消息置顶；会话上下文作为第二条 system 消息追加。
        # with_structured_output 直链，不再需要 checkpointer / thread_id / recursion_limit。
        router_messages: list = [SystemMessage(content=ROUTER_PROMPT)]
        if context_text:
            router_messages.append(SystemMessage(content=context_text))
        router_messages.extend(history_messages)

        if self._router_llm is None:
            return {"route": "unknown", "route_reason": "路由模型未配置"}

        # with_structured_output 默认 include_raw=False，解析失败会抛异常；
        # 这里兜住，分类失败一律归 unknown，不阻塞主图。
        try:
            decision = await self._router_llm.ainvoke(router_messages)
        except Exception:  # noqa: BLE001
            logger.warning("router: 结构化分类失败，退化到 unknown", exc_info=True)
            return {"route": "unknown", "route_reason": "路由分类失败"}
        if decision is None:
            return {"route": "unknown", "route_reason": "路由分类失败"}
        return {"route": decision.task_type, "route_reason": decision.reason}

    def _make_initial_state(self, **kwargs) -> tuple[AssistantState, str, str]:
        """构造主图初始 state。返回 (state, run_id, trace_id)。"""
        run_id = kwargs.get("run_id") or str(uuid4())
        trace_id = kwargs.get("trace_id") or str(uuid4())
        question = kwargs.get("question", "")
        state: AssistantState = {
            "question": question,
            "conversation_id": kwargs.get("conversation_id"),
            "user_id": kwargs.get("user_id"),
            "jwt_token": kwargs.get("jwt_token"),
            "run_id": run_id,
            "trace_id": trace_id,
            "messages": [HumanMessage(content=question)],
            "error": False,
        }
        return state, run_id, trace_id

    async def run(self, **kwargs) -> dict:
        state, run_id, trace_id = self._make_initial_state(**kwargs)
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
            stream_mode=["updates", "messages"],
            subgraphs=True,
        ):
            # 兼容 subgraphs=True/False 两种输出结构
            if isinstance(chunk, tuple) and len(chunk) == 3:
                _namespace, mode, payload = chunk
            elif isinstance(chunk, tuple) and len(chunk) == 2:
                mode, payload = chunk
            else:
                continue

            if mode == "messages":
                # payload = (message_chunk, metadata_dict)
                msg_chunk, meta = payload
                async for event in self._translate_message_event(msg_chunk, meta):
                    yield event

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

    async def _translate_message_event(self, msg_chunk, meta) -> AsyncIterator[Dict[str, Any]]:
        """把 messages 流的 AIMessageChunk 翻译成 token 事件。"""
        # 只关心 AI 的增量 token。ToolMessage / HumanMessage 走 updates 处理。
        if not isinstance(msg_chunk, (AIMessage, AIMessageChunk)):
            return
        content = getattr(msg_chunk, "content", "")
        # content 可能是 str，也可能是 list（多模态 / tool_call 结构）
        if isinstance(content, str) and content:
            yield {"type": "token", "data": {"content": content}}
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    yield {"type": "token", "data": {"content": part["text"]}}

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
                },
            }

        # 2. 子节点消息里可能含 ToolMessage（工具返回）—— 用于 tool_result
        # 主图节点自己不会直接调工具，工具都在子图（ShoppingAgent 等）内部。
        # subgraphs=True 时子图消息会在 messages 流里冒泡，这里 updates 流一般看不到。
        # 保留结构，未来如果有主图直接调工具的场景可以在这里补充。
        _ = node_name  # 静默 lint
