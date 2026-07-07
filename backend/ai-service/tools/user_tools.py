"""用户能力工具集 —— Agent 通过 PG ORM 直查用户维度数据。

覆盖：
- 个人资料 → PG users 表
- 收藏列表 → PG user_favorite 表
- 浏览历史 → PG user_browse_history 表
- 订单列表 → PG orders 表
- 订单详情 → PG orders + order_item 表

## 认证
user_id 通过 ShoppingAgentState → ToolRuntime.state["user_id"] 传入。
未登录（user_id 为 None）时返回 LOGIN_REQUIRED。

## 用户 Profile JSONB
users 表新增 profile JSONB 字段，存动态属性（concerns / allergens / budget_preference 等）。
迁移 SQL（如果列还不存在）：
  ALTER TABLE users ADD COLUMN IF NOT EXISTS profile JSONB DEFAULT '{}';

## 与 Java API 的关系
原通过 Java REST API 拿用户数据。Java 开发完毕前，改为 PG ORM 直查。
Java 上线后可切回 Java（业务规则一处维护），届时修改本文件即可。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.database import get_session_factory
from shopping.orm_models import (
    OrderItemORM,
    OrderORM,
    UserBrowseHistoryORM,
    UserFavoriteORM,
    UserORM,
)

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

def _user_id_from_runtime(runtime: ToolRuntime) -> Optional[int]:
    """从 ToolRuntime.state 读 user_id。"""
    state = runtime.state or {}
    uid = state.get("user_id")
    if uid is None:
        return None
    try:
        return int(uid)
    except (TypeError, ValueError):
        return None


def _needs_login_result() -> dict:
    """未登录时的统一返回结构。Agent 会看到这个信号并告诉用户去登录。"""
    return {
        "error": True,
        "error_code": "LOGIN_REQUIRED",
        "message": "该功能需要登录后使用，请引导用户先登录。",
        "data": None,
    }


def _ok(data: Any = None, message: str = "OK") -> dict:
    """成功返回。"""
    return {"error": False, "data": data, "message": message}


def _empty_data(message: str = "暂无数据") -> dict:
    """空数据成功返回。"""
    return {"error": False, "data": [], "message": message}


# ---- 工具本体（模块级 @tool，全部 async）---------------------------------

@tool(parse_docstring=True)
async def get_user_profile(runtime: ToolRuntime) -> dict:
    """获取当前登录用户的个人资料（含注册时预填的偏好标签）。

    用户注册时填写的 skin_type（肤质）、gender（性别）、preference_tags（偏好标签如["平价","敏感肌"]）
    以及 profile JSONB 动态属性（concerns / allergens 等）会从 PG users 表返回。
    Agent 应在以下时机调用此工具：

    1. **新对话开始时**：用户第一次在会话中开口时，先调此工具了解用户的预填偏好，
       用于后续推荐时做个性化（参考 skin_type/gender/preference_tags）。
    2. **用户明确要求更新偏好**：如"我其实是大油皮"，调此工具确认当前 Profile，
       然后结合对话上下文更新。

    与 remember_user_preferences 的关系：
    - get_user_profile → 从 PG 读注册预填偏好（静态画像）
    - remember_user_preferences → 写 Store 记录对话中学习到的偏好（动态画像）
    get_business_memory 会合并两处，让 agent 拿到统一视图。

    Args:
        runtime: 工具运行时（自动注入）。从 runtime.state 拿 user_id。

    Returns:
        dict: {"error": bool, "data": {id, username, phone, gender, skinType, preferenceTags, profile, ...} | None}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    user_id = _user_id_from_runtime(runtime)
    if user_id is None:
        return _needs_login_result()

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(UserORM).where(UserORM.id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        return {
            "error": True,
            "error_code": "USER_NOT_FOUND",
            "message": "用户不存在",
            "data": None,
        }

    # 组装返回数据（camelCase 兼容前端）
    profile_data = {
        "id": user.id,
        "username": user.username or "",
        "phone": user.phone or "",
        "avatarUrl": user.avatar_url or "",
        "gender": user.gender,
        "ageRange": user.age_range or "",
        "skinType": user.skin_type or "",
        "preferenceTags": user.preference_tags or [],
        "profile": user.profile or {},
        "status": user.status,
        "createTime": user.create_time.isoformat() if user.create_time else None,
    }

    # 自动同步用户预填偏好到 Store，后续 get_business_memory 能读到
    prefs_to_sync = {}
    if user.skin_type:
        prefs_to_sync["skin_type"] = user.skin_type
    if user.gender is not None:
        prefs_to_sync["gender"] = "女" if user.gender == 2 else ("男" if user.gender == 1 else "未设置")
    if user.preference_tags:
        prefs_to_sync["preference_tags"] = user.preference_tags
    # profile JSONB 动态属性也同步
    if user.profile:
        prefs_to_sync["profile"] = user.profile

    if prefs_to_sync:
        from agents.memory import remember_user_preferences
        cid = runtime.state.get("conversation_id") if runtime.state else None
        await remember_user_preferences(cid, user_id, prefs_to_sync)

    return _ok(data=profile_data)


@tool
async def get_user_favorites(runtime: ToolRuntime) -> dict:
    """查询当前登录用户的商品收藏列表。

    用于个性化推荐：当用户问"根据我喜欢的推荐"或表达偏好时，先看看用户收藏了什么，
    再基于收藏商品的品牌/品类/价位做相似推荐。

    Args:
        runtime: 工具运行时（自动注入，不用手动传）。从 runtime.state 拿 user_id。

    Returns:
        dict: {"error": bool, "data": List[Favorite] | None, "message": str}
              Favorite 字段：{id, userId, productId, createTime}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    user_id = _user_id_from_runtime(runtime)
    if user_id is None:
        return _needs_login_result()

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(UserFavoriteORM)
            .where(UserFavoriteORM.user_id == user_id)
            .order_by(UserFavoriteORM.create_time.desc())
        )
        rows = result.scalars().all()

    if not rows:
        return _empty_data("用户暂无收藏商品")

    data = [
        {
            "id": r.id,
            "userId": r.user_id,
            "productId": r.product_id,
            "createTime": r.create_time.isoformat() if r.create_time else None,
        }
        for r in rows
    ]
    return _ok(data=data)


@tool
async def get_user_browse_history(runtime: ToolRuntime) -> dict:
    """查询当前登录用户的商品浏览历史。

    用于个性化推荐：结合最近浏览的商品品类和偏好，做"你最近看过 X，可能也喜欢 Y"这类推荐。

    Args:
        runtime: 工具运行时（自动注入）。从 runtime.state 拿 user_id。

    Returns:
        dict: {"error": bool, "data": List[BrowseHistory] | None, "message": str}
              BrowseHistory 字段：{id, userId, productId, source, durationSec, createTime}
              未登录时 error_code = "LOGIN_REQUIRED"
    """
    user_id = _user_id_from_runtime(runtime)
    if user_id is None:
        return _needs_login_result()

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(UserBrowseHistoryORM)
            .where(UserBrowseHistoryORM.user_id == user_id)
            .order_by(UserBrowseHistoryORM.create_time.desc())
            .limit(50)
        )
        rows = result.scalars().all()

    if not rows:
        return _empty_data("用户暂无浏览记录")

    data = [
        {
            "id": r.id,
            "userId": r.user_id,
            "productId": r.product_id,
            "source": r.source or "",
            "durationSec": r.duration_sec,
            "createTime": r.create_time.isoformat() if r.create_time else None,
        }
        for r in rows
    ]
    return _ok(data=data)


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
    user_id = _user_id_from_runtime(runtime)
    if user_id is None:
        return _needs_login_result()

    session_factory = get_session_factory()
    async with session_factory() as session:
        # 构建查询
        stmt = select(OrderORM).where(OrderORM.user_id == user_id)
        if status is not None:
            stmt = stmt.where(OrderORM.status == status)

        # 总数
        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(OrderORM).where(OrderORM.user_id == user_id)
        if status is not None:
            count_stmt = count_stmt.where(OrderORM.status == status)
        total = (await session.execute(count_stmt)).scalar() or 0

        # 分页
        offset = (page - 1) * size
        stmt = stmt.order_by(OrderORM.create_time.desc()).offset(offset).limit(size)
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        return _empty_data("用户暂无订单")

    records = [
        {
            "id": r.id,
            "orderNo": r.order_no or "",
            "status": r.status,
            "totalAmount": float(r.total_amount) if r.total_amount is not None else None,
            "payAmount": float(r.pay_amount) if r.pay_amount is not None else None,
            "createTime": r.create_time.isoformat() if r.create_time else None,
            "payTime": r.pay_time.isoformat() if r.pay_time else None,
            "deliveryTime": r.delivery_time.isoformat() if r.delivery_time else None,
            "receiverName": r.receiver_name or "",
        }
        for r in rows
    ]
    return _ok(data={"records": records, "total": total, "page": page, "size": size})


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
              订单不属于当前用户或不存在时返回失败
    """
    user_id = _user_id_from_runtime(runtime)
    if user_id is None:
        return _needs_login_result()

    session_factory = get_session_factory()
    async with session_factory() as session:
        # 查订单主表（限定用户，防止越权）
        result = await session.execute(
            select(OrderORM).where(OrderORM.id == order_id, OrderORM.user_id == user_id)
        )
        order = result.scalar_one_or_none()

        if order is None:
            return {
                "error": True,
                "error_code": "ORDER_NOT_FOUND",
                "message": "订单不存在或不属于当前用户",
                "data": None,
            }

        # 查订单明细
        items_result = await session.execute(
            select(OrderItemORM).where(OrderItemORM.order_id == order_id)
        )
        items = items_result.scalars().all()

    order_data = {
        "id": order.id,
        "orderNo": order.order_no or "",
        "status": order.status,
        "totalAmount": float(order.total_amount) if order.total_amount is not None else None,
        "payAmount": float(order.pay_amount) if order.pay_amount is not None else None,
        "freightAmount": float(order.freight_amount) if order.freight_amount is not None else None,
        "receiverName": order.receiver_name or "",
        "receiverPhone": order.receiver_phone or "",
        "receiverAddress": order.receiver_address or "",
        "remark": order.remark or "",
        "createTime": order.create_time.isoformat() if order.create_time else None,
        "payTime": order.pay_time.isoformat() if order.pay_time else None,
        "deliveryTime": order.delivery_time.isoformat() if order.delivery_time else None,
        "receiveTime": order.receive_time.isoformat() if order.receive_time else None,
        "items": [
            {
                "id": item.id,
                "productId": item.product_id,
                "productTitle": item.product_title or "",
                "productImage": item.product_image or "",
                "skuId": item.sku_id,
                "skuProperties": item.sku_properties or "",
                "price": float(item.price) if item.price is not None else None,
                "quantity": item.quantity,
                "totalAmount": float(item.total_amount) if item.total_amount is not None else None,
            }
            for item in items
        ],
    }
    return _ok(data=order_data)


# ---- 工具集合 -------------------------------------------------------------

USER_TOOLS: list = [
    get_user_profile,
    get_user_favorites,
    get_user_browse_history,
    get_user_orders,
    get_order_detail,
]