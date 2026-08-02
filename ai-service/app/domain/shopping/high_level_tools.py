"""ShoppingAgent 的受控业务 Tool 入口。

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
import secrets
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from app.domain.shopping.capabilities import (
    BoundProductFactsCapability,
    CompareCapability,
    DetailCapability,
    RecommendCapability,
    UserShoppingContextCapability,
)
from app.domain.shopping.context import build_shopping_context_from_runtime

logger = logging.getLogger("ai-service.shopping.high_level_tools")


# DeepAgent 的一次运行会跨多个模型/Tool step。候选集只在该请求的上下文中
# 暂存，Agent 只拿到不可猜测的 ID；终结 Tool 始终使用服务端保存的原始候选，
# 不接受模型重新提交商品事实。
_CANDIDATE_SESSION: ContextVar[Optional[dict[str, dict[str, Any]]]] = ContextVar(
    "shopping_candidate_session",
    default=None,
)


@contextmanager
def shopping_candidate_session():
    """Create an isolated candidate registry for one ShoppingAgent run."""
    token = _CANDIDATE_SESSION.set({})
    try:
        yield
    finally:
        _CANDIDATE_SESSION.reset(token)


def _candidate_registry() -> dict[str, dict[str, Any]]:
    registry = _CANDIDATE_SESSION.get()
    if registry is None:
        registry = {}
        _CANDIDATE_SESSION.set(registry)
    return registry


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


# ---- Phase S4: narrow recommendation tools -----------------------------

@tool(parse_docstring=True)
async def search_product_candidates(
    runtime: ToolRuntime,
    query: str,
    limit: int = 3,
) -> dict:
    """召回真实商城候选，不做最终候选审核或商品卡构造。

    用于 ``discover-products`` Skill 的第一步。文本、纯图片和图文请求都使用
    本工具；输入模式与图片由运行时提供，不允许模型选择底层检索通道。

    Args:
        query: Router 已消解指代后的完整商品需求。
        limit: 用户期望展示的商品数量，默认 3。

    Returns:
        action=candidates 时返回有限 CandidateSet 和 candidate_set_id；
        action=clarify/empty 时返回对应原因并终止推荐流程。
    """
    context = await build_shopping_context_from_runtime(runtime)
    requested_limit = max(1, int(limit or 3))
    result = await RecommendCapability().search_candidates(
        query=query,
        context=context,
        limit=requested_limit,
    )
    payload = result.model_dump(include={
        "action",
        "candidate_set",
        "clarify_question",
        "empty_reason",
    })
    payload["requested_limit"] = requested_limit
    candidate_set = result.candidate_set
    payload["candidate_count"] = len(candidate_set.candidates) if candidate_set else 0
    if result.action == "candidates" and candidate_set is not None:
        candidate_set_id = secrets.token_urlsafe(18)
        _candidate_registry()[candidate_set_id] = {
            "query": str(query or "").strip(),
            "requested_limit": requested_limit,
            "result": result,
        }
        payload["candidate_set_id"] = candidate_set_id
    return payload


@tool(parse_docstring=True)
async def finalize_product_recommendation(
    runtime: ToolRuntime,
    candidate_set_id: str,
) -> dict:
    """按 ``discover-products`` Skill 审核已召回候选并生成最终商品卡。

    仅用于 ``search_product_candidates`` 成功后的第二步。候选事实由服务端根据
    candidate_set_id 读取，模型不能传入、替换或改写商品 ID、价格和候选字段。
    第一轮迁移继续复用现有单次 Candidate Judge。

    Args:
        candidate_set_id: 候选召回工具返回的请求级候选集 ID。

    Returns:
        包含 action、product_cards、ranked_products、returned_count 和
        empty_reason 的最终结构化推荐结果。
    """
    record = _candidate_registry().get(str(candidate_set_id or "").strip())
    if not record:
        return {
            "action": "empty",
            "product_cards": [],
            "ranked_products": [],
            "returned_count": 0,
            "error": True,
            "error_code": "SHOPPING_CANDIDATE_SET_EXPIRED",
            "empty_reason": "候选结果已失效，请重新执行一次商品候选召回。",
        }

    search_result = record["result"]
    context = await build_shopping_context_from_runtime(runtime)
    result = await RecommendCapability().finalize_candidates(
        query=record["query"],
        context=context,
        candidate_set=search_result.candidate_set,
        limit=record["requested_limit"],
        need=search_result.need,
        trace=search_result.trace,
    )
    payload = result.model_dump(include={
        "action",
        "ranked_products",
        "product_cards",
        "clarify_question",
        "empty_reason",
    })
    payload["requested_limit"] = record["requested_limit"]
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


# ---- Phase S5: unified bound-product fact tool --------------------------

@tool(parse_docstring=True)
async def load_bound_product_facts(
    runtime: ToolRuntime,
    purpose: Literal["compare", "detail"],
    product_ids: Optional[List[int]] = None,
) -> dict:
    """读取 Router 已绑定商品的真实主档、价格、SKU、库存和规格事实。

    用于 ``compare-products`` 或 ``inspect-product`` Skill；本工具不理解用户关注维度，
    不从历史或自然语言猜商品 ID，也不替 Agent 做比较结论。

    Args:
        purpose: 当前 Skill 的用途；多商品比较传 compare，单商品详情传 detail。
        product_ids: Router 已绑定 ID 的可选有序子集；不得传入未绑定的新 ID。

    Returns:
        compare_facts/detail_facts、真实 products、product_cards；绑定不清时返回
        clarify，商品不存在或下架时返回 empty。
    """
    context = await build_shopping_context_from_runtime(runtime)
    result = await BoundProductFactsCapability().run(
        purpose=purpose,
        context=context,
        product_ids=product_ids,
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


# ---- 工具集合 ----------------------------------------------------------

# 关闭 DeepAgent 时的人工回滚链继续使用原有一体化推荐 Tool。
SHOPPING_ROLLBACK_TOOLS: list = [
    recommend_products,
    compare_products,
    answer_product_detail,
    get_user_shopping_context,
]

# Phase S4 主链：Skill 显式编排候选召回和结果终结。
SHOPPING_HIGH_LEVEL_TOOLS: list = [
    search_product_candidates,
    finalize_product_recommendation,
    load_bound_product_facts,
    get_user_shopping_context,
]
