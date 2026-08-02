"""Normalize exact numeric-unit strings for deterministic comparison."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


_VALUE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z\u4e00-\u9fff]+)\s*$")
_UNITS = {
    "kg": (1000.0, "g"), "千克": (1000.0, "g"), "公斤": (1000.0, "g"),
    "g": (1.0, "g"), "克": (1.0, "g"),
    "l": (1000.0, "ml"), "L": (1000.0, "ml"), "升": (1000.0, "ml"),
    "ml": (1.0, "ml"), "mL": (1.0, "ml"), "毫升": (1.0, "ml"),
    "m": (1000.0, "mm"), "米": (1000.0, "mm"),
    "cm": (10.0, "mm"), "厘米": (10.0, "mm"),
    "mm": (1.0, "mm"), "毫米": (1.0, "mm"),
    "tb": (1024.0, "GB"), "TB": (1024.0, "GB"),
    "gb": (1.0, "GB"), "GB": (1.0, "GB"),
    "mb": (1.0 / 1024.0, "GB"), "MB": (1.0 / 1024.0, "GB"),
    "h": (1.0, "h"), "小时": (1.0, "h"),
    "mah": (1.0, "mAh"), "mAh": (1.0, "mAh"),
    "wh": (1.0, "Wh"), "Wh": (1.0, "Wh"),
}


def _normalize(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    match = _VALUE.match(value)
    if not match or match.group(2) not in _UNITS:
        return value
    factor, unit = _UNITS[match.group(2)]
    normalized = float(match.group(1)) * factor
    return {"raw": value, "value": normalized, "unit": unit}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for raw in payload.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        rows.append({key: _normalize(value) for key, value in raw.items()})
    return {"rows": rows, "count": len(rows)}


if __name__ == "__main__":
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(run(payload), ensure_ascii=False).encode("utf-8"))
