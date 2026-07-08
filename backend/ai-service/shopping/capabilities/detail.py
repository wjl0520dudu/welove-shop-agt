"""DetailCapability —— 单商品详情追问。

## Pipeline
```
resolve_single_product(query, product_id, context)
  ↓ 未找到 → clarify
load_product_detail(pid)             (复用 tools.shopping_tools 内部逻辑)
  ↓
extract_focus(query)                  # price/stock/sku/overview/suitability/ingredients
  ↓
build_facts(product, focus)
  ↓
DetailToolResult
```

## focus 分派
- price     → 返回 base_price + SKU 价位区间
- stock/sku → 返回 SKU 列表（含 stock）
- overview  → 返回 description + tags
- suitability → 返回 tags 中"适合"相关的关键词 + rating
- ingredients → 用旧 LLM 特征抽取 core_ingredients / concentration
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agents.memory import remember_focused_product
from shopping.cards import build_product_card_from_detail
from shopping.schemas import DetailToolResult, ShoppingContext
from tools.reference_tools import (
    _resolve_implicit,
    _resolve_ordinal,
    _resolve_pronominal,
)
from tools.shopping_tools import _extract_product_features, get_product_detail

logger = logging.getLogger("ai-service.shopping.detail")


_FOCUS_KEYWORDS: Dict[str, List[str]] = {
    "price": ["多少钱", "价格", "什么价"],
    "stock": ["有货", "库存", "缺货", "现货"],
    "sku": ["规格", "色号", "尺寸", "型号", "版本"],
    "suitability": ["适合我", "适合什么肤质", "肤质合适"],
    "ingredients": ["成分", "含有什么", "什么成分"],
    # overview 兜底
}


def _extract_focus(query: str) -> str:
    for focus, keywords in _FOCUS_KEYWORDS.items():
        if any(k in query for k in keywords):
            return focus
    return "overview"


def _resolve_product_id(
    query: str,
    product_id: Optional[int],
    ctx: ShoppingContext,
) -> Optional[int]:
    """从四种来源定位 product_id：
    1. 显式 product_id 参数
    2. query 中的指代（第二个/刚才那个/它）
    3. last_focused_product 兜底
    4. last_product_cards 只有一张卡 → 就是它（用户"有其他色号吗"）
    """
    if product_id:
        return int(product_id)

    if ctx.last_product_cards:
        # 序号
        r = _resolve_ordinal(query, ctx.last_product_cards)
        if r and r.get("matched_product"):
            pid = r["matched_product"].get("product_id")
            if pid:
                return int(pid)

        # 代词
        r = _resolve_pronominal(query, ctx.last_focused_product, ctx.last_product_cards)
        if r and r.get("matched_product"):
            pid = r["matched_product"].get("product_id")
            if pid:
                return int(pid)

    # 隐式："多少钱/有货吗" 指向 last_focused_product
    r = _resolve_implicit(query, ctx.last_focused_product)
    if r and r.get("matched_product"):
        pid = r["matched_product"].get("product_id")
        if pid:
            return int(pid)

    # 单一 focused_product 兜底
    if ctx.last_focused_product:
        pid = ctx.last_focused_product.get("product_id")
        if pid:
            return int(pid)

    # 上一轮只有 1 张卡：追问必然指向它
    if len(ctx.last_product_cards) == 1:
        pid = ctx.last_product_cards[0].get("product_id")
        if pid:
            return int(pid)

    return None


async def _load_product_detail_raw(product_id: int) -> Dict[str, Any]:
    """调用旧 get_product_detail 工具的内部函数版（不经过 @tool 封装）。

    get_product_detail 是 @tool 装饰过的，直接 ainvoke 也行；这里手动构 runtime state。
    """
    # 直接 invoke 工具：@tool 支持 async invoke，但需要 runtime 参数
    # 简单做法：把 tool 里的 SQL 逻辑抄一次，避免依赖 runtime。改成直接查库。
    from sqlalchemy import select
    from core.database import get_session_factory
    from shopping.orm_models import ProductORM, ProductSkuORM
    from tools.shopping_tools import _dump_product

    session_factory = get_session_factory()
    async with session_factory() as session:
        product = (await session.execute(
            select(ProductORM).where(ProductORM.id == product_id)
        )).scalar_one_or_none()
        if not product:
            return {}
        sku_rows = (await session.execute(
            select(ProductSkuORM).where(ProductSkuORM.product_id == product_id)
        )).scalars().all()

    data = _dump_product(product)
    data["skus"] = [
        {
            "id": s.id,
            "skuCode": s.sku_code or "",
            "properties": s.properties or {},
            "price": float(s.price) if s.price is not None else None,
            "stock": s.stock,
            "isDefault": s.is_default,
        }
        for s in sku_rows
    ]
    return data


def _build_facts(product: Dict[str, Any], focus: str) -> Dict[str, Any]:
    """按 focus 组装 facts 字段。"""
    skus: List[Dict[str, Any]] = product.get("skus") or []
    if focus == "price":
        prices = [s["price"] for s in skus if s.get("price") is not None]
        return {
            "price": product.get("price"),
            "base_price": product.get("base_price"),
            "sku_price_range": (min(prices), max(prices)) if prices else None,
            "sku_count": len(skus),
        }
    if focus in ("stock", "sku"):
        total_stock = sum(int(s.get("stock") or 0) for s in skus)
        return {
            "skus": skus,
            "sku_count": len(skus),
            "total_stock": total_stock,
            "in_stock": total_stock > 0,
        }
    if focus == "suitability":
        tags = product.get("tags") or ""
        return {
            "tags": tags,
            "rating": product.get("rating"),
            "sales_count": product.get("sales_count"),
            "sub_category": product.get("sub_category"),
        }
    # overview 兜底
    return {
        "description": product.get("description") or "",
        "tags": product.get("tags") or "",
        "rating": product.get("rating"),
        "sales_count": product.get("sales_count"),
        "brand": product.get("brand"),
    }


async def _build_facts_ingredients(product: Dict[str, Any]) -> Dict[str, Any]:
    """成分类问法：走一次 LLM 特征抽取。"""
    features_map = await _extract_product_features([product])
    pid = int(product.get("product_id") or product.get("id", 0))
    features = features_map.get(pid)
    if features is None:
        return {"core_ingredients": [], "concentration": "", "cautions": []}
    return {
        "core_ingredients": features.core_ingredients,
        "concentration": features.concentration,
        "cautions": features.cautions,
        "suitable_skin": features.suitable_skin,
    }


class DetailCapability:
    async def run(
        self,
        query: str,
        context: ShoppingContext,
        product_id: Optional[int] = None,
    ) -> DetailToolResult:
        trace: List[Dict[str, Any]] = []

        pid = _resolve_product_id(query, product_id, context)
        trace.append({"step": "resolve_product", "output": {"product_id": pid}})
        if pid is None:
            return DetailToolResult(
                action="clarify",
                clarify_question=(
                    "你想了解哪个商品呢？可以告诉我商品名，或者说「第一个/第二个」，"
                    "我按上轮推荐给你查。"
                ),
                trace=trace,
            )

        product = await _load_product_detail_raw(pid)
        if not product:
            return DetailToolResult(
                action="empty",
                empty_reason=f"商品 {pid} 不存在或已下架。",
                trace=trace,
            )
        trace.append({"step": "load_detail", "output": {"product_id": pid}})

        focus = _extract_focus(query)
        trace.append({"step": "extract_focus", "output": focus})

        if focus == "ingredients":
            facts = await _build_facts_ingredients(product)
        else:
            facts = _build_facts(product, focus)

        card = build_product_card_from_detail(product)
        await remember_focused_product(context.conversation_id, context.user_id, card)

        return DetailToolResult(
            action="detail",
            product=product,
            focus=focus,  # type: ignore[arg-type]
            facts=facts,
            product_cards=[card],
            trace=trace,
        )
