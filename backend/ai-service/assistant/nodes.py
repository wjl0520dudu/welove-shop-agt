from __future__ import annotations
import logging
from typing import Any, Callable, Dict, Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from agents.state import AssistantState
from agents.memory import remember_product_cards
from agents.prompts import CHITCHAT_PROMPT
from shopping.agent import ShoppingAgent
from knowledge.agent import KnowledgeAgent

logger = logging.getLogger("ai-service.nodes")


def make_nodes(llm, shopping_agent: Optional[ShoppingAgent] = None,
               knowledge_agent: Optional[KnowledgeAgent] = None) -> Dict[str, Callable]:
    """生成节点函数字典。实例通过闭包持有，懒构造以避免无关分支触发数据库连接。"""
    _shopping_holder: Dict[str, Any] = {"agent": shopping_agent}
    _knowledge_holder: Dict[str, Any] = {"agent": knowledge_agent}

    def get_shopping():
        if _shopping_holder["agent"] is None:
            _shopping_holder["agent"] = ShoppingAgent(llm)
        return _shopping_holder["agent"]

    def get_knowledge():
        if _knowledge_holder["agent"] is None:
            _knowledge_holder["agent"] = KnowledgeAgent()
        return _knowledge_holder["agent"]

    _chitchat_chain: Dict[str, Any] = {"chain": None}

    def get_chitchat_chain():
        if _chitchat_chain["chain"] is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", CHITCHAT_PROMPT + "\n结合最近对话历史自然回应，简短友好。"),
                ("human", "{question}"),
            ])
            _chitchat_chain["chain"] = prompt | llm | StrOutputParser()
        return _chitchat_chain["chain"]

    async def shopping_node(state: AssistantState) -> AssistantState:
        try:
            result = await get_shopping().run(
                question=state.get("question", ""),
                messages=_history_messages(state),
                business_memory=state.get("business_memory", {}),
                conversation_id=state.get("conversation_id"),
                user_id=state.get("user_id"),
            )
        except Exception as e:
            logger.exception("shopping node failed")
            return {**state, "answer": "导购 Agent 暂时不可用，请稍后再试。", "task_type": "shopping",
                    "error": True, "error_code": "AI_SHOPPING_ERROR", "message": str(e)}
        cards = result.get("product_cards") or []
        if cards:
            remember_product_cards(state.get("conversation_id"), state.get("user_id"), cards)
        return _merge_result(state, result, task_type="shopping")

    async def knowledge_node(state: AssistantState) -> AssistantState:
        try:
            result = await get_knowledge().ask(
                question=state.get("question", ""),
                business_memory=state.get("business_memory", {}),
            )
        except Exception as e:
            logger.exception("knowledge node failed")
            return {**state, "answer": "知识检索暂时不可用，请稍后再试。", "task_type": "knowledge",
                    "error": True, "error_code": "AI_RAG_ERROR", "message": str(e)}
        return _merge_result(state, result, task_type="knowledge")

    async def chitchat_node(state: AssistantState) -> AssistantState:
        if llm is None:
            return {**state, "answer": "AI 助手暂未配置，无法闲聊。", "task_type": "chitchat",
                    "error": True, "error_code": "AI_LLM_NOT_CONFIGURED"}
        try:
            chain = get_chitchat_chain()
            answer = await chain.ainvoke({"question": state.get("question", "")})
        except Exception as e:
            logger.exception("chitchat node failed")
            return {**state, "answer": "闲聊回复失败，请稍后再试。", "task_type": "chitchat",
                    "error": True, "error_code": "AI_CHITCHAT_ERROR", "message": str(e)}
        return {**state, "answer": answer, "task_type": "chitchat"}

    async def unknown_node(state: AssistantState) -> AssistantState:
        return {**state, "answer": "我可以帮你找商品、推荐，或回答商品知识问题，请告诉我你的需求。",
                "task_type": "unknown"}

    def format_response(state: AssistantState) -> AssistantState:
        result = {
            "answer": state.get("answer", ""),
            "task_type": state.get("task_type") or state.get("route") or "unknown",
            "product_cards": state.get("product_cards", []),
            "sources": state.get("sources", []),
            "tool_calls": state.get("tool_calls", []),
            "run_id": state.get("run_id"),
            "trace_id": state.get("trace_id"),
            "route": state.get("route"),
            "route_reason": state.get("route_reason"),
            "error": bool(state.get("error", False)),
            "error_code": state.get("error_code"),
            "message": state.get("message"),
        }
        return {**state, "result": result}

    return {
        "shopping_node": shopping_node,
        "knowledge_node": knowledge_node,
        "chitchat_node": chitchat_node,
        "unknown_node": unknown_node,
        "format_response": format_response,
    }


def _merge_result(state: AssistantState, result: Dict[str, Any], *, task_type: str) -> AssistantState:
    merged = {**state}
    for key in ("answer", "product_cards", "sources", "tool_calls", "error", "error_code", "message"):
        if key in result:
            merged[key] = result[key]
    merged.setdefault("answer", "")
    merged.setdefault("task_type", result.get("task_type") or task_type)
    merged.setdefault("product_cards", [])
    merged.setdefault("sources", [])
    merged.setdefault("tool_calls", [])
    merged.setdefault("error", False)
    return merged


def _history_messages(state: AssistantState) -> list:
    messages = state.get("messages") or []
    out = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
            continue
        mtype = getattr(m, "type", "")
        content = getattr(m, "content", "")
        if mtype == "human":
            out.append({"role": "user", "content": content})
        elif mtype == "ai":
            out.append({"role": "assistant", "content": str(content) if not isinstance(content, str) else content})
        elif mtype == "system":
            out.append({"role": "system", "content": content})
    return out
