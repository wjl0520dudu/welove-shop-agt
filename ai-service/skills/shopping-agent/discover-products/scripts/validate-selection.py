"""Validate one-based candidate selections atomically."""

from __future__ import annotations

import json
import sys
from typing import Any


def run(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in (payload.get("candidates") or []) if isinstance(item, dict)]
    raw_indices = payload.get("selected_indices") or []
    allowed_statuses = {
        str(value).strip().lower()
        for value in (payload.get("allowed_statuses") or ["exact", "alternative"])
        if str(value).strip()
    }
    indices: list[int] = []
    invalid: list[Any] = []
    for raw in raw_indices:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            invalid.append(raw)
            continue
        if index < 1 or index > len(candidates):
            invalid.append(raw)
        elif index not in indices:
            indices.append(index)

    selected: list[dict[str, Any]] = []
    for index in indices:
        candidate = candidates[index - 1]
        status = str(candidate.get("match_status") or "").strip().lower()
        product_id = candidate.get("product_id") or candidate.get("id")
        if product_id in (None, "") or (status and status not in allowed_statuses):
            invalid.append(index)
            continue
        selected.append(candidate)

    if invalid:
        return {
            "valid": False,
            "invalid_indices": invalid,
            "selected_indices": [],
            "selected_candidates": [],
            "message": "候选选择包含越界编号、缺失商品 ID 或不允许的匹配状态。",
        }
    return {
        "valid": True,
        "invalid_indices": [],
        "selected_indices": indices,
        "selected_candidates": selected,
    }


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
