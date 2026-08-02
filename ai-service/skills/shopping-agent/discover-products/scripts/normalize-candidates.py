"""Normalize candidate field aliases without making semantic decisions."""

from __future__ import annotations

import json
import sys
from typing import Any


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace("，", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def run(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates") or []
    normalized: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        product_id = _positive_int(raw.get("product_id") or raw.get("id"))
        title = str(raw.get("title") or raw.get("name") or "").strip()
        price = _number(raw.get("price") if raw.get("price") is not None else raw.get("base_price"))
        if product_id is not None:
            item["product_id"] = product_id
        if title:
            item["title"] = title
        if price is not None:
            item["price"] = price
        item["brand"] = str(raw.get("brand") or "").strip()
        item["category"] = str(raw.get("category") or raw.get("category_name") or "").strip()
        item["sub_category"] = str(raw.get("sub_category") or raw.get("subCategory") or "").strip()
        item["tags"] = _strings(raw.get("tags"))
        normalized.append(item)
    return {"candidates": normalized, "count": len(normalized)}


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
