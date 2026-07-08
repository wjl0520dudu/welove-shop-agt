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

## 关键：resolve_products 走内部函数而非工具
- 明确 product_ids → 直接用
- query 里有"第二个/他们三/这三款" → 复用 tools.reference_tools 的 _resolve_ordinal / _resolve_plural
- 都没有 + last_product_cards 有 → 默认用上轮全部
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from shopping.schemas import CompareToolResult, ShoppingContext
from tools.reference_tools import (
    _resolve_ordinal,
    _resolve_plural,
    _resolve_pronominal,
)
from tools.shopping_tools import (
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
    if not product_ids:
        return []
    from shopping.vector_store import get_product_milvus_store
    from pymilvus import Collection

    try:
        store = get_product_milvus_store()
        collection = Collection(store.collection_name)
        collection.load()
        ids_expr = ", ".join(str(int(x)) for x in product_ids)
        rows = collection.query(
            expr=f"product_id in [{ids_expr}]",
            output_fields=[
                "product_id", "title", "brand", "image_url", "description",
                "category", "sub_category", "tags",
                "base_price", "rating", "sales_count", "review_count",
            ],
            limit=len(product_ids),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Milvus query 商品主档失败 product_ids=%s", product_ids, exc_info=True)
        return []

    # 保持传入顺序
    by_id: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        pid = int(r.get("product_id") or 0)
        base_price = float(r.get("base_price") or 0)
        by_id[pid] = {
            "product_id": pid,
            "title": r.get("title") or "",
            "brand": r.get("brand") or "",
            "price": base_price,
            "base_price": base_price,
            "image_url": r.get("image_url") or "",
            "description": r.get("description") or "",
            "category": r.get("category") or "",
            "sub_category": r.get("sub_category") or "",
            "tags": r.get("tags") or "",
            "rating": float(r.get("rating") or 0),
            "sales_count": int(r.get("sales_count") or 0),
            "review_count": int(r.get("review_count") or 0),
        }
    return [by_id[pid] for pid in product_ids if pid in by_id]


def _resolve_products_from_query(
    query: str,
    ctx: ShoppingContext,
) -> List[Dict[str, Any]]:
    """query 有指代词时定位对比商品。

    复用 tools.reference_tools 里的解析器。命中 plural / plural_compare
    时用 matched_products 列表；命中 ordinal / pronominal 时用单商品。
    """
    if not ctx.last_product_cards:
        return []

    # 优先复数（"这三款/他们三"），复数直接给多个商品
    plural = _resolve_plural(query, ctx.last_product_cards)
    if plural and plural.get("matched_products"):
        return list(plural["matched_products"])

    # 序号 + 代词：单商品，凑不齐两个就返回空让上游 clarify
    single: List[Dict[str, Any]] = []
    ordinal = _resolve_ordinal(query, ctx.last_product_cards)
    if ordinal and ordinal.get("matched_product"):
        single.append(ordinal["matched_product"])
    pronominal = _resolve_pronominal(query, ctx.last_focused_product, ctx.last_product_cards)
    if pronominal and pronominal.get("matched_product"):
        m = pronominal["matched_product"]
        if not any(_same_product(m, p) for p in single):
            single.append(m)
    return single


def _same_product(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a.get("product_id") or a.get("id")) == (b.get("product_id") or b.get("id"))


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

        # ── 1. resolve products ──
        products: List[Dict[str, Any]] = []

        if product_ids:
            products = await _load_products_by_ids(product_ids)
            trace.append({"step": "resolve", "output": {"source": "product_ids", "count": len(products)}})
        else:
            # 尝试从 query 里解析指代
            resolved = _resolve_products_from_query(query, context)
            if resolved and len(resolved) >= 2:
                products = resolved
                trace.append({"step": "resolve", "output": {"source": "reference", "count": len(products)}})
            elif context.last_product_cards and len(context.last_product_cards) >= 2:
                # 兜底：用上一轮推荐的全部（"帮我对比" 这种没指代但有上下文的）
                products = list(context.last_product_cards)
                trace.append({"step": "resolve", "output": {"source": "last_product_cards", "count": len(products)}})

        if len(products) < 2:
            return CompareToolResult(
                action="clarify",
                clarify_question=(
                    "你想对比哪几款商品？可以告诉我商品名，"
                    "或者我先给你推荐几款再对比。"
                ),
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


def _explain_pick(best: Dict[str, Any], focus: str) -> str:
    if focus == "price":
        return f"「{best.get('title')}」在几款里价格最有优势（{best.get('价格')}元）。"
    if focus == "rating":
        return f"「{best.get('title')}」评分最高（{best.get('评分')}）。"
    if focus == "sales":
        return f"「{best.get('title')}」销量最好（{best.get('销量')}）。"
    return f"综合评分/销量，我更推荐「{best.get('title')}」。"
