from __future__ import annotations
from typing import Any, Dict, List, Optional
from agents.runtime import store


def _key(conversation_id: Optional[str], user_id: Optional[int]) -> tuple:
    if user_id is not None:
        return ("user", str(user_id))
    if conversation_id:
        return ("conv", str(conversation_id))
    return ("anon", "anon")


def get_business_memory(conversation_id: Optional[str], user_id: Optional[int] = None) -> Dict[str, Any]:
    ns = _key(conversation_id, user_id)
    items = store.search(ns, limit=50)
    memory: Dict[str, Any] = {}
    prefs: Dict[str, Any] = {}
    for item in items:
        item_key = getattr(item, "key", None) or ""
        item_value = getattr(item, "value", None) or {}
        if item_key.startswith("pref:"):
            prefs[item_key[5:]] = item_value
            continue
        memory[item_key] = item_value
    if prefs:
        memory["user_preferences"] = prefs
    return memory


def remember_product_cards(conversation_id, user_id, cards: List[dict]) -> None:
    if not cards:
        return
    ns = _key(conversation_id, user_id)
    store.put(ns, "last_product_cards", cards)


def remember_focused_product(conversation_id, user_id, product: Optional[dict]) -> None:
    if not product:
        return
    ns = _key(conversation_id, user_id)
    store.put(ns, "last_focused_product", product)


def remember_user_preference(conversation_id, user_id, key: str, value: Any) -> None:
    if not key:
        return
    ns = _key(conversation_id, user_id)
    store.put(ns, f"pref:{key}", value)


# ---- cart 库兼容：pending_cart_action 按 ns 存，供旧 cart_tools 使用 ----
def remember_pending_cart_action(conversation_id, user_id, action: Optional[dict]) -> None:
    if action is None:
        return
    ns = _key(conversation_id, user_id)
    store.put(ns, "pending_cart_action", action)


def clear_pending_cart_action(conversation_id, user_id) -> None:
    ns = _key(conversation_id, user_id)
    try:
        store.delete(ns, "pending_cart_action")
    except Exception:
        pass


def clear_business_memory() -> None:
    """清空所有业务记忆（测试用）。"""
    for first in ("user", "conv", "anon"):
        try:
            items = store.search((first,), limit=1000)
        except Exception:
            continue
        for item in items:
            item_key = getattr(item, "key", None)
            ns = getattr(item, "namespace", None)
            if item_key is None or ns is None:
                continue
            try:
                store.delete(ns, item_key)
            except Exception:
                pass
