"""product_cards 构造 —— 唯一入口。

## 为什么单独一个模块
- 旧代码 `_cards_from_products` 分散在 tools/shopping_tools.py，
  每个工具都自己调，Store 又兜底一次，重复且容易漂移。
- 集中在一处后：
  - Capability 直接从 RankedProduct 生成卡片；
  - shopping/agent.py 不再需要"从 Store 兜底 last_product_cards"这段兜底路径
    （见 nodes.py 抽取逻辑）。

## 字段稳定性
和当前前端已经消费的字段保持一致：
- product_id / title / brand / price / base_price / image_url
- rating / sales_count / sub_category / reason
新增字段（score / matched_needs / risk_notes）以扩展 key 前缀 `_` 单独放，
不影响前端序列化，供调试和 A/B 观测使用。
"""

from __future__ import annotations

from typing import Any, Dict, List

from shopping.schemas import RankedProduct


def build_product_cards(
    ranked: List[RankedProduct],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """把 RankedProduct 列表转成前端卡片（对齐旧 `_cards_from_products` 字段）。

    `reason` 由 rank_reason 列表前 2 条拼接，让 LLM 拿到"为什么推荐"的抓手。
    """
    cards: List[Dict[str, Any]] = []
    for p in ranked[:limit]:
        cards.append(
            {
                "product_id": p.product_id,
                "title": p.title,
                "brand": p.brand or "",
                "price": p.price if p.price is not None else (p.base_price or 0),
                "base_price": p.base_price if p.base_price is not None else p.price,
                "image_url": p.image_url or "",
                "rating": p.rating or 0,
                "sales_count": p.sales_count or 0,
                "sub_category": p.sub_category or "",
                "reason": "；".join(p.rank_reason[:2]) or "根据你的需求匹配到的商品。",
                # 观测字段（前端可忽略）
                "_score": round(p.score, 3),
                "_matched_needs": p.matched_needs,
                "_risk_notes": p.risk_notes,
                "_recall_sources": p.recall_sources,
            }
        )
    return cards


def build_product_card_from_detail(product: Dict[str, Any]) -> Dict[str, Any]:
    """DetailCapability 用 —— 从单个商品 dict 直接建卡片。

    detail 场景商品来自 get_product_detail，不经过 rank 流程，字段偏原始。
    """
    return {
        "product_id": product.get("product_id") or product.get("id"),
        "title": product.get("title") or "",
        "brand": product.get("brand") or "",
        "price": product.get("price") or product.get("base_price") or 0,
        "base_price": product.get("base_price") or product.get("price"),
        "image_url": product.get("image_url") or "",
        "rating": product.get("rating") or 0,
        "sales_count": product.get("sales_count") or 0,
        "sub_category": product.get("sub_category") or "",
        "reason": "追问详情命中的商品。",
    }
