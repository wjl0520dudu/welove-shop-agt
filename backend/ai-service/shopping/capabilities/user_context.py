"""UserShoppingContextCapability —— 个性化上下文。

## MVP 定位（Phase 1a stub）
- 只返回 users 表 profile + Store 里的 user_preferences；
- **不深挖 favorites / browse_history / orders 的商品向量维度**——
  那是 Phase 2 商品搬 Milvus 后再做的活。
- 未登录时优雅返回 {is_logged_in: False, message: 需要登录}。

## 与用户诉求的关系
用户诉求：`get_user_shopping_context` 先 stub，能拿到就 ok。
Phase 2 时再补 favorites 品类/品牌统计、browse_history 高频类目等。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from shopping.schemas import ShoppingContext
from sqlalchemy import select

from core.database import get_session_factory

logger = logging.getLogger("ai-service.shopping.user_context")


class UserShoppingContextCapability:
    async def run(
        self,
        context: ShoppingContext,
        include_favorites: bool = False,
        include_browse_history: bool = False,
        include_orders: bool = False,
    ) -> Dict[str, Any]:
        """返回统一 dict（不用 Pydantic model 是因为字段随开关变）。"""
        if not context.is_logged_in or not context.user_id:
            return {
                "error": True,
                "error_code": "LOGIN_REQUIRED",
                "data": {"is_logged_in": False},
                "message": "该功能需要登录后使用，请引导用户先登录。",
            }

        data: Dict[str, Any] = {
            "is_logged_in": True,
            "user_id": context.user_id,
            "profile": None,
            "preferences": dict(context.user_preferences or {}),
        }

        # ── 从 PG 读 users 表基础 profile（skin_type / gender / preference_tags / profile JSONB）──
        try:
            from shopping.orm_models import UserORM
            session_factory = get_session_factory()
            async with session_factory() as session:
                user = (await session.execute(
                    select(UserORM).where(UserORM.id == int(context.user_id))
                )).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            logger.warning("user_context: query users failed", exc_info=True)
            user = None

        if user is not None:
            data["profile"] = {
                "skin_type": user.skin_type or "",
                "gender": user.gender,
                "age_range": user.age_range or "",
                "preference_tags": user.preference_tags or [],
                "profile": user.profile or {},
            }

        # ── favorites / browse / orders：MVP stub，只返回"是否要展开"标志 ──
        if include_favorites:
            data["favorites_summary"] = {"status": "not_implemented", "note": "Phase 2 提供收藏商品品类/品牌统计"}
        if include_browse_history:
            data["browse_summary"] = {"status": "not_implemented", "note": "Phase 2 提供最近浏览的高频类目"}
        if include_orders:
            data["orders_summary"] = {"status": "not_implemented", "note": "Phase 2 提供订单商品品类统计"}

        return {"error": False, "data": data, "message": "OK"}
