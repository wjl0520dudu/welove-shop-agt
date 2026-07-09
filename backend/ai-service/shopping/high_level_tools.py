"""ShoppingAgent 的高层 Tool 入口 —— LLM 只面对这 4 个。

## 关键约束
- 每个 Tool 的 docstring 是 LLM 判断"用哪个"的唯一依据，必须清楚写：
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

from shopping.capabilities import (
    CompareCapability,
    DetailCapability,
    RecommendCapability,
    UserShoppingContextCapability,
)
from shopping.context import build_shopping_context_from_runtime

logger = logging.getLogger("ai-service.shopping.high_level_tools")


# ---- Tool 1: recommend_products -----------------------------------------

@tool(parse_docstring=True)
async def recommend_products(
    runtime: ToolRuntime,
    query: str,
    limit: int = 3,
) -> dict:
    """根据用户购物需求推荐真实商品，返回排序后的商品和商品卡片。

    适用于：
    - 用户想找商品、买商品、推荐商品
    - 用户提到预算、肤质、场景、偏好、避雷点
    - 用户说"推荐""找""买""有没有""适合""预算""送人"
    - 用户回答上一轮追问（"油皮""预算 200""送妈妈"）——本工具会自动读取
      并合并 pending_shopping_need

    不适用于：
    - 用户想对比已有商品 → 应调用 compare_products
    - 用户追问某个商品的价格/规格/库存 → 应调用 answer_product_detail

    Args:
        query: 用户当前原话，保留完整自然语言。
        limit: 返回商品卡片数量，默认 3。

    Returns:
        dict 结构：
        {
            "action": "recommend|clarify|empty",
            "need": {...},                    # 解析后的结构化需求
            "product_cards": [...],           # 前端可直接渲染的卡片
            "ranked_products": [...],         # 完整排序详情（含 rank_reason）
            "clarify_question": "...",         # action=clarify 时的追问
            "empty_reason": "...",             # action=empty 时的说明
            "trace": [...],                    # 观测用
        }

        - action=recommend: 基于 product_cards + ranked_products 写自然语言推荐话术。
        - action=clarify: 直接把 clarify_question 问给用户，不要推荐商品。
        - action=empty: 说明当前条件下没找到，建议放宽条件。
    """
    context = await build_shopping_context_from_runtime(runtime)
    result = await RecommendCapability().run(query=query, context=context, limit=limit)
    return result.model_dump()


# ---- Tool 2: compare_products -------------------------------------------

@tool(parse_docstring=True)
async def compare_products(
    runtime: ToolRuntime,
    query: str,
    product_ids: Optional[List[int]] = None,
) -> dict:
    """对比多个真实商品，给出多维对比表和最佳选择建议。

    适用于：
    - 用户问"这两个哪个好""他们三对比一下"
    - 用户问"第二个和第三个哪个更适合敏感肌"
    - 用户想按价格/评分/销量/成分/肤质等维度横向比较

    不适用于：
    - 用户想重新找商品 → 应调用 recommend_products
    - 用户只问单个商品的价格/库存/详情 → 应调用 answer_product_detail

    Args:
        query: 用户当前原话。
        product_ids: 可选，明确要对比的商品 ID 列表。不传时会从 query 的指代词
                     ("第二个/他们三")或上一轮 last_product_cards 自动解析。

    Returns:
        dict 结构：
        {
            "action": "compare|clarify|empty",
            "products": [...],
            "dimensions": ["价格","评分","销量","核心成分",...],
            "comparison_rows": [...],         # 每商品一行，各维度值
            "suggestion": {"focus":"price","recommended_product_id":X,"reason":"..."},
            "product_cards": [...],
            "clarify_question": "...",
            "trace": [...],
        }

        - action=compare: 基于 comparison_rows + suggestion 写自然语言对比结论。
        - action=clarify: 商品不足 2 款，直接把 clarify_question 问给用户。
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
    """回答某个商品的价格、库存、规格、成分、适合人群、详情等追问。

    适用于：
    - "第二个多少钱""这个多少钱"
    - "刚才那个还有货吗""有其他规格吗"
    - "讲讲第一款""详细介绍下这个"
    - "这个适合我吗""含什么成分"

    不适用于：
    - 用户想找新商品 → 应调用 recommend_products
    - 用户想对比多个商品 → 应调用 compare_products

    Args:
        query: 用户当前原话。
        product_id: 可选，明确指定商品 ID。不传时会从 query 的指代词
                    ("第二个/刚才那个/它")或 last_focused_product 自动解析。

    Returns:
        dict 结构：
        {
            "action": "detail|clarify|empty",
            "product": {...},                   # 完整商品数据（含 skus）
            "focus": "price|stock|sku|overview|suitability|ingredients",
            "facts": {...},                     # 按 focus 精选的关键事实
            "product_cards": [...],
            "clarify_question": "...",
            "trace": [...],
        }

        - action=detail: 基于 facts 用自然语言回答用户的追问点。
        - action=clarify: 无法定位商品，把 clarify_question 问给用户。
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
    """获取当前用户的购物上下文摘要（登录后的画像 + 偏好）。

    适用于：
    - 用户明确要求"根据我的肤质推荐""按我喜欢的推""我上次买的"
    - 用户说"我的..."需要读取个人数据时

    不适用于：
    - 普通商品推荐/对比/追问，先直接用 recommend_products/compare_products/
      answer_product_detail，不需要先调本工具。

    Args:
        include_favorites: 是否包含收藏摘要（MVP stub，尚未实现）。
        include_browse_history: 是否包含浏览历史摘要（MVP stub）。
        include_orders: 是否包含订单摘要（MVP stub）。

    Returns:
        dict 结构：
        {
            "error": bool,
            "error_code": "LOGIN_REQUIRED",     # 未登录时
            "data": {
                "is_logged_in": bool,
                "profile": {"skin_type","gender","preference_tags","profile"},
                "preferences": {...},           # Store 里学习到的偏好
                "favorites_summary": {...},     # 若开关打开
                "browse_summary": {...},
                "orders_summary": {...},
            },
            "message": "..."
        }
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
