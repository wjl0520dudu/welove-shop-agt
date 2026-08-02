"""CompareCapability —— 商品对比。

## Pipeline
```
resolve_products(query, product_ids, context)
  ↓
if len < 2: return clarify
  ↓
load_product_details(pids)         # 复用旧 shopping_tools.get_product_detail 逻辑
  ↓
_extract_product_features(products) # 复用旧 LLM 特征抽取
  ↓
build_comparison_rows
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


async def _load_products_by_ids(product_ids: List[int]) -> List[Dict[str, Any]]:
    """按 product_id 列表批量拉商品主档。

    Phase 1b 起走 Milvus（商品数据在 product_mm_collection），
    跟 DetailCapability._load_product_detail_raw 保持同一数据源。
    """
    from app.infrastructure.vectorstores.product.active_store import load_active_products_by_ids

    return load_active_products_by_ids(product_ids)


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
        del query  # Open comparison dimensions are understood by the Agent.

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

        # 旧回滚 Tool 保留特征抽取，但不再通过关键词 focus 替 Agent 选赢家。
        features = await _extract_product_features(products)
        trace.append({"step": "extract_features", "output": {
            "product_ids": [int(p.get("product_id") or p.get("id", 0)) for p in products],
        }})

        # 组装完整事实行，比较维度与结论由 Agent 根据当前问题理解。
        rows: List[Dict[str, Any]] = []
        for p in products:
            pid = int(p.get("product_id") or p.get("id", 0))
            f = features.get(pid, ProductFeatures())
            rows.append(_row_from_product(p, f))

        cards = _cards_from_products(products, limit=len(products))

        return CompareToolResult(
            action="compare",
            products=products,
            dimensions=_COMPARE_DIMENSIONS,
            comparison_rows=rows,
            suggestion={},
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
