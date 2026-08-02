"""Build a matrix from explicit product fact paths and dimensions."""

from __future__ import annotations

import json
import sys
from typing import Any


def _lookup(item: dict[str, Any], path: str) -> Any:
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def run(payload: dict[str, Any]) -> dict[str, Any]:
    products = [item for item in (payload.get("products") or []) if isinstance(item, dict)]
    dimensions: list[dict[str, str]] = []
    for raw in payload.get("dimensions") or []:
        if isinstance(raw, str) and raw.strip():
            dimensions.append({"key": raw.strip(), "label": raw.strip()})
        elif isinstance(raw, dict) and str(raw.get("key") or "").strip():
            key = str(raw["key"]).strip()
            dimensions.append({"key": key, "label": str(raw.get("label") or key).strip()})
    if not dimensions:
        return {"valid": False, "matrix": [], "message": "必须提供明确的比较维度。"}

    matrix = []
    for product in products:
        matrix.append({
            "product_id": product.get("product_id") or product.get("id"),
            "title": product.get("title") or product.get("name") or "",
            "values": {
                dimension["label"]: _lookup(product, dimension["key"])
                for dimension in dimensions
            },
        })
    return {"valid": True, "dimensions": dimensions, "matrix": matrix}


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
