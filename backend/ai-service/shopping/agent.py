from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from agents.memory import get_business_memory
from agents.prompts import SHOPPING_AGENT_PROMPT
from agents.state import ShoppingAgentState
from agents.middleware import build_summarization_middleware
from core.errors import ErrorCode
from shopping.high_level_tools import SHOPPING_HIGH_LEVEL_TOOLS

# Phase 1a 关键变更：LLM 只面对 4 个高层 tool，底层 12 个工具全部退到 Capability 内部。
# 见 shopping/high_level_tools.py 和 shopping/capabilities/*。
_ALL_TOOLS = SHOPPING_HIGH_LEVEL_TOOLS

# 保留 summarization middleware（长对话压缩）。
# PreferenceLearningMiddleware 依然禁用 —— after_model 触发太密，代价高。
_SHOPPING_MIDDLEWARE = [
    build_summarization_middleware(),
]

logger = logging.getLogger("ai-service.shopping.agent")

# ShoppingAgent 独立 checkpointer，跟主图/router/knowledge 隔离。
_shopping_checkpointer = InMemorySaver()


class ShoppingAgent:
    """导购 Agent —— Phase 1a 起使用高层 Capability Tool 模式。

    ## Phase 1a 变更（本 commit）
    - LLM 可见工具从 12 个 → 4 个高层 tool
    - product_cards 从 ToolMessage 抽取（不再无条件读 Store 兜底）
    - system_prompt 大幅精简（76 行控制指令 → 40 行工具描述）
    - 底层工具（search_products/get_product_detail/…）仍存在，但只作为
      Capability 内部函数被调用，不再挂给 LLM

    ## Phase 1b 计划（下个 commit）
    - shopping/retrieval.py 内部从 PgVectorStore 切到 ProductMilvusStore（三路 + rerank）
    - agent.py 零改动
    """

    def __init__(self, llm):
        self._llm = llm

    def _build_system_prompt(self, business_memory: Dict[str, Any]) -> str:
        """把业务记忆注入 system prompt。

        新 prompt 里已经不再让 LLM 自己解析指代词（那是 Capability 内部函数的活），
        但仍需要让 LLM 知道"上一轮有什么商品"，才能判断该走 compare/detail 还是
        重新 recommend。
        """
        memory_lines: List[str] = []
        last_cards = business_memory.get("last_product_cards") or []
        if last_cards:
            # 只保留每张卡的 id/title/price 供 LLM 判断有无历史候选
            slim = [
                {
                    "product_id": c.get("product_id"),
                    "title": c.get("title"),
                    "price": c.get("price"),
                }
                for c in last_cards[:5]
            ]
            memory_lines.append("上一轮推荐商品（供选择工具时参考，不要复制到回答里）：\n"
                                + json.dumps(slim, ensure_ascii=False, indent=2))
        focused = business_memory.get("last_focused_product")
        if focused:
            memory_lines.append(
                "当前关注商品："
                + json.dumps({
                    "product_id": focused.get("product_id"),
                    "title": focused.get("title"),
                }, ensure_ascii=False)
            )
        prefs = business_memory.get("user_preferences") or {}
        if prefs:
            memory_lines.append("用户偏好：" + json.dumps(prefs, ensure_ascii=False))
        pending = business_memory.get("pending_shopping_need")
        if pending:
            memory_lines.append(
                "有待补全的购物需求（如用户在回答上轮追问，请调 recommend_products，工具会自动合并）："
                + json.dumps({
                    "missing_slots": pending.get("missing_slots"),
                    "last_clarify_question": pending.get("last_clarify_question"),
                }, ensure_ascii=False)
            )
        memory_block = "\n\n".join(memory_lines) if memory_lines else "（暂无历史推荐）"
        return f"{SHOPPING_AGENT_PROMPT}\n\n## 业务记忆\n{memory_block}"

    def _build_messages(
        self, question: str, messages: List[Dict[str, Any]]
    ) -> list:
        """把 supervisor 传入的对话历史（dict）转成 langchain message 对象。"""
        out: list = []
        for m in messages or []:
            if not isinstance(m, dict):
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

        Returns:
            {"answer": str, "product_cards": [...], "task_type": "shopping",
             "sources": [], "tool_calls": [...], "error": bool}
        """
        if self._llm is None:
            return {
                "answer": "导购 Agent 暂不可用。",
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.LLM_NOT_CONFIGURED,
            }

        # 拿 Store memory + supervisor 传入的 business_memory 合并
        store_memory = await get_business_memory(conversation_id, user_id)
        effective_memory = {**store_memory, **business_memory} if business_memory else store_memory

        system_prompt = self._build_system_prompt(effective_memory)

        # create_agent 每次重建：system_prompt 依赖本次记忆快照。工具已单例。
        agent = create_agent(
            model=self._llm,
            checkpointer=_shopping_checkpointer,
            system_prompt=system_prompt,
            tools=_ALL_TOOLS,
            state_schema=ShoppingAgentState,
            middleware=_SHOPPING_MIDDLEWARE,
        )

        agent_messages = self._build_messages(question, messages)

        try:
            # recursion_limit=15：4 个高层 tool 场景下 3-5 步足够，15 是安全上限。
            result = await agent.ainvoke(
                {
                    "messages": agent_messages,
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "jwt_token": jwt_token,
                },
                config={
                    "configurable": {"thread_id": str(uuid4())},
                    "recursion_limit": 15,
                },
            )
        except Exception as e:
            logger.exception("ShoppingAgent ainvoke failed")
            # Store 兜底（可能 Capability 已经写过 last_product_cards）
            try:
                fallback_memory = await get_business_memory(conversation_id, user_id)
                fallback_cards = fallback_memory.get("last_product_cards") or []
            except Exception:  # noqa: BLE001
                fallback_cards = []
            return {
                "answer": (
                    "我已经为你找到了几款商品，但整理推荐语时遇到点问题。"
                    "你可以直接看下面的商品卡片，或者告诉我更具体的偏好我再帮你精选。"
                    if fallback_cards
                    else "导购 Agent 处理失败，请稍后再试。"
                ),
                "product_cards": fallback_cards,
                "task_type": "shopping",
                "error": True,
                "error_code": ErrorCode.SHOPPING_ERROR,
                "message": str(e),
            }

        collected_tool_calls = _extract_tool_calls(result.get("messages", []))

        # ★ Phase 1a 关键变更：product_cards 优先从最近一次 ToolMessage 抽取，
        # 而不是无条件读 Store —— 避免"对比/详情"轮次误带上一轮推荐卡片。
        # 只有 ToolMessage 里没有 product_cards（LLM 没调工具，纯闲聊）时才回读 Store。
        tool_result = _extract_high_level_tool_result(result.get("messages", []))
        if tool_result and "product_cards" in tool_result:
            product_cards = tool_result.get("product_cards") or []
        else:
            fallback_memory = await get_business_memory(conversation_id, user_id)
            product_cards = fallback_memory.get("last_product_cards") or []

        # answer 从最后一条 AI 消息 content 提取
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
            "product_cards": product_cards,
            "task_type": "shopping",
            "sources": [],
            "tool_calls": collected_tool_calls,
            "error": False,
        }


def _extract_tool_calls(messages: list) -> List[Dict[str, Any]]:
    """从 create_agent 的 result["messages"] 里抽取工具调用记录。"""
    out: List[Dict[str, Any]] = []
    for m in messages or []:
        tcs = getattr(m, "tool_calls", None)
        if not tcs:
            continue
        for tc in tcs:
            if isinstance(tc, dict):
                name = tc.get("name") or ""
                args = tc.get("args") or tc.get("arguments") or {}
            else:
                name = getattr(tc, "name", "") or ""
                args = getattr(tc, "args", None) or getattr(tc, "arguments", None) or {}
            if not name:
                continue
            out.append({"name": name, "args": args})
    return out


def _extract_high_level_tool_result(messages: list) -> Dict[str, Any]:
    """从消息列表里倒序找到最近一次 **高层 Tool** 返回的 dict。

    高层 Tool 返回的 JSON 里必定含 `action`（recommend/clarify/empty/compare/detail），
    用这个字段过滤掉旧的底层工具残留（如果消息 buffer 里混着的话）。
    """
    high_level_actions = {
        "recommend", "clarify", "empty", "compare", "detail"
    }
    for m in reversed(messages or []):
        if getattr(m, "type", "") != "tool":
            continue
        content = getattr(m, "content", "")
        if not content:
            continue
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("action") in high_level_actions:
            return data
    return {}
