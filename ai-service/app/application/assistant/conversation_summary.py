"""LLM-backed compression for the persisted visible conversation prefix.

This module deliberately knows nothing about LangGraph runtime messages, tool
calls, DAG state, or business Store memory. chat-service owns persistence and
sends only user-visible user/assistant messages. The resulting text can then
be safely injected into both Router and ChitchatAgent as the same system
context on the next turn.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from langchain_core.messages import HumanMessage, SystemMessage


ROLLING_SUMMARY_PROMPT = """你负责维护电商导购对话的“已发生对话摘要”。

输入包含：旧摘要，以及一批按时间顺序新增、但已经不再保留原文的用户—助手可见消息。
请将两者合并为一份可供下一轮 Router 和 Chitchat 共用的简洁中文摘要。

只记录确实出现在输入中的内容：
- 用户明确需求、约束和稳定偏好；
- 已推荐/正在讨论的商品及其顺序、商品卡中可见的名称与关键事实；
- 已确认的知识结论、已完成或待继续的问题；
- 让“第一款”“它”“刚才的问题”等后续表达可被理解的必要上下文。

绝不记录或猜测：工具调用、检索过程、候选筛选、模型判断、DAG、系统提示词、内部 ID、未证实商品事实。
若新消息与旧摘要矛盾，以较新的消息为准。不要回答用户，不要加标题、寒暄、Markdown 代码块；只输出摘要正文。
"""


def normalize_visible_summary_messages(messages: Iterable[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    """Keep only serializable, user-visible facts from chat-service messages."""
    normalized: list[dict[str, Any]] = []
    for raw in messages:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        elif hasattr(raw, "dict"):
            raw = raw.dict()
        if not isinstance(raw, Mapping):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(raw.get("content") or "").strip()
        image_url = str(raw.get("image_url") or raw.get("imageUrl") or "").strip()
        cards = raw.get("product_cards") or raw.get("productCards") or []
        visible_cards: list[dict[str, Any]] = []
        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, Mapping):
                    continue
                visible_cards.append({
                    key: card.get(key)
                    for key in ("title", "brand", "price", "base_price", "sub_category", "reason")
                    if card.get(key) not in (None, "")
                })
        if not content and not image_url and not visible_cards:
            continue
        item: dict[str, Any] = {"role": role, "content": content}
        if image_url:
            item["image_url"] = image_url
        if visible_cards:
            item["product_cards"] = visible_cards
        normalized.append(item)
    return normalized


def _as_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, Mapping)
        ).strip()
    return str(content or "").strip()


def _bound_summary(text: str, max_chars: int) -> str:
    value = str(text or "").strip().strip("`")
    if len(value) <= max_chars:
        return value
    # Keep a valid, compact persisted string even if a provider ignores the
    # output limit. The next rolling call can still merge it with newer facts.
    return value[:max_chars].rstrip()


async def build_rolling_summary(
    llm: Any,
    *,
    previous_summary: str,
    messages: Iterable[Mapping[str, Any] | Any],
    max_chars: int,
    run_config: Mapping[str, Any] | None = None,
) -> str:
    """Merge a persisted prefix summary with newly eligible visible messages."""
    visible = normalize_visible_summary_messages(messages)
    old_summary = str(previous_summary or "").strip()
    if not visible:
        return _bound_summary(old_summary, max_chars)

    payload = json.dumps(
        {"旧摘要": old_summary or "（无）", "新增可见消息": visible},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content=ROLLING_SUMMARY_PROMPT),
            HumanMessage(content=(
                f"请在不超过 {max_chars} 个中文字符内输出合并摘要。\n"
                f"输入：{payload}"
            )),
        ],
        config={
            **dict(run_config or {}),
            "run_name": "assistant.rolling-summary",
            "tags": [*list((run_config or {}).get("tags") or []), "system:rolling-summary"],
        },
    )
    return _bound_summary(_as_text(response), max_chars)
