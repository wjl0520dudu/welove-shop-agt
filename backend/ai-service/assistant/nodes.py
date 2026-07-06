# -*- coding: utf-8 -*-
from __future__ import annotations
import logging
from uuid import uuid4
from typing import Any, Callable, Dict, Optional
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import AIMessage, HumanMessage
from agents.state import AssistantState
from agents.schemas import ChitchatResult
from agents.prompts import CHITCHAT_PROMPT
from shopping.agent import ShoppingAgent
from knowledge.agent import KnowledgeAgent

logger = logging.getLogger("ai-service.nodes")

# 闲聊 agent 专用独立 checkpointer，与主图 checkpointer 完全隔离
_chitchat_checkpointer = InMemorySaver()


def make_nodes(llm, shopping_agent: Optional[ShoppingAgent] = None,
               knowledge_agent: Optional[KnowledgeAgent] = None) -> Dict[str, Callable]:
    _shopping_holder: Dict[str, Any] = {"agent": shopping_agent}
    _knowledge_holder: Dict[str, Any] = {"agent": knowledge_agent}
    _chitchat_holder: Dict[str, Any] = {"agent": None}

    def get_shopping():
        if _shopping_holder["agent"] is None:
            _shopping_holder["agent"] = ShoppingAgent(llm)
        return _shopping_holder["agent"]

    def get_knowledge():
        if _knowledge_holder["agent"] is None:
            _knowledge_holder["agent"] = KnowledgeAgent(llm)
        return _knowledge_holder["agent"]

    def _get_chitchat_agent():
        if _chitchat_holder["agent"] is None:
            _chitchat_holder["agent"] = create_agent(
                model=llm,
                checkpointer=_chitchat_checkpointer,
                system_prompt=CHITCHAT_PROMPT,
                response_format=ToolStrategy(ChitchatResult),
            )
        return _chitchat_holder["agent"]

    async def shopping_node(state: AssistantState) -> dict:
        try:
            result = await get_shopping().run(
                question=state.get("question", ""),
                messages=_history_messages(state),
                business_memory=state.get("business_memory", {}),
                conversation_id=state.get("conversation_id"),
                user_id=state.get("user_id"),
                jwt_token=state.get("jwt_token"),
            )
        except Exception as e:
            logger.exception("shopping node failed")
            return {
                "answer": "导购 Agent 暂时不可用，请稍后再试。",
                "task_type": "shopping",
                "error": True,
                "error_code": "AI_SHOPPING_ERROR",
                "message": str(e),
                "messages": [AIMessage(content="导购 Agent 暂时不可用，请稍后再试。")],
            }
        return _merge_result(result, task_type="shopping",
                             extra={"messages": [AIMessage(content=result.get("answer", ""))]})

    async def knowledge_node(state: AssistantState) -> dict:
        try:
            messages = _build_agent_messages(state)
            result = await get_knowledge().run(
                messages=messages,
                conversation_id=state.get("conversation_id", ""),
            )
            # 无检索结果兜底：sources 为空 或 has_answer=False 时补一句引导，
            # 但 task_type 保持 knowledge —— 不要伪装成 chitchat，否则前端行为错乱。
            # 具体的"知识库暂无相关信息"由 KNOWLEDGE_PROMPT 约束 LLM 自己说，这里只做兜底 answer 补全。
            has_answer = bool(result.get("has_answer", True))
            sources = result.get("sources") or []
            answer = (result.get("answer") or "").strip()
            if (not has_answer or not sources) and not answer:
                question = state.get("question", "")
                answer = (
                    f"关于「{question}」，我在知识库里暂时没有找到直接相关的资料。"
                    f"你可以换个角度问我，或者提供更具体的场景（比如你的肤质、使用需求），我再帮你分析。"
                )
                result = {**result, "answer": answer}
        except Exception as e:
            logger.exception("knowledge node failed")
            return {
                "answer": "知识检索暂时不可用，请稍后再试。",
                "task_type": "knowledge",
                "error": True,
                "error_code": "AI_RAG_ERROR",
                "message": str(e),
                "messages": [AIMessage(content="知识检索暂时不可用，请稍后再试。")],
            }
        return _merge_result(result, task_type="knowledge",
                             extra={"messages": [AIMessage(content=result.get("answer", ""))]})

    async def chitchat_node(state: AssistantState) -> dict:
        if llm is None:
            return {
                "answer": "AI 助手暂未配置，无法闲聊。",
                "task_type": "chitchat",
                "error": True,
                "error_code": "AI_LLM_NOT_CONFIGURED",
            }
        try:
            messages = _build_agent_messages(state)
            agent = _get_chitchat_agent()
            result = await agent.ainvoke(
                {"messages": messages},
                config={"configurable": {"thread_id": str(uuid4())}},
            )
            structured = result.get("structured_response")
            if structured is not None:
                answer = structured.answer
            else:
                # fallback：从 messages 最后一条 AI 消息提取文本
                last_ai = ""
                for m in reversed(result.get("messages", [])):
                    if isinstance(m, dict):
                        mtype = m.get("type", "")
                        if mtype == "ai" and m.get("content"):
                            last_ai = str(m.get("content", ""))
                            break
                    else:
                        mtype = getattr(m, "type", "")
                        if mtype == "ai":
                            content = getattr(m, "content", "")
                            if isinstance(content, str) and content.strip():
                                last_ai = content
                                break
                answer = last_ai or "嗯嗯，我在呢~"
        except Exception as e:
            logger.exception("chitchat node failed")
            return {
                "answer": "闲聊回复失败，请稍后再试。",
                "task_type": "chitchat",
                "error": True,
                "error_code": "AI_CHITCHAT_ERROR",
                "message": str(e),
                "messages": [AIMessage(content="闲聊回复失败，请稍后再试。")],
            }
        return {
            "answer": answer,
            "task_type": "chitchat",
            "messages": [AIMessage(content=answer)],
        }

    async def unknown_node(state: AssistantState) -> dict:
        msg = "我可以帮你找商品、推荐，或回答商品知识问题，请告诉我你的需求。"
        return {
            "answer": msg,
            "task_type": "unknown",
            "messages": [AIMessage(content=msg)],
        }

    def format_response(state: AssistantState) -> dict:
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
        return {"result": result}

    return {
        "shopping_node": shopping_node,
        "knowledge_node": knowledge_node,
        "chitchat_node": chitchat_node,
        "unknown_node": unknown_node,
        "format_response": format_response,
    }


