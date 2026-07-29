"""构造 ShoppingContext —— 每个高层 Tool 的第一步。

把"从 ToolRuntime 拿 conv/user/jwt + 从 Store 拿 memory"这段样板集中在一处，
Capability 内部只面对 ShoppingContext（BaseModel），不再直接摸 runtime.state。

## 为什么单独一个模块
- 每个高层 Tool（recommend/compare/detail/user_context）都要做同样的事；
- 集中在一处能给 Tool docstring 让 LLM 看到"你不用管 state"；
- Phase 1b 上 Milvus 后如果要多注入什么（例如 tenant_id），只改这里。
"""

from __future__ import annotations

from typing import Any, Dict

from langgraph.prebuilt import ToolRuntime

from app.infrastructure.persistence.memory import get_business_memory
from app.domain.shopping.schemas import ShoppingContext


async def build_shopping_context_from_runtime(runtime: ToolRuntime) -> ShoppingContext:
    """从 ToolRuntime.state + Store 一次组装出 ShoppingContext。

    Capability 只依赖 ShoppingContext，不再直接读 runtime.state / Store，
    单测时可以直接 mock 一个 ShoppingContext 传进去。
    """
    state: Dict[str, Any] = dict(runtime.state or {})

    conversation_id = state.get("conversation_id")
    user_id = state.get("user_id")
    jwt_token = state.get("jwt_token")
    run_id = state.get("run_id")

    try:
        memory = await get_business_memory(conversation_id, user_id)
    except Exception:  # noqa: BLE001 —— Store 不可用时降级为空 memory，链路继续
        memory = {}
    # DAG 后置任务会把前置任务的结构化商品结果放在 task-local memory 中。
    # 显式注入优先于 Store，避免并发子任务对 last_product_cards 的覆盖顺序
    # 影响依赖任务的比较/详情能力。
    injected_memory = state.get("business_memory")
    if isinstance(injected_memory, dict):
        memory = {**memory, **injected_memory}

    return ShoppingContext(
        conversation_id=conversation_id,
        user_id=user_id,
        jwt_token=jwt_token,
        run_id=run_id,
        is_logged_in=bool(user_id),
        business_memory=memory,
        last_product_cards=list(memory.get("last_product_cards") or []),
        selected_product_ids=list(memory.get("selected_product_ids") or []),
        last_focused_product=memory.get("last_focused_product"),
        user_preferences=dict(memory.get("user_preferences") or {}),
    )
