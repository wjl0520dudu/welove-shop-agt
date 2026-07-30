"""CompareCapability —— 商品对比。

## Pipeline
```
resolve_products(query, product_ids, context)
  ↓
if len < 2: return clarify
  ↓
load_product_details(pids)         # 复用旧 shopping_tools.get_product_detail 逻辑
  ↓
extract_focus(query)                # price/rating/skin_type/…
  ↓
_extract_product_features(products) # 复用旧 LLM 特征抽取
  ↓
build_comparison_rows + choose_best_by_focus
  ↓
CompareToolResult
```

## 商品绑定
Compare 只接受 Router 已绑定的商品 ID。它不从 query、历史商品卡或
focused product 中重新解析“第几个”“它们”等跨轮指代。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.domain.shopping.schemas import CompareToolResult, ShoppingContext
from app.domain.shopping.tools.shopping_tools import (
    ProductFeatures,
    _cards_from_products,
    _extract_product_features,
)

logger = logging.getLogger("ai-service.shopping.compare")


# 对比维度顺序：基础维度在前，抽取维度在后
_COMPARE_DIMENSIONS = [
    "价格", "评分", "销量",
    "核心成分", "浓度", "适合肤质", "主打功效", "质地/使用感", "注意事项",
]


# focus 关键词：告诉排序器"用户最关心哪个维度"，给建议时用
_FOCUS_MAP: Dict[str, List[str]] = {
    "price": ["便宜", "性价比", "预算", "实惠", "多少钱"],
    "rating": ["评分", "口碑", "评价"],
    "sales": ["销量", "热卖", "卖得好"],
    "skin_type": ["敏感肌", "油皮", "干皮", "混油", "肤质"],
    "benefits": ["功效", "效果", "作用"],
}


def _extract_focus(query: str) -> str:
    """从 query 提取用户最关心的对比维度。"""
    for focus, keywords in _FOCUS_MAP.items():
        if any(k in query for k in keywords):
            return focus
    return "match"


async def _load_products_by_ids(product_ids: List[int]) -> List[Dict[str, Any]]:
    """按 product_id 列表批量拉商品主档。

    Phase 1b 起走 Milvus（商品数据在 product_mm_collection），
    跟 DetailCapability._load_product_detail_raw 保持同一数据源。
    """
    from app.infrastructure.vectorstores.product.active_store import load_active_products_by_ids

    return load_active_products_by_ids(product_ids)


def _pick_best_by_focus(
    rows: List[Dict[str, Any]],
    focus: str,
) -> Optional[Dict[str, Any]]:
    """按 focus 挑一个最佳。行结构见 _row_from_product（价格/评分/销量是中文键）。"""
    if not rows:
        return None
    if focus == "price":
        return min(rows, key=lambda r: float(r.get("价格") or 1e12))
    if focus == "rating":
        return max(rows, key=lambda r: float(r.get("评分") or 0))
    if focus == "sales":
        return max(rows, key=lambda r: int(r.get("销量") or 0))
    # match / benefits / skin_type：rating * 0.6 + sales_norm * 0.4
    max_sales = max((int(r.get("销量") or 0) for r in rows), default=1) or 1
    return max(rows, key=lambda r: (
        0.6 * (float(r.get("评分") or 0) / 5.0)
        + 0.4 * (int(r.get("销量") or 0) / max_sales)
    ))


def _row_from_product(p: Dict[str, Any], features: ProductFeatures) -> Dict[str, Any]:
    """把商品 dict + features 拉平成一行对比。"""
    return {
        "product_id": p.get("product_id") or p.get("id"),
        "title": p.get("title") or "",
        "价格": p.get("price") or p.get("base_price"),
        "评分": p.get("rating"),
        "销量": p.get("sales_count"),
        "核心成分": features.core_ingredients,
        "浓度": features.concentration,
        "适合肤质": features.suitable_skin,
        "主打功效": features.key_benefits,
        "质地/使用感": features.texture,
        "注意事项": features.cautions,
    }


class CompareCapability:
    async def run(
        self,
        query: str,
        context: ShoppingContext,
        product_ids: Optional[List[int]] = None,
    ) -> CompareToolResult:
        trace: List[Dict[str, Any]] = []

        # Router is the sole cross-turn resolver.  A caller may narrow the
        # bound set, but must never introduce arbitrary ids or use a history
        # fallback inside this Capability.
        bound_ids = _normalise_product_ids(context.selected_product_ids)
        requested_ids = _normalise_product_ids(product_ids) if product_ids else bound_ids
        if not bound_ids or len(requested_ids) < 2 or any(product_id not in bound_ids for product_id in requested_ids):
            return CompareToolResult(
                action="clarify",
                clarify_question=(
                    "你想对比哪几款商品？可以告诉我商品名，"
                    "或者我先给你推荐几款再对比。"
                ),
                trace=trace,
            )

        products = await _load_products_by_ids(requested_ids)
        trace.append({"step": "resolve", "output": {
            "source": "router_bound_product_ids",
            "requested_count": len(requested_ids),
            "count": len(products),
        }})
        if len(products) < 2:
            return CompareToolResult(
                action="empty",
                empty_reason="已确认的商品不存在或已下架，暂时无法完成对比。",
                trace=trace,
            )

        # ── 2. focus 抽取 ──
        focus = _extract_focus(query)
        trace.append({"step": "extract_focus", "output": focus})

        # ── 3. 特征抽取（复用旧 LLM）──
        features = await _extract_product_features(products)
        trace.append({"step": "extract_features", "output": {
            "product_ids": [int(p.get("product_id") or p.get("id", 0)) for p in products],
        }})

        # ── 4. 组装 rows + 挑最佳 ──
        rows: List[Dict[str, Any]] = []
        for p in products:
            pid = int(p.get("product_id") or p.get("id", 0))
            f = features.get(pid, ProductFeatures())
            rows.append(_row_from_product(p, f))

        best = _pick_best_by_focus(rows, focus)
        suggestion: Dict[str, Any] = {}
        if best:
            suggestion = {
                "focus": focus,
                "recommended_product_id": best.get("product_id"),
                "recommended_title": best.get("title"),
                "reason": _explain_pick(best, focus),
            }
        trace.append({"step": "choose_best", "output": suggestion})

        cards = _cards_from_products(products, limit=len(products))

        return CompareToolResult(
            action="compare",
            products=products,
            dimensions=_COMPARE_DIMENSIONS,
            comparison_rows=rows,
            suggestion=suggestion,
            product_cards=cards,
            trace=trace,
        )


def _normalise_product_ids(values: Optional[List[int]]) -> List[int]:
    ids: List[int] = []
    for value in values or []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in ids:
            ids.append(product_id)
    return ids


def _explain_pick(best: Dict[str, Any], focus: str) -> str:
    if focus == "price":
        return f"「{best.get('title')}」在几款里价格最有优势（{best.get('价格')}元）。"
    if focus == "rating":
        return f"「{best.get('title')}」评分最高（{best.get('评分')}）。"
    if focus == "sales":
        return f"「{best.get('title')}」销量最好（{best.get('销量')}）。"
    return f"综合评分/销量，我更推荐「{best.get('title')}」。"
