"""Build a matrix from explicit product fact paths and dimensions."""

from __future__ import annotations

import json
import sys
from typing import Any


def _lookup_values(value: Any, parts: list[str]) -> list[Any]:
    if not parts:
        return list(value) if isinstance(value, list) else [value]
    if isinstance(value, list):
        output: list[Any] = []
        for item in value:
            output.extend(_lookup_values(item, parts))
        return output
    if not isinstance(value, dict) or parts[0] not in value:
        return []
    return _lookup_values(value[parts[0]], parts[1:])


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate(values: list[Any], mode: str) -> Any:
    if not values:
        return None
    if not mode:
        return values[0] if len(values) == 1 else values
    if mode == "count":
        return len(values)
    numbers = [number for value in values if (number := _number(value)) is not None]
    if not numbers:
        return None
    if mode == "min":
        return min(numbers)
    if mode == "max":
        return max(numbers)
    if mode == "sum":
        return sum(numbers)
    if mode == "range":
        return {"min": min(numbers), "max": max(numbers)}
    return None


def run(payload: dict[str, Any]) -> dict[str, Any]:
    products = [item for item in (payload.get("products") or []) if isinstance(item, dict)]
    dimensions: list[dict[str, str]] = []
    for raw in payload.get("dimensions") or []:
        if isinstance(raw, str) and raw.strip():
            dimensions.append({"key": raw.strip(), "label": raw.strip(), "aggregate": ""})
        elif isinstance(raw, dict) and str(raw.get("key") or "").strip():
            key = str(raw["key"]).strip()
            dimensions.append({
                "key": key,
                "label": str(raw.get("label") or key).strip(),
                "aggregate": str(raw.get("aggregate") or "").strip(),
            })
    if not dimensions:
        return {"valid": False, "matrix": [], "message": "必须提供明确的比较维度。"}

    matrix = []
    for product in products:
        matrix.append({
            "product_id": product.get("product_id") or product.get("id"),
            "title": product.get("title") or product.get("name") or "",
            "values": {
                dimension["label"]: _aggregate(
                    _lookup_values(product, dimension["key"].split(".")),
                    dimension["aggregate"],
                )
                for dimension in dimensions
            },
        })
    return {"valid": True, "dimensions": dimensions, "matrix": matrix}


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
