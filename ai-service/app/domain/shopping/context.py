"""构造 ShoppingContext —— 每个高层 Tool 的第一步。

Router 已经完成跨轮上下文理解。本模块只从 ToolRuntime.state 组装最小
Shopping 执行上下文，避免 Capability 再从 Store 读取历史商品卡并进行第二次
指代消解。

## 为什么单独一个模块
- 每个高层 Tool（recommend/compare/detail/user_context）都要做同样的事；
- 集中在一处能给 Tool docstring 让 LLM 看到"你不用管 state"；
- Phase 1b 上 Milvus 后如果要多注入什么（例如 tenant_id），只改这里。
"""

from __future__ import annotations

from typing import Any, Dict

from langgraph.prebuilt import ToolRuntime

from app.domain.shopping.schemas import ShoppingContext


async def build_shopping_context_from_runtime(runtime: ToolRuntime) -> ShoppingContext:
    """从 ToolRuntime.state 组装 ShoppingContext。

    Capability 只依赖 ShoppingContext，不再直接读 runtime.state，
    单测时可以直接 mock 一个 ShoppingContext 传进去。
    """
    state: Dict[str, Any] = dict(runtime.state or {})

    conversation_id = state.get("conversation_id")
    user_id = state.get("user_id")
    jwt_token = state.get("jwt_token")
    run_id = state.get("run_id")

    injected_memory = state.get("business_memory")
    memory = dict(injected_memory) if isinstance(injected_memory, dict) else {}
    selected_ids = state.get("selected_product_ids")
    if not isinstance(selected_ids, list):
        selected_ids = memory.get("selected_product_ids") or []
    input_mode = str(state.get("input_mode") or "text")
    if input_mode not in {"text", "image", "multimodal"}:
        input_mode = "text"

    return ShoppingContext(
        conversation_id=conversation_id,
        user_id=user_id,
        jwt_token=jwt_token,
        run_id=run_id,
        is_logged_in=bool(user_id),
        business_memory=memory,
        # Historical cards/focus are intentionally not injected into a domain
        # tool. Router has already turned any valid reference into these ids.
        last_product_cards=[],
        selected_product_ids=_normalise_selected_product_ids(selected_ids),
        last_focused_product=None,
        user_preferences=dict(memory.get("user_preferences") or {}),
        image_url=str(state.get("image_url") or "").strip() or None,
        input_mode=input_mode,
    )


def _normalise_selected_product_ids(values: Any) -> list[int]:
    """Keep Router binding order while ignoring invalid and duplicate ids."""
    ids: list[int] = []
    for value in values if isinstance(values, list) else []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in ids:
            ids.append(product_id)
    return ids
