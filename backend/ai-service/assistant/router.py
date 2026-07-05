from __future__ import annotations
import json
import logging
import re
from typing import Any, Dict, List
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from agents.schemas import IntentDecision
from agents.prompts import ROUTER_PROMPT

logger = logging.getLogger("ai-service.router")

# 兜底规则关键词（按命中优先级）
_SHOPPING_WORDS = ("推荐", "买", "找商品", "商品", "防晒", "面霜", "口红", "精华",
                  "比较", "对比", "哪个好", "性价比", "便宜", "预算", "销量", "评分")
_KNOWLEDGE_WORDS = ("成分", "怎么用", "用法", "区别", "是什么", "为什么", "原理",
                   "功效", "副作用", "科普", "知识", "适合什么", "可以吗")
_CHITCHAT_WORDS = ("你好", "hello", "hi", "在吗", "谢谢", "再见", "哈喽", "嗨")


ROUTER_CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ROUTER_PROMPT + "\n\n格式要求：只输出一段 JSON 文本，不要 markdown 代码块，不要解释。\n"
     "字段：{{\"task_type\":\"shopping|knowledge|chitchat|unknown\",\"confidence\":0.0,\"reason\":\"简短理由\"}}"),
    ("human", "最近对话：\n{history}\n\n业务记忆：{business_memory}\n\n本次问题：{question}"),
])


async def classify_intent(llm, *, question: str, messages: List[Dict[str, Any]],
                          business_memory: Dict[str, Any]) -> IntentDecision:
    """LangChain 管道式路由：ROUTER_CHAT_PROMPT | llm | StrOutputParser -> 解析 JSON -> 规则兜底。

    完全不依赖模型原生 function calling / structured output，对所有 OpenAI 兼容代理通用。
    """
    if llm is None:
        return IntentDecision(task_type="unknown", reason="llm not configured")

    history_text = _format_recent_messages(messages, limit=8)
    memory_text = json.dumps(business_memory, ensure_ascii=False)

    chain = ROUTER_CHAT_PROMPT | llm | StrOutputParser()
    try:
        raw = await chain.ainvoke({
            "history": history_text,
            "business_memory": memory_text,
            "question": question,
        })
    except Exception as e:
        logger.warning("router chain ainvoke failed, fallback to rules: %s", e)
        return _rule_based_intent(question, messages, business_memory)

    decision = _parse_router_text(raw, question, messages, business_memory)
    if decision is None:
        logger.warning("router output not parseable, fallback to rules: %s", (raw or "")[:200])
        return _rule_based_intent(question, messages, business_memory)
    return decision


def _parse_router_text(raw: str, question: str, messages: List[Dict[str, Any]],
                        business_memory: Dict[str, Any]):
    """把模型文本（可能含 JSON / 代码块 / 多余文字）解析成 IntentDecision。"""
    text = (raw or "").strip()
    if not text:
        return None
    # 去 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    # 直接 json.loads
    try:
        p = json.loads(text)
        return _to_intent_decision(p) if isinstance(p, dict) else None
    except Exception:
        pass
    # 抽第一个 JSON 对象
    match = re.search(r"\{[\s\S]*?\}", text)
    if not match:
        return None
    try:
        p = json.loads(match.group(0))
        return _to_intent_decision(p) if isinstance(p, dict) else None
    except Exception:
        return None


def _to_intent_decision(data: Dict[str, Any]):
    task_type = str(data.get("task_type", "unknown")).lower().strip()
    if task_type not in ("shopping", "knowledge", "chitchat", "unknown"):
        # 历史残留 cart/plan_execute 等不认识，统一 unknown
        task_type = "unknown"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return IntentDecision(task_type=task_type, confidence=confidence,
                          reason=str(data.get("reason", "")))


def _rule_based_intent(question: str, messages: List[Dict[str, Any]],
                       business_memory: Dict[str, Any]) -> IntentDecision:
    """无 LLM 或解析失败时的兜底分类：上下文优先（结合记忆）+关键词命中。"""
    text = (question or "").lower()
    # 上下文：上一轮已推荐过商品 -> 本轮更可能是 shopping（如"第二个怎么样"）
    last_cards = business_memory.get("last_product_cards") or []
    if last_cards and re.search(r"第.个|这个|那个|刚.{0,2}个", question or ""):
        return IntentDecision(task_type="shopping", confidence=0.6,
                              reason="rule: reference to previous product cards")
    score = {"shopping": 0, "knowledge": 0, "chitchat": 0}
    for w in _SHOPPING_WORDS:
        if w in text:
            score["shopping"] += 2
    for w in _KNOWLEDGE_WORDS:
        if w in text:
            score["knowledge"] += 2
    for w in _CHITCHAT_WORDS:
        if w in text:
            score["chitchat"] += 3
    best = max(score, key=score.get)
    if score[best] <= 0:
        return IntentDecision(task_type="unknown", confidence=0.3, reason="rule: no keyword hit")
    return IntentDecision(task_type=best, confidence=0.5, reason=f"rule: keyword hit {best}")


def _format_recent_messages(messages: List[Dict[str, Any]], limit: int = 8) -> str:
    """把最近 limit 条消息拼成 "user: ... / assistant: ..." 文本，供 router 参考。"""
    if not messages:
        return "（暂无历史）"
    role_map = {"user": "用户", "assistant": "助手", "system": "系统"}
    lines = []
    for msg in messages[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = role_map.get(msg.get("role", ""), msg.get("role", "?"))
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        content = str(content).strip()
        if not content:
            continue
        if len(content) > 500:
            content = content[:500] + "…"
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "（暂无历史）"
