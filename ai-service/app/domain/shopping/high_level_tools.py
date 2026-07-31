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
    """根据 Router 已整理的完整购物需求推荐真实商品。

    适用于：
    - 用户想找商品、买商品、推荐商品
    - 用户提到预算、肤质、场景、偏好、避雷点
    - 本轮有参考图片时找相似商品；图片由 runtime 自动提供给本工具

    不适用于：
    - 用户想对比已有商品 → 应调用 compare_products
    - 用户追问某个商品的价格/规格/库存 → 应调用 answer_product_detail

    固定执行闭环：
    1. 触发：仅用于发现或推荐新商品。调用时把 Router 交付的完整 query 原样传入，
       不删除预算、场景、肤质、偏好、避雷条件，也不读取会话历史补写需求。
    2. 工具内部：自动完成需求解析 → 文本/图片/图文候选召回 → 系统级过滤 →
       排序/软重排（如已启用）→ 商品卡构造。有图片时仍只调用本工具一次。
    3. 返回分支：
       - action=recommend：使用 product_cards 和 ranked_products 中的真实字段组织推荐。
       - action=clarify：直接提出 clarify_question，停止，不要自行补全条件后重搜。
       - action=empty：如实说明 empty_reason，停止，不要调用对比、详情或无关工具凑答案。
    4. 完成后：不得以相同或改写后的参数再次调用本工具；不得自行调用底层检索、
       再过滤、软重排、补卡或修改工具返回的商品事实。
    5. 最终输出：只围绕工具返回的商品卡和真实字段作答；商品卡由系统展示。

    典型示例：
    - “预算 300 元，给通勤用推荐一副降噪耳机” → 调用本工具，query 保留完整预算和场景。
    - “夏天出油多，想要清爽的防晒” → 调用本工具，query 保留肤质和使用感偏好。
    - “送朋友的生日礼物，想要实用一点的咖啡机” → 调用本工具。
    - “根据这张图找类似跑鞋” → 调用本工具一次，图片检索由工具内部执行。
    - “比较 A 和 B 哪个好” → 不调用本工具，改用 compare_products。
    - “A 还有没有货” → 不调用本工具，改用 answer_product_detail。

    Args:
        query: Router 已消解指代后的完整商品需求。
        limit: 返回商品卡片数量，默认 3。

    Returns:
        dict 结构：
        {
            "action": "recommend|clarify|empty",
            "product_cards": [...],           # 前端可直接渲染的卡片
            "ranked_products": [...],         # 仅包含最终展示商品
            "requested_limit": 3,             # 本次期望数量
            "returned_count": 2,              # 最终真实商品数量
            "clarify_question": "...",         # action=clarify 时的追问
            "empty_reason": "...",             # action=empty 时的说明
        }

        - action=recommend: 基于 product_cards + ranked_products 写自然语言推荐话术。
        - action=clarify: 直接把 clarify_question 问给用户，不要推荐商品，然后停止。
        - action=empty: 如实说明当前条件下没找到，不要改用对比或详情工具凑答案，然后停止。
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
    """对比 Router 已绑定的多个真实商品，给出多维对比和选择建议。

    适用于：
    - 用户问 Router 已绑定商品之间哪个好、需要横向比较
    - 用户想按价格/评分/销量/成分/肤质等维度横向比较

    不适用于：
    - 用户想重新找商品 → 应调用 recommend_products
    - 用户只问单个商品的价格/库存/详情 → 应调用 answer_product_detail

    固定执行闭环：
    1. 触发：仅用于比较两个或更多 Router 已绑定商品。只能使用已绑定的有序商品 ID，
       不得从历史卡片、商品名称或原问题猜测、补充或替换对象。
    2. 工具内部：自动从同一活动商品源读取真实商品事实，构造比较维度、差异、建议和卡片。
       不要先调用推荐工具重新找商品。
    3. 返回分支：
       - action=compare：根据 comparison_rows、dimensions 和 suggestion 组织比较结论。
       - action=clarify：直接提出 clarify_question，停止；不能任意找历史商品凑够两件。
       - action=empty：如实说明工具的空结果，停止。
    4. 完成后：不得再次调用 compare_products，也不得改调推荐或详情工具；不得自行重排、
       修改比较对象或补写价格、库存、规格、成分、评分等事实。
    5. 最终输出：优先回答用户指定的比较维度，再给出基于 suggestion 的选择建议。

    典型示例：
    - “比较这两款耳机的降噪、续航和通话效果” → 调用本工具。
    - “这几款跑鞋哪双更适合日常通勤” → 调用本工具。
    - “A 和 B 哪个性价比更高” → 调用本工具。
    - “推荐一款适合通勤的耳机” → 不调用本工具，改用 recommend_products。
    - “A 的价格是多少” → 不调用本工具，改用 answer_product_detail。

    Args:
        query: Router 已消解指代后的完整对比问题。
        product_ids: 可选的 Router 已绑定商品 ID 有序子集；省略时使用 runtime
            中的全部已绑定商品。不得传入任意新 ID。

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
        - action=clarify: 商品不足 2 款，直接把 clarify_question 问给用户，然后停止。
        - action=empty: 如实说明当前没有可确认的比较结果，然后停止。
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
    """回答 Router 已绑定商品的价格、库存、规格、成分和详情追问。

    适用于：
    - 已绑定商品的价格、库存、规格、成分、适配性追问
    - "这个适合我吗""含什么成分"

    不适用于：
    - 用户想找新商品 → 应调用 recommend_products
    - 用户想对比多个商品 → 应调用 compare_products

    固定执行闭环：
    1. 触发：仅用于 Router 已唯一绑定商品的价格、库存、SKU、规格、成分、适配性或概览追问。
       只能使用该绑定 ID，不能从历史卡片、focus 商品、商品名称或代词猜测。
    2. 工具内部：自动从活动商品源查询在售状态、商品事实和 SKU 事实，并按当前问题整理 facts。
    3. 返回分支：
       - action=detail：只依据 facts 和 product 中真实存在的字段回答当前追问点。
       - action=clarify：直接提出 clarify_question，停止。
       - action=empty：如实说明工具的空结果，停止。
    4. 完成后：不得再次调用本工具，也不得改调推荐或对比工具；不得编造价格、库存、SKU、
       规格、功效、成分或评价来补足答案。
    5. 最终输出：直接回答用户最关心的事实；未返回的字段明确说明无法确认。

    典型示例：
    - “这款精华有什么规格，哪个规格更划算” → 调用本工具。
    - “这双跑鞋现在有货吗，尺码怎么选” → 调用本工具。
    - “这台相机的重量和续航怎么样” → 调用本工具。
    - “给我推荐一台旅行相机” → 不调用本工具，改用 recommend_products。
    - “这两台相机哪个更适合旅行” → 不调用本工具，改用 compare_products。

    Args:
        query: Router 已消解指代后的完整详情问题。
        product_id: 可选的 Router 已绑定商品 ID；省略时仅在 runtime 中唯一
            绑定一件商品时使用该 ID。不得传入任意新 ID。

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
        - action=clarify: 无法定位商品，把 clarify_question 问给用户，然后停止。
        - action=empty: 如实说明当前没有可确认的详情结果，然后停止。
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
    """获取用户明确要求读取的购物上下文摘要。

    适用于：
    - 用户明确要求"根据我的肤质推荐""按我喜欢的推""我上次买的"
    - 用户说"我的..."需要读取个人数据时

    不适用于：
    - 普通商品推荐/对比/追问，先直接用 recommend_products/compare_products/
      answer_product_detail，不需要先调本工具。

    固定执行闭环：
    1. 触发：仅当用户明确要求基于个人画像、收藏、浏览或订单信息处理需求时调用。
       普通推荐、对比和详情追问不能为了猜测偏好而调用。
    2. 工具内部：按用户明确要求读取允许的个人数据摘要；它不读取会话历史，也不解析商品指代。
    3. 返回分支：登录或数据不足时，直接说明返回的 message；有可用摘要时只把它作为后续
       一个主要商品工具的辅助信号，不能把它当作商品事实。
    4. 完成后：最多再调用一个主要商品工具；不得连续读取用户上下文、不得自行推断未返回偏好。
    5. 最终输出：围绕用户明确请求的个人化目标回答，不泄露内部画像字段、JWT 或订单细节。

    典型示例：
    - “按我的肤质推荐防晒” → 先调用本工具（include_favorites=false 等），再调用 recommend_products。
    - “根据我收藏过的商品推荐” → 先调用本工具（include_favorites=true），再调用 recommend_products。
    - “推荐一款 300 元以内的耳机” → 不调用本工具，直接 recommend_products。

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
