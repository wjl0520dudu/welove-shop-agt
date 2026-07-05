from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from agents.prompts import SHOPPING_AGENT_PROMPT
from shopping.product_repository import ProductRepository
from shopping.recommender import ShoppingRecommender, shopping_state_to_result

logger = logging.getLogger("ai-service.shopping.agent")


class ShoppingAgent:
    """导购 agent：转发到 LCEL 管道版 ShoppingRecommender。

    不再使用 create_agent / response_format（依赖模型原生 function calling /
    structured output，部分 OpenAI 兼容代理不支持会 400）。
    ShoppingRecommender 用 INTENT_PROMPT | llm | StrOutputParser + JSON 文本解析
    + ANSWER_PROMPT | llm 的 LCEL 管道，对所有模型通用。
    """

    def __init__(self, llm, repository: Optional[ProductRepository] = None):
        self.llm = llm
        self.repository = repository or ProductRepository()
        # 懒构造：llm 为 None（未配置）时不建链，避免在调用时报更清晰的错误。
        self.recommender: Optional[ShoppingRecommender] = None

    async def run(self, *, question: str, messages: List[Dict[str, Any]],
                  business_memory: Dict[str, Any], conversation_id: Optional[str] = None,
                  user_id: Optional[int] = None) -> dict:
        if self.llm is None:
            return {"answer": "导购 Agent 暂不可用。", "task_type": "shopping", "error": True,
                    "error_code": "AI_LLM_NOT_CONFIGURED"}
        if self.recommender is None:
            self.recommender = ShoppingRecommender(self.llm, self.repository)

        context = _serialize_context(messages, business_memory)
        profile = business_memory.get("user_preferences") or {}
        try:
            state = await self.recommender.recommend(
                question=question,
                user_id=user_id,
                session_id=conversation_id,
                context=context,
                profile=profile,
            )
        except Exception as e:
            logger.exception("ShoppingRecommender.run failed")
            return {"answer": "导购 Agent 处理失败。", "task_type": "shopping", "error": True,
                    "error_code": "AI_SHOPPING_ERROR", "message": str(e)}

        result = shopping_state_to_result(state)
        # 统一补齐 nodes 期望的字段
        result.setdefault("task_type", "shopping")
        result.setdefault("sources", [])
        result.setdefault("tool_calls", [])
        result.setdefault("error", False)
        # 把导购 system prompt 的约束（禁编造、结合 last_product_cards）通过 context 注入已足够，
        # 这里不再二次拼接，避免重复影响 LCEL 链路输出。
        return result


def _serialize_context(messages: List[Dict[str, Any]], business_memory: Dict[str, Any]) -> str:
    """把对话历史 + 业务记忆拼成 recommender 需要的 context 文本。"""
    import json
    parts: List[str] = []
    last_cards = business_memory.get("last_product_cards")
    if last_cards:
        parts.append("上一轮推荐商品：" + json.dumps(last_cards, ensure_ascii=False))
    focused = business_memory.get("last_focused_product")
    if focused:
        parts.append("当前关注商品：" + json.dumps(focused, ensure_ascii=False))
    prefs = business_memory.get("user_preferences")
    if prefs:
        parts.append("用户偏好：" + json.dumps(prefs, ensure_ascii=False))
    role_map = {"user": "用户", "assistant": "助手", "system": "系统"}
    history_lines: List[str] = []
    for m in (messages or [])[-6:]:
        if not isinstance(m, dict):
            continue
        role = role_map.get(m.get("role", ""), m.get("role", "?"))
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        content = str(content).strip()
        if not content:
            continue
        if len(content) > 300:
            content = content[:300] + "…"
        history_lines.append(f"{role}: {content}")
    if history_lines:
        parts.append("最近对话：\n" + "\n".join(history_lines))
    return "\n\n".join(parts)
