"""用户能力工具集 —— Agent 通过 Java REST API 拿用户维度数据。

覆盖：
- 收藏列表 → GET /api/recommend/favorite/list
- 浏览历史 → GET /api/recommend/browse/history
- 订单列表 → GET /api/order/list?status=&page=&size=
- 订单详情 → GET /api/order/{id}

## 认证透传
Java 侧走 JwtFilter，所有接口需要 Bearer <jwt>。
JWT 通过 ShoppingAgentState → ToolRuntime.state["jwt_token"] 传下来，
工具从 runtime 里拿，不用闭包捕获。

## 未登录降级
如果 state 里没有 jwt_token（匿名会话），工具直接返回 error 结构，让 agent
诚实告诉用户"需要登录后才能查看"，不 leak Java 侧的 500/401 细节。

## 与直连 PG 的对比
之前 shopping_tools 直接查 PG product 表。用户维度的数据（收藏/浏览/订单）
交给 Java：业务规则一处维护、权限走 JwtFilter、事务由 Java 保障。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field

from core.java_api_client import JavaApiResult, get_java_api_client

logger = logging.getLogger("ai-service.user_tools")


# ---- 参数 schema ----------------------------------------------------------

class ListOrdersInput(BaseModel):
    status: Optional[int] = Field(
        default=None,
        description="订单状态过滤：0-待付款 1-待发货 2-待收货 3-已完成 4-已取消，不传则返回全部",
        ge=0, le=4,
    )
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    size: int = Field(default=10, ge=1, le=50, description="每页数量，最大 50")


class OrderIdInput(BaseModel):
    order_id: int = Field(..., description="订单 ID")


# ---- 内部 helper ---------------------------------------------------------

def _jwt_from_runtime(runtime: ToolRuntime) -> Optional[str]:
    """从 ToolRuntime.state 读 jwt_token。"""
    state = runtime.state or {}
    return state.get("jwt_token")


def _needs_login_result() -> dict:
    """未登录时的统一返回结构。Agent 会看到这个信号并告诉用户去登录。"""
    return {
        "error": True,
        "error_code": "LOGIN_REQUIRED",
        "message": "该功能需要登录后使用，请引导用户先登录。",
        "data": None,
    }


def _java_result_to_tool_output(result: JavaApiResult, empty_message: str = "暂无数据") -> dict:
    """把 JavaApiResult 转成工具输出格式，agent 能直接读。"""
    if not result.success:
        return {
            "error": True,
            "error_code": result.error_code or "JAVA_API_ERROR",
            "message": result.message or "调用后端失败",
            "data": None,
        }
    # 空数据也算成功，让 agent 自己判断"无历史/无订单"
    data = result.data
    if data is None or (isinstance(data, list) and len(data) == 0):
        return {"error": False, "data": [], "message": empty_message}
    return {"error": False, "data": data}


# ---- 工具本体（模块级 @tool，全部 async）---------------------------------

@tool
async def get_user_favorites(runtime: ToolRuntime) -> dict:
    """查询当前登录用户的商品收藏列表。

    用于个性化推荐：当用户问"根据我喜欢的推荐"或表达偏好时，先看看用户收藏了什么，
    再基于收藏商品的品牌/品类/价位做相似推荐。

    Args:
        runtime: 工具运行时（自动注入，不用手动传）。从 runtime.state 拿 jwt_token。

    Returns:
        dict: {"error": bool, "data": List[Favorite] | None, "message": str}
              Favorite 字段：{id, userId, productId, createTime}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    jwt = _jwt_from_runtime(runtime)
    if not jwt:
        return _needs_login_result()
    result = await get_java_api_client().get("/api/recommend/favorite/list", jwt_token=jwt)
    return _java_result_to_tool_output(result, empty_message="用户暂无收藏商品")


@tool
async def get_user_browse_history(runtime: ToolRuntime) -> dict:
    """查询当前登录用户的商品浏览历史。

    用于个性化推荐：结合最近浏览的商品品类和偏好，做"你最近看过 X，可能也喜欢 Y"这类推荐。

    Args:
        runtime: 工具运行时（自动注入）。从 runtime.state 拿 jwt_token。

    Returns:
        dict: {"error": bool, "data": List[BrowseHistory] | None, "message": str}
              BrowseHistory 字段：{id, userId, productId, source, durationSec, createTime}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    jwt = _jwt_from_runtime(runtime)
    if not jwt:
        return _needs_login_result()
    result = await get_java_api_client().get("/api/recommend/browse/history", jwt_token=jwt)
    return _java_result_to_tool_output(result, empty_message="用户暂无浏览记录")


@tool(args_schema=ListOrdersInput)
async def get_user_orders(
    runtime: ToolRuntime,
    status: Optional[int] = None,
    page: int = 1,
    size: int = 10,
) -> dict:
    """查询当前登录用户的订单列表。

    用于售后场景："我的上一单发货了吗""我上个月买的粉底液叫什么名字"。
    可用 status 过滤：0-待付款 1-待发货 2-待收货 3-已完成 4-已取消。

    Args:
        runtime: 工具运行时（自动注入）。
        status: 订单状态过滤（0-4），不传则返回全部。
        page: 页码，从 1 开始，默认 1。
        size: 每页数量，最大 50，默认 10。

    Returns:
        dict: {"error": bool, "data": {records, total, ...} | None, "message": str}
              Order 字段：{id, orderNo, status, totalAmount, payAmount, createTime, items:[...]}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    jwt = _jwt_from_runtime(runtime)
    if not jwt:
        return _needs_login_result()
    params: dict[str, Any] = {"page": page, "size": size}
    if status is not None:
        params["status"] = status
    result = await get_java_api_client().get("/api/order/list", jwt_token=jwt, params=params)
    return _java_result_to_tool_output(result, empty_message="用户暂无订单")


@tool(args_schema=OrderIdInput)
async def get_order_detail(runtime: ToolRuntime, order_id: int) -> dict:
    """查询指定订单的详情（含订单项、状态、金额、地址等）。

    用于用户明确问"我的 XX 订单怎么样了""这单里买了什么"。
    order_id 通常来自 get_user_orders 结果的 id 字段；如果用户没给 ID，
    应该先调 get_user_orders 让用户挑一个。

    Args:
        runtime: 工具运行时（自动注入）。
        order_id: 订单 ID。

    Returns:
        dict: {"error": bool, "data": Order | None, "message": str}
              Order 详情字段：{id, orderNo, status, totalAmount, address, items:[...]}
              未登录时 error_code = "LOGIN_REQUIRED"
              订单不属于当前用户或不存在时 Java 会返回失败
    """
    jwt = _jwt_from_runtime(runtime)
    if not jwt:
        return _needs_login_result()
    result = await get_java_api_client().get(f"/api/order/{order_id}", jwt_token=jwt)
    return _java_result_to_tool_output(result)


# ---- 工具集合 -------------------------------------------------------------

USER_TOOLS: list = [
    get_user_favorites,
    get_user_browse_history,
    get_user_orders,
    get_order_detail,
]
