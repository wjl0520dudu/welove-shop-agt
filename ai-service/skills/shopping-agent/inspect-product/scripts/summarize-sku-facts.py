"""Summarize trusted SKU price and stock facts."""

from __future__ import annotations

import json
import sys
from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stock(sku: dict[str, Any]) -> int:
    raw = sku.get("stock") if sku.get("stock") is not None else sku.get("stock_quantity")
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def run(payload: dict[str, Any]) -> dict[str, Any]:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    skus = payload.get("skus") if isinstance(payload.get("skus"), list) else product.get("skus") or []
    skus = [dict(item) for item in skus if isinstance(item, dict)]
    prices = []
    available = 0
    total_stock = 0
    variants = []
    for sku in skus:
        price = _number(sku.get("price") if sku.get("price") is not None else sku.get("sale_price"))
        if price is not None:
            prices.append(price)
        stock = _stock(sku)
        total_stock += stock
        status = str(sku.get("status") or "").strip().lower()
        if stock > 0 and status not in {"inactive", "off_sale", "disabled"}:
            available += 1
        variants.append({
            "sku_id": sku.get("sku_id") or sku.get("id"),
            "name": sku.get("name") or sku.get("sku_name") or "",
            "price": price,
            "stock": stock,
            "attributes": sku.get("attributes") or sku.get("specs") or {},
        })
    return {
        "product_id": product.get("product_id") or product.get("id"),
        "sku_count": len(skus),
        "available_sku_count": available,
        "total_stock": total_stock,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "variants": variants,
    }


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