def _build_agent_messages(state: AssistantState) -> list:
    """从共享 state 构建传给子 agent 的消息列表。

    子 agent（knowledge/shopping/chitchat）通过 create_agent 运行，需要 {"messages": [...]} 格式。
    这里从 state["messages"] 中提取，带上完整对话历史，实现多 agent 共享记忆。
    """
    messages = state.get("messages") or []
    out = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
            continue
        mtype = getattr(m, "type", "")
        content = getattr(m, "content", "")
        if isinstance(content, str) and content.strip():
            if mtype == "human":
                out.append(HumanMessage(content=content))
            elif mtype == "ai":
                out.append(AIMessage(content=content))
    return out


def _merge_result(result: Dict[str, Any], *, task_type: str,
                  extra: Dict[str, Any] = None) -> dict:
    merged: Dict[str, Any] = {}
    for key in ("answer", "product_cards", "sources", "tool_calls", "error", "error_code", "message"):
        if key in result:
            merged[key] = result[key]
    merged.setdefault("answer", "")
    merged.setdefault("task_type", result.get("task_type") or task_type)
    merged.setdefault("product_cards", [])
    merged.setdefault("sources", [])
    merged.setdefault("tool_calls", [])
    merged.setdefault("error", False)
    if extra:
        merged.update(extra)
    return merged


def _history_messages(state: AssistantState) -> list:
    """构建传给 ShoppingAgent 的历史消息列表（dict 格式）。"""
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