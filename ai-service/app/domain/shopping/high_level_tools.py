"""ShoppingAgent 的高层 Tool 入口 —— LLM 只面对这 4 个。

## 关键约束
- 每个 Tool 的 docstring 是 LLM 判断"用哪个"的重要依据，必须清楚写：
  - 适用场景
  - 不适用场景
  - Args / Returns
- Tool 内部只做参数收敛 + 结果 dump，业务逻辑在 Capability。
- 每个 Tool 的返回都是 `dict`（LangChain @tool 要求可 JSON 序列化）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from app.domain.shopping.capabilities import (
    CompareCapability,
    DetailCapability,
    RecommendCapability,
    UserShoppingContextCapability,
)
from app.domain.shopping.context import build_shopping_context_from_runtime

logger = logging.getLogger("ai-service.shopping.high_level_tools")


# ---- Tool 1: recommend_products -----------------------------------------

@tool(parse_docstring=True)
async def recommend_products(
    runtime: ToolRuntime,
    query: str,
    limit: int = 3,
) -> dict:
    """发现或推荐新的真实商城商品，支持文本、纯图片和图文需求。

    仅用于找新商品或筛选商品；比较已绑定商品和查询单品详情应使用对应工具。
    具体工作方法由 ``discover-products`` Skill 提供。

    Args:
        query: Router 已消解指代后的完整商品需求。
        limit: 返回商品卡片数量，默认 3。

    Returns:
        包含 action、product_cards、ranked_products、requested_limit、
        returned_count、clarify_question 和 empty_reason 的结构化结果。
    """
    context = await build_shopping_context_from_runtime(runtime)
    result = await RecommendCapability().run(query=query, context=context, limit=limit)
    # CandidateSet and trace are internal observability artifacts. Exposing
    # rejected candidates to the final Agent lets it mention products that the
    # user will never see as cards and also needlessly enlarges the prompt.
    payload = result.model_dump(include={
        "action",
        "ranked_products",
        "product_cards",
        "clarify_question",
        "empty_reason",
        "error",
        "error_code",
        "message",
    })
    payload["requested_limit"] = max(1, int(limit or 3))
    payload["returned_count"] = len(payload.get("product_cards") or [])
    return payload


# ---- Tool 2: compare_products -------------------------------------------

@tool(parse_docstring=True)
async def compare_products(
    runtime: ToolRuntime,
    query: str,
    product_ids: Optional[List[int]] = None,
) -> dict:
    """比较 Router 已绑定的多个真实商品并给出结构化差异。

    仅用于至少两个已绑定商品的横向比较或选择；不用于发现新品或单品详情。
    具体工作方法由 ``compare-products`` Skill 提供。

    Args:
        query: Router 已消解指代后的完整对比问题。
        product_ids: 可选的 Router 已绑定商品 ID 有序子集；省略时使用 runtime
            中的全部已绑定商品。不得传入任意新 ID。

    Returns:
        包含 action、products、dimensions、comparison_rows、suggestion、
        product_cards 和 clarify_question 的结构化结果。
    """
    context = await build_shopping_context_from_runtime(runtime)
    result = await CompareCapability().run(
        query=query, context=context, product_ids=product_ids,
    )
    return result.model_dump()


# ---- Tool 3: answer_product_detail --------------------------------------

@tool(parse_docstring=True)
async def answer_product_detail(
    runtime: ToolRuntime,
    query: str,
    product_id: Optional[int] = None,
) -> dict:
    """查询 Router 已绑定单个商品的实时事实和详情。

    仅用于一个已绑定商品的价格、库存、SKU、规格、成分、适配性或概览追问；
    不用于发现新品或比较多件商品。具体工作方法由 ``inspect-product`` Skill 提供。

    Args:
        query: Router 已消解指代后的完整详情问题。
        product_id: 可选的 Router 已绑定商品 ID；省略时仅在 runtime 中唯一
            绑定一件商品时使用该 ID。不得传入任意新 ID。

    Returns:
        包含 action、product、focus、facts、product_cards 和
        clarify_question 的结构化结果。
    """
    context = await build_shopping_context_from_runtime(runtime)
    result = await DetailCapability().run(
        query=query, context=context, product_id=product_id,
    )
    return result.model_dump()


# ---- Tool 4: get_user_shopping_context ----------------------------------

@tool(parse_docstring=True)
async def get_user_shopping_context(
    runtime: ToolRuntime,
    include_favorites: bool = False,
    include_browse_history: bool = False,
    include_orders: bool = False,
) -> dict:
    """读取用户明确请求的、允许使用的购物画像或行为摘要。

    普通商品推荐、比较和详情任务不需要本工具。具体使用边界由
    ``use-shopping-profile`` Skill 提供。

    Args:
        include_favorites: 是否包含收藏摘要（MVP stub，尚未实现）。
        include_browse_history: 是否包含浏览历史摘要（MVP stub）。
        include_orders: 是否包含订单摘要（MVP stub）。

    Returns:
        包含 error、error_code、data 和 message 的结构化结果；data 可能包含
        profile、preferences、favorites_summary、browse_summary 或 orders_summary。
    """
    context = await build_shopping_context_from_runtime(runtime)
    return await UserShoppingContextCapability().run(
        context=context,
        include_favorites=include_favorites,
        include_browse_history=include_browse_history,
        include_orders=include_orders,
    )


# ---- 工具集合（挂给 ShoppingAgent 的唯一入口）--------------------------

SHOPPING_HIGH_LEVEL_TOOLS: list = [
    recommend_products,
    compare_products,
    answer_product_detail,
    get_user_shopping_context,
]
