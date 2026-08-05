"""Compare full history with the production rolling-summary representation.

The evaluation is deliberately AI-service-only.  It models the context that
chat-service would supply after 20 visible messages trigger one asynchronous
summary, then sends three continuous follow-up questions for every scenario.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.infrastructure.config import config
from evals.langsmith_experiment import summarize_trace_token_usage
from evals.run_agent_eval import _evaluation_headers, build_evaluation_trace_context
from evals.summary_context_cases import summary_context_cases


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[round((len(values) - 1) * quantile)], 2)


def _content_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(message.get("content") or "")) for message in messages)


def _expand_old_prefix(messages: list[dict[str, Any]], *, minimum_chars: int, minimum_messages: int) -> list[dict[str, Any]]:
    """Make fixtures long enough without using production history or extra LLM calls."""

    expanded = [dict(message) for message in messages]
    filler = "已确认的历史讨论细节保持不变：当前主题、需求、限制条件与已说明事实均需在后续继续沿用。"
    chars_needed = max(0, minimum_chars - _content_chars(expanded))
    if chars_needed:
        expanded.append({"role": "assistant", "content": filler * (chars_needed // len(filler) + 1)})
    while len(expanded) < minimum_messages:
        role = "user" if len(expanded) % 2 == 0 else "assistant"
        expanded.append({"role": role, "content": "请继续保留以上已确认的会话事实。"})
    return expanded


def _rolling_history(messages: list[dict[str, Any]], *, covered_count: int, keep_messages: int) -> list[dict[str, Any]]:
    """Return the raw bridge plus retained recent messages; never drop pending text."""

    recent_start = max(0, len(messages) - max(1, keep_messages))
    pending_start = min(max(0, covered_count), recent_start)
    return [dict(item) for item in messages[pending_start:]]


def _post(client: httpx.Client, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = client.post(url, json=payload, headers=headers)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    return response.json(), elapsed_ms


def _headers(*, run_id: str, case_id: str, variant: str, operation: str, turn: int | None = None) -> dict[str, str]:
    trace = build_evaluation_trace_context(
        {"run_id": run_id, "dataset": "rolling-summary-long-conversation-v3", "variant": variant},
        case_id=case_id,
        operation=operation,
    )
    headers = _evaluation_headers(trace)
    if turn is not None:
        headers["X-Evaluation-Turn"] = str(turn)
    return headers


def _token_totals(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    usage = [item.get(key) or {} for item in items if (item.get(key) or {}).get("available")]
    return {
        "sample_count": len(usage),
        "input_total": sum(int(item.get("input_tokens") or 0) for item in usage),
        "output_total": sum(int(item.get("output_tokens") or 0) for item in usage),
        "total": sum(int(item.get("total_tokens") or 0) for item in usage),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate full history versus rolling summary over long conversations")
    parser.add_argument("--mode", choices=("full-history", "rolling-summary"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/assistant")
    parser.add_argument("--evaluation-run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--continuation-turns", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--trigger-message-count", type=int, default=config.CONVERSATION_SUMMARY_TRIGGER_MESSAGES)
    parser.add_argument("--keep-messages", type=int, default=config.CONVERSATION_SUMMARY_KEEP_MESSAGES)
    parser.add_argument("--minimum-old-prefix-chars", type=int, default=8000)
    parser.add_argument("--summary-max-chars", type=int, default=config.CONVERSATION_SUMMARY_MAX_CHARS)
    parser.add_argument("--case-limit", type=int, default=20, help="run the first N controlled scenarios; use 2 for a low-cost preflight")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not config.LANGSMITH_TRACING or not config.LANGSMITH_API_KEY:
        parser.error("LANGSMITH_TRACING=true and LANGSMITH_API_KEY are required")
    if args.trigger_message_count < 2 or args.keep_messages < 1 or args.minimum_old_prefix_chars < 1 or args.case_limit < 1:
        parser.error("trigger/keep/old-prefix values must be positive; trigger must be at least 2")
    expected_summary_enabled = args.mode == "rolling-summary"
    if config.CONVERSATION_SUMMARY_ENABLED != expected_summary_enabled:
        parser.error(
            f"{args.mode} requires CONVERSATION_SUMMARY_ENABLED={str(expected_summary_enabled).lower()}; "
            "update .env and restart ai-service before this group"
        )

    started_at = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    case_metrics: list[dict[str, Any]] = []
    cases = summary_context_cases()[:args.case_limit]
    with httpx.Client(timeout=max(1, args.timeout_seconds)) as client:
        for case in cases:
            case_id = str(case["id"])
            old_needed = max(0, args.trigger_message_count - len(case["recent_messages"]))
            old = _expand_old_prefix(case["eligible_prefix_messages"], minimum_chars=args.minimum_old_prefix_chars, minimum_messages=old_needed)
            messages = [*old, *[dict(item) for item in case["recent_messages"]]]
            if len(messages) < args.trigger_message_count:
                raise RuntimeError(f"{case_id} did not reach trigger count")

            summary = ""
            covered_count = 0
            summary_calls = 0
            summary_generation_ms = 0.0
            if args.mode == "rolling-summary":
                summary_response, elapsed = _post(
                    client,
                    args.base_url + "/conversation-summary",
                    {"previous_summary": "", "messages": messages[:-args.keep_messages], "max_chars": args.summary_max_chars},
                    _headers(run_id=args.evaluation_run_id, case_id=case_id, variant=args.mode, operation="summary-generation"),
                )
                summary = str(summary_response.get("summary") or "").strip()
                if not summary:
                    raise RuntimeError(f"{case_id} returned empty summary")
                covered_count = len(messages) - args.keep_messages
                summary_calls, summary_generation_ms = 1, elapsed

            case_rows: list[dict[str, Any]] = []
            for turn, continuation in enumerate(case["continuations"][:args.continuation_turns], start=1):
                question = str(continuation["question"])
                messages.append({"role": "user", "content": question})
                history = _rolling_history(messages, covered_count=covered_count, keep_messages=args.keep_messages) if args.mode == "rolling-summary" else [dict(item) for item in messages]
                payload = {
                    "question": question,
                    "conversation_id": f"summary-perf-{case_id}-{args.mode}-{uuid4().hex[:8]}",
                    "user_id": "eval",
                    "conversation_history": history,
                    "conversation_summary": summary,
                }
                try:
                    response, latency_ms = _post(client, args.base_url + "/run", payload, _headers(
                        run_id=args.evaluation_run_id, case_id=case_id, variant=args.mode, operation="summary-final", turn=turn))
                    error, error_detail = False, None
                except Exception as exc:  # batch must finish with a report
                    response, latency_ms, error, error_detail = {}, None, True, str(exc)
                row = {
                    "id": case_id,
                    "turn": turn,
                    "expected_route": continuation["expected_route"],
                    "actual_route": response.get("route"),
                    "route_passed": response.get("route") == continuation["expected_route"],
                    "error": error,
                    "error_detail": error_detail,
                    "latency_ms": latency_ms,
                    "history_message_count": len(history),
                    "sent_context_content_chars": _content_chars(history) + len(summary),
                    "summary_chars": len(summary),
                }
                rows.append(row)
                case_rows.append(row)
                messages.append({"role": "assistant", "content": continuation["assistant_reply"]})
            case_metrics.append({
                "id": case_id,
                "summary_calls": summary_calls,
                "summary_generation_ms": round(summary_generation_ms, 2) if summary_calls else None,
                "all_continuations_passed": all(item["route_passed"] for item in case_rows),
            })

    from langsmith import Client
    client = Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY)
    case_ids = {str(case["id"]) for case in cases}
    final_tokens = summarize_trace_token_usage(client, project_name=config.LANGSMITH_PROJECT,
        evaluation_run_id=args.evaluation_run_id, case_ids=case_ids, start_time=started_at, operation="summary-final")
    summary_tokens = summarize_trace_token_usage(client, project_name=config.LANGSMITH_PROJECT,
        evaluation_run_id=args.evaluation_run_id, case_ids=case_ids, start_time=started_at, operation="summary-generation") if args.mode == "rolling-summary" else {}
    for item in case_metrics:
        item["final_token_usage"] = final_tokens.get(item["id"], {})
        item["summary_token_usage"] = summary_tokens.get(item["id"], {})

    latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    report = {
        "schema_version": "rolling-summary-long-conversation-perf-v3",
        "mode": args.mode,
        "evaluation_run_id": args.evaluation_run_id,
        "conversation_count": len(case_metrics),
        "continuation_turns": args.continuation_turns,
        "turn_count": len(rows),
        "trigger_message_count": args.trigger_message_count,
        "keep_messages": args.keep_messages,
        "minimum_old_prefix_chars": args.minimum_old_prefix_chars,
        "route_pass_rate": round(sum(row["route_passed"] for row in rows) / len(rows), 4),
        "conversation_pass_rate": round(sum(item["all_continuations_passed"] for item in case_metrics) / len(case_metrics), 4),
        "latency_ms": {"p50": _percentile(latencies, .5), "p95": _percentile(latencies, .95)},
        "context_chars": {"sent_total": sum(row["sent_context_content_chars"] for row in rows)},
        "final_token_usage": _token_totals(case_metrics, "final_token_usage"),
        "summary_token_usage": _token_totals(case_metrics, "summary_token_usage"),
        "cases": case_metrics,
        "rows": rows,
    }
    output = args.output or Path("evals/reports") / f"{args.evaluation_run_id}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
