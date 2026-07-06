"""跨 Agent 共享的业务记忆模块（全 async 接口）。

数据按生命周期分两层存储：

- **会话级** `("conversations", cid, "business")`：
  - last_product_cards：最近推荐的商品卡片
  - last_focused_product：用户当前关注的商品
  - pending_cart_action：待确认的购物车操作

- **用户级** `("users", uid, "profile")`：
  - user_preferences：肤质、性别、预算偏好等长期画像

`get_business_memory` 同时读两处并合并，让 agent 拿到一个平铺的视图，
不用关心内部分层。

## 为什么全 async

底层 store 是 AsyncPostgresStore（Linux 生产环境用），同步 put/get 从 async
上下文调用可能触发 event loop 死锁。全项目本来就是 async 风格，这里跟着 async 化
最稳。降级用的 InMemoryStore 也同时支持 aput/aget，接口统一。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.runtime import get_store


# ---- namespace helpers ----------------------------------------------------

def _conversation_ns(conversation_id: Optional[str]) -> tuple[str, str, str]:
    """会话级 namespace：cards / focused / pending_cart 存这里。"""
    cid = str(conversation_id or "default")
    return ("conversations", cid, "business")


def _user_ns(user_id: Optional[int | str]) -> tuple[str, str, str]:
    """用户级 namespace：user_preferences 存这里，跨会话持久化。"""
    uid = str(user_id or "anonymous")
    return ("users", uid, "profile")


async def _get_conversation(conversation_id: Optional[str]) -> dict:
    item = await get_store().aget(_conversation_ns(conversation_id), "memory")
    if item is None:
        return {}
    return item.value if isinstance(item.value, dict) else {}


async def _set_conversation(conversation_id: Optional[str], data: dict) -> None:
    await get_store().aput(_conversation_ns(conversation_id), "memory", data)


async def _get_user(user_id: Optional[int | str]) -> dict:
    item = await get_store().aget(_user_ns(user_id), "profile")
    if item is None:
        return {}
    return item.value if isinstance(item.value, dict) else {}


async def _set_user(user_id: Optional[int | str], data: dict) -> None:
    await get_store().aput(_user_ns(user_id), "profile", data)


# ---- 对外 API -------------------------------------------------------------

async def get_business_memory(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
) -> dict:
    """获取当前会话可用的业务记忆（会话级 + 用户级合并）。

    合并后是一个平铺 dict：
        {
            "last_product_cards": [...],      # 会话级
            "last_focused_product": {...},    # 会话级
            "pending_cart_action": {...},     # 会话级
            "user_preferences": {...},         # 用户级
        }
    """
    conv = await _get_conversation(conversation_id)
    user = await _get_user(user_id)
    merged = dict(conv)
    if user:
        merged["user_preferences"] = user
    return merged


async def remember_product_cards(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    cards: List[Dict[str, Any]],
) -> None:
    """记住最近推荐的商品卡片（会话级）。"""
    if not cards:
        return
    memory = await _get_conversation(conversation_id)
    memory["last_product_cards"] = cards
    await _set_conversation(conversation_id, memory)


async def remember_focused_product(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    card: Dict[str, Any],
) -> None:
    """记住用户当前关注/选中的单个商品（会话级）。"""
    if not card:
        return
    memory = await _get_conversation(conversation_id)
    memory["last_focused_product"] = card
    await _set_conversation(conversation_id, memory)


async def remember_pending_cart_action(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    action: Dict[str, Any],
) -> None:
    """记住待确认的购物车操作（会话级）。"""
    if not action:
        return
    memory = await _get_conversation(conversation_id)
    memory["pending_cart_action"] = action
    await _set_conversation(conversation_id, memory)


async def clear_pending_cart_action(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
) -> None:
    """清除待确认的购物车操作（会话级）。"""
    memory = await _get_conversation(conversation_id)
    memory.pop("pending_cart_action", None)
    await _set_conversation(conversation_id, memory)


async def remember_user_preferences(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    preferences: Dict[str, Any],
) -> None:
    """记住用户偏好（用户级，跨会话持久化）。

    conversation_id 参数保留是为了 API 一致性，实际按 user_id 存储。
    """
    if not preferences:
        return
    existing = await _get_user(user_id)
    existing.update(preferences)
    await _set_user(user_id, existing)
