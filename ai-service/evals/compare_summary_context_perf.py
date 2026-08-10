"""Merge the two rolling-summary performance reports into one comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_comparison(full: dict[str, Any], rolling: dict[str, Any]) -> dict[str, Any]:
    if full.get("mode") != "full-history" or rolling.get("mode") != "rolling-summary":
        raise ValueError("reports must be full-history and rolling-summary respectively")
    if full.get("conversation_count") != rolling.get("conversation_count"):
        raise ValueError("reports must use the same conversation count")
    if full.get("continuation_turns") != rolling.get("continuation_turns"):
        raise ValueError("reports must use the same continuation-turn count")
    full_final = full.get("final_token_usage") or {}
    rolling_final = rolling.get("final_token_usage") or {}
    rolling_summary = rolling.get("summary_token_usage") or {}
    final_saving = _number(full_final.get("total")) - _number(rolling_final.get("total"))
    generation_total = _number(rolling_summary.get("total"))
    end_to_end_total = _number(rolling_final.get("total")) + generation_total
    return {
        "schema_version": "rolling-summary-long-conversation-comparison-v2",
        "conversation_count": full["conversation_count"],
        "continuation_turns": full["continuation_turns"],
        "turn_count": full.get("turn_count"),
        "full_history_run_id": full.get("evaluation_run_id"),
        "rolling_summary_run_id": rolling.get("evaluation_run_id"),
        "route_pass_rate": {
            "full_history": full.get("route_pass_rate"),
            "rolling_summary": rolling.get("route_pass_rate"),
            "delta": round(_number(rolling.get("route_pass_rate")) - _number(full.get("route_pass_rate")), 4),
        },
        "conversation_pass_rate": {
            "full_history": full.get("conversation_pass_rate"),
            "rolling_summary": rolling.get("conversation_pass_rate"),
            "delta": round(_number(rolling.get("conversation_pass_rate")) - _number(full.get("conversation_pass_rate")), 4),
        },
        "latency_ms": {
            metric: {
                "full_history": (full.get("latency_ms") or {}).get(metric),
                "rolling_summary": (rolling.get("latency_ms") or {}).get(metric),
                "delta": round(_number((rolling.get("latency_ms") or {}).get(metric)) - _number((full.get("latency_ms") or {}).get(metric)), 2),
            }
            for metric in ("p50", "p95")
        },
        "context_chars": {
            "full_history": (full.get("context_chars") or {}).get("sent_total"),
            "rolling_summary": (rolling.get("context_chars") or {}).get("sent_total"),
        },
        "token_usage": {
            "full_history_final": full_final,
            "rolling_summary_final": rolling_final,
            "rolling_summary_generation": rolling_summary,
            "final_turn_saving": round(final_saving, 2),
            "summary_generation_total": round(generation_total, 2),
            "rolling_summary_end_to_end_total": round(end_to_end_total, 2),
            "end_to_end_saving": round(_number(full_final.get("total")) - end_to_end_total, 2),
            "break_even_future_turns": (
                round(generation_total / final_saving, 2) if final_saving > 0 else None
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare rolling-summary performance reports")
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--rolling", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/summary-perf-comparison-v1.json"))
    args = parser.parse_args()
    full = json.loads(args.full.read_text(encoding="utf-8"))
    rolling = json.loads(args.rolling.read_text(encoding="utf-8"))
    comparison = build_comparison(full, rolling)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
