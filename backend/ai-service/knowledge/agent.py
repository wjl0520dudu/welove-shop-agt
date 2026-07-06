# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
from uuid import uuid4
from typing import List

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool

from agents.middleware import build_summarization_middleware
from agents.schemas import KnowledgeResult
from agents.prompts import KNOWLEDGE_PROMPT
from rag.models import RetrievalPlan
from rag.retriever import get_retriever


@tool
def search_knowledge(query: str) -> dict:
    """在知识库中检索与 query 相关的内容。返回检索到的知识片段和来源列表。
    使用时机：
    1. 收到用户知识类问题后，立即调用
    2. 把用户问题提炼为精准的检索查询词
    3. 如果一次检索不够，可以用不同的查询词再次检索
    """
    plan = RetrievalPlan(query=query, top_k=5, search_mode="hybrid")
    output = get_retriever().retrieve(plan)
    return {
        "knowledge_context": output.knowledge_context,
        "sources": [{"title": s.doc, "score": round(s.score, 3)} for s in output.sources],
        "total_results": len(output.results),
    }


# KnowledgeAgent 专用独立 checkpointer，与主图 checkpointer 完全隔离
# 原因同 router：create_agent 内部的工具调用会往 checkpointer 写消息，
# 如果用共享 checkpointer + 同一 thread_id，tool_call 消息会混入下一轮
_knowledge_checkpointer = InMemorySaver()

# 对话级知识缓存：key = f"{conversation_id}:{md5(question)}"，value = run() 返回结果。
# 同一问题在同一会话中不必重复 RAG。
#
# 用 TTLCache 而非普通 dict：
#   - maxsize=1024：单进程最多 1024 条，超出 LRU 淘汰
#   - ttl=1800（30 分钟）：条目自动过期，避免长时间运行内存膨胀
# 多 worker 部署时每个 worker 有独立缓存，命中率分摊但不影响正确性。
# 如果未来需要跨进程共享，把这个 cache 挪到 PostgresStore 里即可。
_knowledge_cache: TTLCache = TTLCache(maxsize=1024, ttl=1800)


class KnowledgeAgent:
    """知识问答 agent：create_agent + search_knowledge 工具 + KnowledgeResult 结构化输出。

    使用独立 checkpointer 确保 ainvoke 正常工作，每次调用传唯一 thread_id
    避免内部 tool_call 消息污染下一次调用。

    共享记忆通过 supervisor graph 的 state["messages"] 传入，
    agent 可以看到完整对话历史，从而理解上下文。

    对话级缓存：同一问题（hash 去重）直接返回缓存结果，避免重复 RAG。

    实例懒构造，直到首次调用时才创建底层 agent。
    """

    def __init__(self, llm):
        self._llm = llm
        self._agent = None

    def _get_agent(self):
        if self._agent is None:
            self._agent = create_agent(
                model=self._llm,
                checkpointer=_knowledge_checkpointer,
                system_prompt=KNOWLEDGE_PROMPT,
                tools=[search_knowledge],
                middleware=[build_summarization_middleware()],
                response_format=ToolStrategy(KnowledgeResult),
            )
        return self._agent

    async def run(self, *, messages: list, conversation_id: str = "") -> dict:
        """执行知识问答。

        Args:
            messages: 来自 supervisor 共享记忆的消息列表（含对话历史 + 当前问题）。
                      格式为 langchain_core.messages 对象列表。
            conversation_id: 可选，用于对话级缓存隔离。

        Returns:
            包含 answer、sources、confidence、task_type 等字段的字典。
        """
        if not messages:
            return {
                "answer": "没有收到任何问题。",
                "sources": [],
                "confidence": 0.0,
                "task_type": "knowledge",
                "error": True,
                "error_code": "AI_RAG_EMPTY_INPUT",
            }

        # 提取最后一条用户消息作为缓存 key
        question = ""
        for m in reversed(messages):
            mtype = getattr(m, "type", "")
            content = getattr(m, "content", "")
            if mtype == "human" and isinstance(content, str) and content.strip():
                question = content.strip()
                break

        # 对话级缓存：同一对话 + 同一问题，直接返回缓存
        cache_key = f"{conversation_id}:{hashlib.md5(question.encode()).hexdigest()}" if question else ""
        if cache_key and cache_key in _knowledge_cache:
            return _knowledge_cache[cache_key]

        # 每次调用使用唯一 thread_id，确保不受内部 tool_call 消息污染
        result = await self._get_agent().ainvoke(
            {"messages": messages},
            config={"configurable": {"thread_id": str(uuid4())}},
        )

        structured = result.get("structured_response")
        if structured is None:
            return {
                "answer": "知识检索暂时不可用，请稍后再试。",
                "sources": [],
                "confidence": 0.0,
                "task_type": "knowledge",
                "error": True,
                "error_code": "AI_RAG_STRUCTURED_ERROR",
            }

        output = {
            "answer": structured.answer,
            "sources": [s for s in structured.sources] if structured.sources else [],
            "confidence": getattr(structured, "confidence", 0.5),
            "has_answer": getattr(structured, "has_answer", True),
            "task_type": "knowledge",
        }

        # 存入缓存
        if cache_key:
            _knowledge_cache[cache_key] = output

        return output