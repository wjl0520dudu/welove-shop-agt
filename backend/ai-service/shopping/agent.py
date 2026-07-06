from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.memory import get_business_memory
from agents.prompts import SHOPPING_AGENT_PROMPT
from agents.schemas import ShoppingResult
from agents.state import ShoppingAgentState
from agents.middleware import (
    PreferenceLearningMiddleware,
    build_summarization_middleware,
)
from tools.shopping_tools import SHOPPING_TOOLS
from tools.user_tools import USER_TOOLS

# ShoppingAgent 使用的全部工具：商品搜索/详情/对比 + 用户维度（收藏/浏览/订单）
_ALL_TOOLS = SHOPPING_TOOLS + USER_TOOLS

# ShoppingAgent 专用 middleware：长对话压缩 + 偏好学习
_SHOPPING_MIDDLEWARE = [
    build_summarization_middleware(),
    PreferenceLearningMiddleware(),
]

logger = logging.getLogger("ai-service.shopping.agent")

# ShoppingAgent 专用独立 checkpointer，与主图 checkpointer 完全隔离。
# 原因同 router/knowledge：create_agent 内部的工具调用会往 checkpointer 写消息，
# 若用共享 checkpointer + 同一 thread_id，上一轮的 tool_call 消息会混入下一轮，LLM 被污染。
_shopping_checkpointer = InMemorySaver()


class ShoppingAgent:
    """导购 agent：create_agent + 模块级工具 + ShoppingResult 结构化输出。

    ## ToolRuntime 模式（教程 05）
    - 工具是模块级常量 SHOPPING_TOOLS（无需每次请求重建）
    - conversation_id / user_id 通过 ShoppingAgentState 传入，工具从 runtime.state 读
    - state_schema=ShoppingAgentState 让 create_agent 认识扩展字段

    ## 为什么 agent 不是完全单例
    system_prompt 依赖每次调用时的最新 business_memory（`last_product_cards`
    等），所以 `create_agent` 每次 run 时重建。工具已经是单例了，重建成本很低。

    ## 独立 checkpointer
    与 router/knowledge 相同：避免内部 tool_call 消息污染下一轮。每次调用
    生成唯一 uuid thread_id，state 完全干净。
    """

    def __init__(self, llm):
        self._llm = llm

    def _build_system_prompt(self, business_memory: Dict[str, Any]) -> str:
        """把业务记忆注入 system prompt，让 agent 能解析历史指代（第二个、刚才那个）。

        业务记忆来自 agents.memory 的 Store（AsyncPostgresStore / InMemoryStore），
        跨 shopping / cart agent 共享：last_product_cards / last_focused_product /
        user_preferences。
        """
        memory_lines: List[str] = []
        last_cards = business_memory.get("last_product_cards") or []
        if last_cards:
            memory_lines.append(
                "上一轮推荐商品：\n"
                + json.dumps(last_cards, ensure_ascii=False, indent=2)
            )
        focused = business_memory.get("last_focused_product")
        if focused:
            memory_lines.append("当前关注商品：" + json.dumps(focused, ensure_ascii=False))
        prefs = business_memory.get("user_preferences") or {}
        if prefs:
            memory_lines.append("用户偏好：" + json.dumps(prefs, ensure_ascii=False))
        memory_block = "\n\n".join(memory_lines) if memory_lines else "（暂无历史推荐）"
        return f"{SHOPPING_AGENT_PROMPT}\n\n## 业务记忆\n{memory_block}"

    def _build_messages(
        self, question: str, messages: List[Dict[str, Any]]
    ) -> list:
        """把 supervisor 传入的对话历史（dict 格式）转成 langchain message 对象。

        主图 run() 初始化时已将当前 question 写入 state["messages"]，
        _history_messages 原样透传，这里只做格式转换，不再重复追加。
        """
        out: list = []
        for m in messages or []:
            if not isinstance(m, dict):
                # 已经是 message 对象（HumanMessage / AIMessage），直接保留
                out.append(m)
                continue
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            content = str(content).strip()
            if not content:
                continue
            if role == "user":
                out.append(HumanMessage(content=content))
            elif role == "assistant":
                out.append(AIMessage(content=content))
            elif role == "system":
                out.append(SystemMessage(content=content))
        return out

    async def run(
        self,
        *,
        question: str,
        messages: List[Dict[str, Any]],
        business_memory: Dict[str, Any],
        conversation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        jwt_token: Optional[str] = None,
    ) -> dict:
        """执行导购推荐。

        Args:
            question: 当前用户问题。
            messages: 来自 supervisor 共享记忆的对话历史（dict 格式）。
            business_memory: 业务记忆（last_product_cards / last_focused_product / user_preferences）。
            conversation_id: 会话 ID，用于业务记忆隔离。
            user_id: 用户 ID。

        Returns:
            包含 answer、product_cards、task_type 等字段的字典，
            字段与 assistant/nodes.py 的 _merge_result 期望一致。
        """
        if self._llm is None:
            return {
                "answer": "导购 Agent 暂不可用。",
                "task_type": "shopping",
                "error": True,
                "error_code": "AI_LLM_NOT_CONFIGURED",
            }

        # 从 Store 读取业务记忆（跨 shopping/cart agent 共享）
        # supervisor 传入的 business_memory 参数优先级更高（如果有值就覆盖 Store 值）。
        store_memory = await get_business_memory(conversation_id, user_id)
        effective_memory = {**store_memory, **business_memory} if business_memory else store_memory

        system_prompt = self._build_system_prompt(effective_memory)

        # create_agent 每次重建：system_prompt 依赖本次记忆快照，工具已单例复用。
        agent = create_agent(
            model=self._llm,
            checkpointer=_shopping_checkpointer,
            system_prompt=system_prompt,
            tools=_ALL_TOOLS,
            state_schema=ShoppingAgentState,
            middleware=_SHOPPING_MIDDLEWARE,
            response_format=ToolStrategy(ShoppingResult),
        )

        agent_messages = self._build_messages(question, messages)

        try:
            # 关键点：把 conversation_id / user_id / jwt_token 塞进 state，
            # 让工具通过 ToolRuntime.state 读取（jwt_token 用于 user_tools 调 Java）
            result = await agent.ainvoke(
                {
                    "messages": agent_messages,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "jwt_token": jwt_token,
                },
                config={"configurable": {"thread_id": str(uuid4())}},
            )
        except Exception as e:
            logger.exception("ShoppingAgent ainvoke failed")
            return {
                "answer": "导购 Agent 处理失败，请稍后再试。",
                "task_type": "shopping",
                "error": True,
                "error_code": "AI_SHOPPING_ERROR",
                "message": str(e),
            }

        structured = result.get("structured_response")
        if structured is None:
            # fallback：从最后一条 AI 消息提取文本（部分代理不支持结构化输出时）
            answer = ""
            for m in reversed(result.get("messages", [])):
                mtype = getattr(m, "type", "")
                if mtype == "ai":
                    content = getattr(m, "content", "")
                    if isinstance(content, str) and content.strip():
                        answer = content
                        break
            return {
                "answer": answer or "暂时没能找到合适的商品，能再说详细一点吗？",
                "product_cards": [],
                "task_type": "shopping",
                "sources": [],
                "tool_calls": [],
                "error": False,
            }

        return {
            "answer": structured.answer,
            "product_cards": structured.product_cards or [],
            "task_type": "shopping",
            "need_followup": getattr(structured, "need_followup", False),
            "followup_question": getattr(structured, "followup_question", None),
            "confidence": getattr(structured, "confidence", 0.5),
            "sources": [],
            "tool_calls": [],
            "error": False,
        }
