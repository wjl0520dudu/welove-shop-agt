"""跨 Agent 共享的业务记忆模块（全 async 接口）。

数据按生命周期分两层存储：

- **会话级** `("conversations", cid, "business")`：
  - last_product_cards：最近推荐的商品卡片（shopping 侧）
  - last_focused_product：用户当前关注的商品（shopping 侧）
  - pending_cart_action：待确认的购物车操作
  - last_knowledge_entities：上一轮知识问答里出现的实体列表（knowledge 侧）
    例："烟酰胺和视黄醇能一起用吗" → ["烟酰胺", "视黄醇"]
    下一轮"第二个的成分是什么" → 通过 resolve_reference 命中 "视黄醇"

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


# ---- pending_shopping_need（多轮购物需求澄清）----------------------------

# 澄清超过这个轮数还没补全就丢弃 pending，避免旧状态污染新话题。
# 3 是经验值：正常用户 2 轮内就能补出品类；超过 3 轮说明话题已转移。
_MAX_PENDING_TURNS = 3


async def get_pending_shopping_need(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
) -> Optional[dict]:
    """读取会话级 pending_shopping_need；不存在返回 None。

    结构见 shopping.schemas.PendingShoppingNeed（避免循环 import 这里返回 dict）。
    """
    memory = await _get_conversation(conversation_id)
    pending = memory.get("pending_shopping_need")
    if not isinstance(pending, dict):
        return None
    # 超过最大轮数直接丢弃，返回 None 让上游走"新需求"路径
    if int(pending.get("turn_count") or 0) >= _MAX_PENDING_TURNS:
        memory.pop("pending_shopping_need", None)
        await _set_conversation(conversation_id, memory)
        return None
    return pending


async def remember_pending_shopping_need(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    pending: Dict[str, Any],
) -> None:
    """覆盖式写入 pending_shopping_need。

    调用方（RecommendCapability）负责保证 turn_count 递增。
    """
    if not pending:
        return
    memory = await _get_conversation(conversation_id)
    memory["pending_shopping_need"] = pending
    await _set_conversation(conversation_id, memory)


async def clear_pending_shopping_need(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
) -> None:
    """清除 pending_shopping_need（用户已经把需求说清楚了 / 话题切走）。"""
    memory = await _get_conversation(conversation_id)
    if memory.pop("pending_shopping_need", None) is not None:
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


# ---- 知识实体记忆（KnowledgeAgent 侧）------------------------------------

# 保留最近多少个实体。太多会让"第几个"这类序号指代变得不精准；太少又会
# 覆盖不到一轮内多次提到的实体。5 是经验值：一句话里通常最多 3-4 个成分名。
_MAX_KNOWLEDGE_ENTITIES = 5


async def remember_knowledge_entities(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
    entities: List[str],
) -> None:
    """记住上一轮知识问答里出现的实体（会话级）。

    实体来源：
    - 用户问题中被明确点名的对象（"烟酰胺"、"视黄醇"）
    - 检索到的 knowledge 片段里的关键实体（可选）

    覆盖式写入（不追加），只保留"最新一轮"的实体列表，避免跨轮混淆。
    去重保序 + 截断到 _MAX_KNOWLEDGE_ENTITIES 条。
    """
    if not entities:
        return

    # 去重保序：dict.fromkeys 天然做到
    unique = [e.strip() for e in entities if e and e.strip()]
    unique = list(dict.fromkeys(unique))[:_MAX_KNOWLEDGE_ENTITIES]
    if not unique:
        return

    memory = await _get_conversation(conversation_id)
    memory["last_knowledge_entities"] = unique
    await _set_conversation(conversation_id, memory)


async def clear_knowledge_entities(
    conversation_id: Optional[str],
    user_id: Optional[int | str],
) -> None:
    """清除会话级知识实体记忆（用户切换话题时用）。"""
    memory = await _get_conversation(conversation_id)
    memory.pop("last_knowledge_entities", None)
    await _set_conversation(conversation_id, memory)
