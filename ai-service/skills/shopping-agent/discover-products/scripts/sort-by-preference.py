"""Stably sort already accepted candidates by provided preference scores."""

from __future__ import annotations

import json
import sys
from typing import Any


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def run(payload: dict[str, Any]) -> dict[str, Any]:
    items = [dict(item) for item in (payload.get("items") or []) if isinstance(item, dict)]
    applicability = _score(payload.get("preference_applicability_score"))
    threshold = _score(payload.get("threshold", 0.65))
    highest = max(
        (
            _score(item.get("personalization_score", item.get("preference_relevance_score")))
            for item in items
        ),
        default=0.0,
    )
    applied = applicability >= threshold and highest >= threshold and len(items) > 1
    if applied:
        items.sort(
            key=lambda item: _score(
                item.get("personalization_score", item.get("preference_relevance_score"))
            ),
            reverse=True,
        )
    return {
        "items": items,
        "applied": applied,
        "preference_applicability_score": applicability,
        "threshold": threshold,
    }


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
