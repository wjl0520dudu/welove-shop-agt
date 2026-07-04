from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

_memory: dict[str, dict[str, Any]] = {}


def memory_key(conversation_id: Optional[str], user_id: Optional[int] = None) -> str:
    if conversation_id:
        return str(conversation_id)
    if user_id is not None:
        return f"user-{user_id}"
    return "anonymous"


def get_business_memory(conversation_id: Optional[str], user_id: Optional[int] = None) -> dict[str, Any]:
    key = memory_key(conversation_id, user_id)
    return deepcopy(_memory.get(key, {}))


def update_business_memory(conversation_id: Optional[str], user_id: Optional[int] = None, **updates: Any) -> dict[str, Any]:
    key = memory_key(conversation_id, user_id)
    current = _memory.setdefault(key, {})
    for name, value in updates.items():
        if value is not None:
            current[name] = deepcopy(value)
    return deepcopy(current)


def remember_product_cards(conversation_id: Optional[str], user_id: Optional[int], cards: list[dict]) -> dict[str, Any]:
    if not cards:
        return get_business_memory(conversation_id, user_id)
    first = cards[0] if isinstance(cards[0], dict) else None
    return update_business_memory(
        conversation_id,
        user_id,
        last_product_cards=cards,
        last_focused_product=first,
    )


def remember_focused_product(conversation_id: Optional[str], user_id: Optional[int], product: Optional[dict]) -> dict[str, Any]:
    if not product:
        return get_business_memory(conversation_id, user_id)
    return update_business_memory(conversation_id, user_id, last_focused_product=product)


def remember_pending_cart_action(conversation_id: Optional[str], user_id: Optional[int], action: Optional[dict]) -> dict[str, Any]:
    return update_business_memory(conversation_id, user_id, pending_cart_action=action)


def clear_pending_cart_action(conversation_id: Optional[str], user_id: Optional[int]) -> dict[str, Any]:
    key = memory_key(conversation_id, user_id)
    current = _memory.setdefault(key, {})
    current.pop("pending_cart_action", None)
    return deepcopy(current)


def clear_business_memory() -> None:
    _memory.clear()