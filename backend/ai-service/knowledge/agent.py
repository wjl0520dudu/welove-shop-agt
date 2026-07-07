# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import json
from uuid import uuid4
from typing import List

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool

from agents.middleware import build_summarization_middleware
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


def _extract_sources(messages: list) -> list:
    """从 search_knowledge 工具的 ToolMessage 里抽取 sources。

    search_knowledge 返回 {"knowledge_context":..., "sources":[{"title","score"}], ...}，
    LangChain 把它 JSON 序列化进 ToolMessage.content，这里解析回来。
    去 ToolStrategy 后 sources 不再由结构化输出提供，改由这里抽取。
    """
    sources: list = []
    for m in messages or []:
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str) or not content:
            continue
        try:
            data = json.loads(content)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict):
            continue
        for s in data.get("sources") or []:
            if isinstance(s, dict):
                sources.append({"title": s.get("title"), "score": s.get("score")})
    return sources


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
    """知识问答 agent：create_agent + search_knowledge 工具，answer 走纯文本流式（无结构化输出，sources 从 ToolMessage 抽取）。

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
            # 去掉 response_format=ToolStrategy：原先是它和 ToolCallLimitMiddleware("end")
            # 打架导致 GraphRecursionError——ToolStrategy 注册的结构化输出工具也算"其他工具"，
            # 触发 tool_call_limit.py 的 NotImplementedError / jump_to:end 后
            # structured_response=None → 走错误分支"知识检索暂时不可用"。去掉后两者不再冲突。
            #
            # ToolCallLimit 改 continue：search_knowledge 最多 2 次，超限后注入错误
            # ToolMessage 提示模型"别再调了"，让模型用已检索内容组织回答（而非硬停）。
            # ModelCallLimit 作为硬顶兜底，防弱模型真的死循环；recursion_limit 再兜一层。
            self._agent = create_agent(
                model=self._llm,
                checkpointer=_knowledge_checkpointer,
                system_prompt=KNOWLEDGE_PROMPT,
                tools=[search_knowledge],
                middleware=[
                    build_summarization_middleware(),
                    ToolCallLimitMiddleware(
                        tool_name="search_knowledge",
                        run_limit=2,
                        exit_behavior="continue",
                    ),
                    ModelCallLimitMiddleware(run_limit=5, exit_behavior="end"),
                ],
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

        # 每次调用使用唯一 thread_id，确保不受内部 tool_call 消息污染。
        # recursion_limit=12：高于 ModelCallLimit(5) 的 ~10 步，让 ModelCallLimit 先干净退出。
        result = await self._get_agent().ainvoke(
            {"messages": messages},
            config={
                "configurable": {"thread_id": str(uuid4())},
                "recursion_limit": 12,
            },
        )

        # answer 从最后一条 AI 消息 content 提取（纯文本，可流式）；
        # sources 从 search_knowledge 的 ToolMessage 里 JSON 解析抽取。
        result_messages = result.get("messages", [])
        answer = ""
        for m in reversed(result_messages):
            if getattr(m, "type", "") == "ai":
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    answer = content
                    break
        sources = _extract_sources(result_messages)

        output = {
            "answer": answer or "知识检索暂时不可用，请稍后再试。",
            "sources": sources,
            "confidence": 0.7 if sources else 0.3,
            "has_answer": bool(sources),
            "task_type": "knowledge",
        }

        # 存入缓存
        if cache_key:
            _knowledge_cache[cache_key] = output

        return output