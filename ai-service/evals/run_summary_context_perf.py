"""Evaluate full history versus a persisted rolling summary over long conversations.

The runner uses 20 controlled conversations.  Each first crosses the same
character threshold chat-service uses, then makes three *continuous* follow-up
requests in the same logical conversation.  This is intentionally different
from a one-shot "summarize then ask once" benchmark: a persisted summary is
generated once and reused by later turns, which is the production cost model.
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


def _post(client: httpx.Client, url: str, payload: dict, headers: dict) -> tuple[dict, float]:
    started = time.perf_counter()
    response = client.post(url, json=payload, headers=headers)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    return response.json(), elapsed


def _content_chars(messages: list[dict[str, Any]]) -> int:
    """Exactly match chat-service's summary scheduling metric."""

    return sum(len(str(message.get("content") or "")) for message in messages)


def _expand_prefix(messages: list[dict[str, Any]], minimum_chars: int) -> list[dict[str, Any]]:
    """Create a controlled long prefix without mutating production data.

    The expansion is offline-fixture-only.  It lets every scenario reach the
    configured production threshold without paying for 20 separately replayed
    live conversations before the actual continuation evaluation begins.
    """

    expanded = [dict(message) for message in messages]
    current = _content_chars(expanded)
    if minimum_chars <= current:
        return expanded
    filler = "已确认的历史讨论细节保持不变：当前主题、需求、限制条件与已说明事实均需在后续继续沿用。"
    needed = minimum_chars - current
    expanded.append({"role": "assistant", "content": filler * (needed // len(filler) + 1)})
    return expanded


def _rolling_history(messages: list[dict[str, Any]], *, covered_count: int, recent_window: int) -> list[dict[str, Any]]:
    """Return the complete production-visible bridge: pending prefix + newest window.

    Items that have slipped out of the newest window but are not yet folded
    into the persisted summary must remain verbatim.  Otherwise a threshold
    batching policy would silently drop them between summary updates.
    """

    recent_start = max(0, len(messages) - max(1, recent_window))
    pending_start = min(max(0, covered_count), recent_start)
    return [dict(item) for item in [*messages[pending_start:recent_start], *messages[recent_start:]]]


def _token_totals(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    available = [item.get(key) or {} for item in items if (item.get(key) or {}).get("available")]
    return {
        "sample_count": len(available),
        "input_total": sum(int(item.get("input_tokens") or 0) for item in available),
        "output_total": sum(int(item.get("output_tokens") or 0) for item in available),
        "total": sum(int(item.get("total_tokens") or 0) for item in available),
    }


def _summary_headers(*, run_id: str, case_id: str) -> dict[str, str]:
    trace = build_evaluation_trace_context(
        {"run_id": run_id, "dataset": "rolling-summary-long-conversation-v2", "variant": "rolling-summary"},
        case_id=case_id,
        operation="summary-generation",
    )
    return _evaluation_headers(trace)


def _final_headers(*, run_id: str, case_id: str, mode: str, turn: int) -> dict[str, str]:
    trace = build_evaluation_trace_context(
        {"run_id": run_id, "dataset": "rolling-summary-long-conversation-v2", "variant": mode},
        case_id=case_id,
        operation="summary-final",
    )
    # A stable case id aggregates all turns' real model usage.  The turn tag is
    # still searchable in LangSmith without turning each turn into a new case.
    headers = _evaluation_headers(trace)
    headers["X-Evaluation-Turn"] = str(turn)
    return headers


def _maybe_roll_summary(
    *,
    client: httpx.Client,
    base_url: str,
    messages: list[dict[str, Any]],
    summary: str,
    covered_count: int,
    recent_window: int,
    threshold: int,
    max_chars: int,
    headers: dict[str, str],
) -> tuple[str, int, float | None]:
    """Mirror chat-service batching after an assistant reply is persisted."""

    recent_start = max(0, len(messages) - max(1, recent_window))
    pending = messages[covered_count:recent_start]
    if _content_chars(pending) < threshold:
        return summary, covered_count, None
    response, elapsed = _post(
        client,
        base_url + "/conversation-summary",
        {"previous_summary": summary, "messages": pending, "max_chars": max_chars},
        headers,
    )
    next_summary = str(response.get("summary") or "").strip()
    if not next_summary:
        raise RuntimeError("conversation-summary returned an empty summary")
    return next_summary, recent_start, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate long-conversation full history versus rolling summary")
    parser.add_argument("--mode", choices=("full-history", "rolling-summary"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/assistant")
    parser.add_argument("--evaluation-run-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--continuation-turns", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--recent-message-window", type=int, default=config.ROUTER_CONTEXT_RECENT_MESSAGE_WINDOW)
    parser.add_argument("--minimum-prefix-chars", type=int, default=config.ROUTER_SUMMARY_CHAR_THRESHOLD)
    parser.add_argument("--summary-max-chars", type=int, default=config.ROUTER_SUMMARY_MAX_CHARS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not config.LANGSMITH_TRACING or not config.LANGSMITH_API_KEY:
        parser.error("LANGSMITH_TRACING=true and LANGSMITH_API_KEY are required")
    if args.minimum_prefix_chars < 1:
        parser.error("--minimum-prefix-chars must be positive to test summary triggering")

    cases = summary_context_cases()
    if any(len(case["continuations"]) < args.continuation_turns for case in cases):
        parser.error("fixture does not contain enough continuation turns")
    started_at = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    case_metrics: list[dict[str, Any]] = []

    with httpx.Client(timeout=max(1, args.timeout_seconds)) as client:
        for case in cases:
            case_id = str(case["id"])
            prefix = _expand_prefix(case["eligible_prefix_messages"], args.minimum_prefix_chars)
            initial_prefix_chars = _content_chars(prefix)
            if initial_prefix_chars < args.minimum_prefix_chars:
                raise RuntimeError(f"{case_id} did not reach the requested prefix threshold")
            messages = [*prefix, *[dict(item) for item in case["recent_messages"]]]
            summary = ""
            covered_count = 0
            summary_calls = 0
            summary_generation_ms = 0.0
            if args.mode == "rolling-summary":
                summary, covered_count, initial_summary_ms = _maybe_roll_summary(
                    client=client,
                    base_url=args.base_url,
                    messages=messages,
                    summary="",
                    covered_count=0,
                    recent_window=args.recent_message_window,
                    threshold=args.minimum_prefix_chars,
                    max_chars=args.summary_max_chars,
                    headers=_summary_headers(run_id=args.evaluation_run_id, case_id=case_id),
                )
                if not summary:
                    raise RuntimeError(f"{case_id} should have generated an initial summary")
                summary_calls = 1
                summary_generation_ms += float(initial_summary_ms or 0)

            case_rows: list[dict[str, Any]] = []
            for turn, continuation in enumerate(case["continuations"][:args.continuation_turns], start=1):
                question = str(continuation["question"])
                # chat-service persists the user message before it invokes
                # ai-service, so the current question is also in history.
                messages.append({"role": "user", "content": question})
                history = (
                    _rolling_history(messages, covered_count=covered_count, recent_window=args.recent_message_window)
                    if args.mode == "rolling-summary" else [dict(item) for item in messages]
                )
                pending_chars = _content_chars(messages[covered_count:max(0, len(messages) - args.recent_message_window)])
                payload = {
                    "question": question,
                    "conversation_id": f"summary-perf-{case_id}-{args.mode}-{uuid4().hex[:8]}",
                    "user_id": "eval",
                    "conversation_history": history,
                    "conversation_summary": summary,
                }
                try:
                    response, latency_ms = _post(
                        client, args.base_url + "/run", payload,
                        _final_headers(run_id=args.evaluation_run_id, case_id=case_id, mode=args.mode, turn=turn),
                    )
                    error = False
                    error_detail = None
                except Exception as exc:  # noqa: BLE001 - batch must report every case
                    response, latency_ms, error, error_detail = {"error": str(exc)}, None, True, str(exc)
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
                    "initial_eligible_prefix_content_chars": initial_prefix_chars,
                    "pending_bridge_content_chars": pending_chars,
                    "summary_chars": len(summary),
                }
                rows.append(row)
                case_rows.append(row)

                # Use a fixed visible assistant reply before the next measured
                # turn, keeping the two variants' conversation facts equal.
                messages.append({"role": "assistant", "content": continuation["assistant_reply"]})
                if args.mode == "rolling-summary":
                    try:
                        summary, covered_count, update_ms = _maybe_roll_summary(
                            client=client,
                            base_url=args.base_url,
                            messages=messages,
                            summary=summary,
                            covered_count=covered_count,
                            recent_window=args.recent_message_window,
                            threshold=args.minimum_prefix_chars,
                            max_chars=args.summary_max_chars,
                            headers=_summary_headers(run_id=args.evaluation_run_id, case_id=case_id),
                        )
                        if update_ms is not None:
                            summary_calls += 1
                            summary_generation_ms += update_ms
                    except Exception as exc:  # noqa: BLE001
                        row["summary_update_error"] = str(exc)

            case_metrics.append({
                "id": case_id,
                "initial_eligible_prefix_content_chars": initial_prefix_chars,
                "summary_calls": summary_calls,
                "summary_generation_ms": round(summary_generation_ms, 2) if summary_calls else None,
                "all_continuations_passed": all(row["route_passed"] for row in case_rows),
            })

    from langsmith import Client

    langsmith_client = Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY)
    case_ids = {str(case["id"]) for case in cases}
    final_tokens = summarize_trace_token_usage(
        langsmith_client, project_name=config.LANGSMITH_PROJECT,
        evaluation_run_id=args.evaluation_run_id, case_ids=case_ids,
        start_time=started_at, operation="summary-final",
    )
    summary_tokens = summarize_trace_token_usage(
        langsmith_client, project_name=config.LANGSMITH_PROJECT,
        evaluation_run_id=args.evaluation_run_id, case_ids=case_ids,
        start_time=started_at, operation="summary-generation",
    ) if args.mode == "rolling-summary" else {}
    for item in case_metrics:
        item["final_token_usage"] = final_tokens.get(item["id"], {})
        item["summary_token_usage"] = summary_tokens.get(item["id"], {})

    latencies = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
    report = {
        "schema_version": "rolling-summary-long-conversation-perf-v2",
        "mode": args.mode,
        "evaluation_run_id": args.evaluation_run_id,
        "conversation_count": len(cases),
        "continuation_turns": args.continuation_turns,
        "turn_count": len(rows),
        "minimum_prefix_chars": args.minimum_prefix_chars,
        "recent_message_window": args.recent_message_window,
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
