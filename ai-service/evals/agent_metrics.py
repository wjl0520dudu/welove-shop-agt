"""Aggregations shared by Agent Contract, DeepEval and RAGAS reports."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable


def calculate_agent_metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    total = len(items)
    if not total:
        return _empty_metrics()

    contract_passed = sum(bool(row.get("contract", {}).get("passed")) for row in items)
    task_passed = sum(_task_passed(row) for row in items)
    failure_reasons: Counter[str] = Counter()
    scenarios: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in items:
        scenarios[str(row.get("scenario") or "uncategorized")].append(row)
        failure_reasons.update(row.get("contract", {}).get("failure_reasons") or [])
        judge = row.get("judge") or {}
        if judge.get("enabled") and judge.get("passed") is False:
            failure_reasons["judge_failed"] += 1
        if (row.get("ragas") or {}).get("error"):
            failure_reasons["ragas_error"] += 1

    latencies = _numbers(row.get("latency_ms") for row in items)
    ttfts = _numbers(row.get("ttft_ms") for row in items)
    token_rows = [row.get("token_usage") or {} for row in items if (row.get("token_usage") or {}).get("available")]
    return {
        "case_count": total,
        "contract_pass_rate": _ratio(contract_passed, total),
        "task_success_rate": _ratio(task_passed, total),
        "pass@1": _ratio(task_passed, total),
        "latency_ms": _latency_summary(latencies),
        "ttft_ms": _latency_summary(ttfts),
        "token_usage": _token_summary(token_rows),
        "scenario_breakdown": {
            name: {
                "case_count": len(group),
                "contract_pass_rate": _ratio(sum(bool(row.get("contract", {}).get("passed")) for row in group), len(group)),
                "task_success_rate": _ratio(sum(_task_passed(row) for row in group), len(group)),
            }
            for name, group in sorted(scenarios.items())
        },
        "failure_reason_counts": dict(sorted(failure_reasons.items())),
    }


def compare_reports(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Return explicit numeric deltas and newly failing case IDs."""
    current_metrics = current.get("metrics") or {}
    baseline_metrics = baseline.get("metrics") or {}
    keys = ("contract_pass_rate", "task_success_rate", "pass@1")
    deltas = {
        key: round(float(current_metrics.get(key, 0.0)) - float(baseline_metrics.get(key, 0.0)), 4)
        for key in keys
    }
    performance_deltas = {
        name: _optional_delta(
            (current_metrics.get(name) or {}).get("p95"),
            (baseline_metrics.get(name) or {}).get("p95"),
        )
        for name in ("latency_ms", "ttft_ms")
    }
    quality_deltas: dict[str, float] = {}
    for section in ("ragas_summary", "retrieval_summary"):
        current_values = (current.get(section) or {}).get("metrics") or {}
        baseline_values = (baseline.get(section) or {}).get("metrics") or {}
        for key in sorted(set(current_values) & set(baseline_values)):
            delta = _optional_delta(current_values.get(key), baseline_values.get(key))
            if delta is not None:
                quality_deltas[f"{section}.{key}"] = delta
    current_failed = {
        str(row.get("id")) for row in current.get("cases") or [] if not _task_passed(row)
    }
    baseline_failed = {
        str(row.get("id")) for row in baseline.get("cases") or [] if not _task_passed(row)
    }
    return {
        "metric_deltas": deltas,
        "performance_p95_deltas_ms": performance_deltas,
        "quality_metric_deltas": quality_deltas,
        "new_failures": sorted(current_failed - baseline_failed),
        "fixed_cases": sorted(baseline_failed - current_failed),
    }


def _task_passed(row: dict[str, Any]) -> bool:
    if not bool((row.get("contract") or {}).get("passed")):
        return False
    judge = row.get("judge") or {}
    return not judge.get("enabled") or judge.get("passed") is not False


def _empty_metrics() -> dict[str, Any]:
    return {
        "case_count": 0,
        "contract_pass_rate": 0.0,
        "task_success_rate": 0.0,
        "pass@1": 0.0,
        "latency_ms": _latency_summary([]),
        "ttft_ms": _latency_summary([]),
        "token_usage": _token_summary([]),
        "scenario_breakdown": {},
        "failure_reason_counts": {},
    }


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"sample_count": 0, "p50": None, "p95": None, "mean": None}
    return {
        "sample_count": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "mean": round(sum(values) / len(values), 2),
    }


def _numbers(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return out


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    value = ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 2)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _optional_delta(current: Any, baseline: Any) -> float | None:
    if current is None or baseline is None:
        return None
    try:
        return round(float(current) - float(baseline), 4)
    except (TypeError, ValueError):
        return None


def _token_summary(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    """Aggregate only token usage read from real LangSmith LLM leaf runs."""

    values: dict[str, list[float]] = {"input_tokens": [], "output_tokens": [], "total_tokens": []}
    for row in rows:
        for key in values:
            try:
                values[key].append(float(row.get(key) or 0))
            except (TypeError, ValueError):
                continue
    total_values = values["total_tokens"]
    return {
        "sample_count": len(rows),
        "input_total": int(sum(values["input_tokens"])),
        "output_total": int(sum(values["output_tokens"])),
        "total": int(sum(total_values)),
        "total_p50": _percentile(total_values, 0.50) if total_values else None,
        "total_p95": _percentile(total_values, 0.95) if total_values else None,
        "total_mean": round(sum(total_values) / len(total_values), 2) if total_values else None,
    }
