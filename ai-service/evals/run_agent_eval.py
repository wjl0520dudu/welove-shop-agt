"""Unified offline evaluator for the Phase-4 Agent Golden Dataset.

Examples (from ``ai-service``):

    # Purely deterministic regression from recorded outputs (no model/service).
    python -m evals.run_agent_eval --recorded-results tests/fixtures/agent_eval_mock_results.jsonl

    # Execute a small Golden Dataset against a running ai-service.
    python -m evals.run_agent_eval --base-url http://127.0.0.1:8000/api/assistant

    # RAGAS needs in-process raw retrieval contexts.
    python -m evals.run_agent_eval --direct --deepeval --ragas
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.infrastructure.config import config
from evals.agent_contract import validate_agent_contract
from evals.agent_judges import (
    evaluate_with_deepeval,
    evaluate_with_ragas,
    load_judge_cache,
    save_judge_cache,
)
from evals.agent_metrics import calculate_agent_metrics, compare_reports
from evals.retrieval_metrics import summarize_retrieval_rows

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "agent_golden_cases.jsonl"
_SERVICE_ROOT = Path(__file__).parents[1]
PROMPT_FILES = (
    _SERVICE_ROOT / "app" / "prompts" / "prompts.py",
    _SERVICE_ROOT / "app" / "prompts" / "shopping.py",
    _SERVICE_ROOT / "app" / "prompts" / "knowledge_qa.py",
    _SERVICE_ROOT / "app" / "prompts" / "chitchat.py",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            item = json.loads(text)
            item.setdefault("id", f"line_{line_number}")
            item.setdefault("expected", {})
            item.setdefault("request", {})
            rows.append(item)
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate Golden Dataset IDs: {ids}")
    return rows


def load_recorded_results(path: Path) -> dict[str, dict[str, Any]]:
    rows = load_jsonl(path)
    return {str(row["id"]): row for row in rows}


def filter_cases(
    cases: list[dict[str, Any]],
    *,
    scenarios: list[str] | None = None,
    tags: list[str] | None = None,
    case_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = cases
    if scenarios:
        allowed = set(scenarios)
        selected = [case for case in selected if str(case.get("scenario")) in allowed]
    if tags:
        required = set(tags)
        selected = [case for case in selected if required.issubset(set(case.get("tags") or []))]
    if case_ids:
        allowed_ids = set(case_ids)
        selected = [case for case in selected if str(case.get("id")) in allowed_ids]
    if limit is not None:
        selected = selected[:max(0, limit)]
    return selected


def build_evaluation_trace_context(
    evaluation: dict[str, str] | None,
    *,
    case_id: str,
    operation: str,
) -> dict[str, str] | None:
    """Create stable, searchable LangSmith metadata for one evaluator request.

    The context is passed only by offline evaluation code. The production API
    treats it as observability metadata and never exposes it to Router, Agent,
    tools or the user-visible response.
    """

    if not evaluation:
        return None
    values = {
        "run_id": str(evaluation.get("run_id") or "").strip(),
        "dataset": str(evaluation.get("dataset") or "").strip(),
        "variant": str(evaluation.get("variant") or "").strip(),
        "case_id": str(case_id).strip(),
        "operation": str(operation).strip(),
    }
    if not values["run_id"]:
        return None
    trace_seed = "|".join(values[key] for key in ("run_id", "case_id", "operation"))
    values["trace_id"] = "eval-" + hashlib.sha256(trace_seed.encode("utf-8")).hexdigest()[:24]
    return values


def _evaluation_headers(trace_context: dict[str, str] | None) -> dict[str, str]:
    if not trace_context:
        return {}
    headers = {"X-Trace-Id": trace_context["trace_id"]}
    for key, header in {
        "run_id": "X-Evaluation-Run-Id",
        "case_id": "X-Evaluation-Case-Id",
        "dataset": "X-Evaluation-Dataset",
        "variant": "X-Evaluation-Variant",
        "operation": "X-Evaluation-Operation",
    }.items():
        if trace_context.get(key):
            headers[header] = trace_context[key]
    return headers


def _record_trace(record: dict[str, Any], trace_context: dict[str, str] | None, *, key: str = "langsmith_trace") -> None:
    if trace_context:
        record[key] = {
            "trace_id": trace_context["trace_id"],
            "evaluation_run_id": trace_context["run_id"],
            "evaluation_case_id": trace_context["case_id"],
            "dataset": trace_context["dataset"],
            "variant": trace_context["variant"],
            "operation": trace_context["operation"],
            "project": config.LANGSMITH_PROJECT,
        }


async def execute_http_case(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict[str, Any],
    *,
    timeout_seconds: float,
    evaluation: dict[str, str] | None = None,
    evaluation_case_id: str | None = None,
    operation: str = "run",
) -> dict[str, Any]:
    request = dict(case.get("request") or {})
    endpoint = str(request.pop("endpoint", "") or "")
    has_image = bool(request.get("image_url"))
    if not endpoint:
        endpoint = "/multimodal/run" if has_image else "/run"
    payload = {
        "question": str(case.get("input") or ""),
        "context": str(request.pop("context", "") or ""),
        "conversation_id": request.pop("conversation_id", f"golden-{case['id']}-{uuid4().hex[:8]}"),
        **request,
    }
    trace_context = build_evaluation_trace_context(
        evaluation, case_id=evaluation_case_id or str(case["id"]), operation=operation,
    )
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url.rstrip('/')}{endpoint}", json=payload,
            headers=_evaluation_headers(trace_context), timeout=timeout_seconds,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        response.raise_for_status()
        data = response.json()
        record = {"id": case["id"], "response": data, "latency_ms": latency_ms}
        _record_trace(record, trace_context)
        return record
    except (httpx.HTTPError, ValueError) as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        record = {
            "id": case["id"],
            "response": {"error": True, "error_code": "EVAL_HTTP_ERROR", "message": str(exc), "answer": ""},
            "latency_ms": latency_ms,
        }
        _record_trace(record, trace_context)
        return record


async def execute_sse_check(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict[str, Any],
    *,
    timeout_seconds: float,
    evaluation: dict[str, str] | None = None,
    evaluation_case_id: str | None = None,
    operation: str = "stream",
) -> tuple[list[str], float | None, dict[str, str] | None]:
    request = dict(case.get("request") or {})
    request.pop("endpoint", None)
    has_image = bool(request.get("image_url"))
    endpoint = "/multimodal/stream" if has_image else "/stream"
    payload = {
        "question": str(case.get("input") or ""),
        "context": str(request.pop("context", "") or ""),
        "conversation_id": request.pop("conversation_id", f"golden-stream-{case['id']}-{uuid4().hex[:8]}"),
        **request,
    }
    trace_context = build_evaluation_trace_context(
        evaluation, case_id=evaluation_case_id or str(case["id"]), operation=operation,
    )
    events: list[str] = []
    ttft_ms: float | None = None
    started = time.perf_counter()
    try:
        async with client.stream(
            "POST", f"{base_url.rstrip('/')}{endpoint}", json=payload,
            headers=_evaluation_headers(trace_context), timeout=timeout_seconds,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    events.append(event)
                    if ttft_ms is None and event in {"token", "final", "error"}:
                        ttft_ms = round((time.perf_counter() - started) * 1000, 2)
    except httpx.HTTPError:
        events.append("transport_error")
    return events, ttft_ms, trace_context


def _case_with_conversation(case: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    prepared = dict(case)
    prepared["request"] = {**(case.get("request") or {}), "conversation_id": conversation_id}
    return prepared


def _setup_cases(case: dict[str, Any], conversation_id: str) -> list[dict[str, Any]]:
    setup_cases: list[dict[str, Any]] = []
    for index, setup in enumerate(case.get("setup") or [], 1):
        if not isinstance(setup, dict):
            continue
        setup_cases.append({
            "id": f"{case['id']}-setup-{index}",
            "input": str(setup.get("input") or ""),
            "request": {
                **(case.get("request") or {}),
                **(setup.get("request") or {}),
                "conversation_id": conversation_id,
            },
        })
    return setup_cases


async def _prepare_http_conversation(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict[str, Any],
    conversation_id: str,
    timeout_seconds: float,
    evaluation: dict[str, str] | None = None,
    operation_prefix: str = "setup",
) -> dict[str, Any] | None:
    for index, setup_case in enumerate(_setup_cases(case, conversation_id), 1):
        setup_result = await execute_http_case(
            client, base_url, setup_case, timeout_seconds=timeout_seconds,
            evaluation=evaluation, evaluation_case_id=str(case["id"]),
            operation=f"{operation_prefix}-{index}",
        )
        if bool((setup_result.get("response") or {}).get("error")):
            return setup_result
    return None


async def collect_http_results(
    cases: list[dict[str, Any]], base_url: str, timeout_seconds: float,
    *, evaluation: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    total = len(cases)
    async with httpx.AsyncClient() as client:
        results: dict[str, dict[str, Any]] = {}
        for i, case in enumerate(cases, 1):
            cid = case["id"]
            scenario = case.get("scenario", "-")
            input_preview = (case.get("input") or "")[:40].replace("\n", " ")
            print(f"[http {i:3}/{total}] {cid:12} [{scenario:22}] input={input_preview!r}", file=sys.stderr, flush=True)
            run_conversation = f"golden-{case['id']}-run-{uuid4().hex[:8]}"
            setup_error = await _prepare_http_conversation(
                client, base_url, case, run_conversation, timeout_seconds,
                evaluation=evaluation,
            )
            prepared = _case_with_conversation(case, run_conversation)
            record = setup_error or await execute_http_case(
                client, base_url, prepared, timeout_seconds=timeout_seconds, evaluation=evaluation,
            )
            if setup_error:
                record["response"] = {
                    **(record.get("response") or {}),
                    "error_code": "EVAL_SETUP_FAILED",
                }
            if (case.get("expected") or {}).get("require_sse"):
                stream_conversation = f"golden-{case['id']}-stream-{uuid4().hex[:8]}"
                stream_setup_error = await _prepare_http_conversation(
                    client, base_url, case, stream_conversation, timeout_seconds,
                    evaluation=evaluation, operation_prefix="stream-setup",
                )
                if stream_setup_error:
                    record["sse_events"] = ["setup_error"]
                    record["ttft_ms"] = None
                else:
                    stream_case = _case_with_conversation(case, stream_conversation)
                    events, ttft_ms, stream_trace = await execute_sse_check(
                        client, base_url, stream_case, timeout_seconds=timeout_seconds, evaluation=evaluation,
                    )
                    record["sse_events"] = events
                    record["ttft_ms"] = ttft_ms
                    _record_trace(record, stream_trace, key="langsmith_stream_trace")
            results[str(case["id"])] = record
    return results


async def _prepare_direct_conversation(
    graph: Any,
    case: dict[str, Any],
    conversation_id: str,
    timeout_seconds: float,
    evaluation: dict[str, str] | None = None,
    operation_prefix: str = "setup",
) -> dict[str, Any] | None:
    for index, setup_case in enumerate(_setup_cases(case, conversation_id), 1):
        setup_request = dict(setup_case.get("request") or {})
        setup_request.pop("endpoint", None)
        trace_context = build_evaluation_trace_context(
            evaluation, case_id=str(case["id"]), operation=f"{operation_prefix}-{index}",
        )
        try:
            setup_result = await asyncio.wait_for(
                graph.run(
                    question=setup_case.get("input", ""),
                    trace_id=trace_context["trace_id"] if trace_context else None,
                    evaluation_context={key: value for key, value in (trace_context or {}).items() if key != "trace_id"},
                    **setup_request,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": True, "error_code": "EVAL_SETUP_FAILED", "message": str(exc), "answer": ""}
        if setup_result.get("error"):
            return {**setup_result, "error_code": "EVAL_SETUP_FAILED"}
    return None


async def collect_direct_results(
    cases: list[dict[str, Any]], timeout_seconds: float,
    *, evaluation: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Execute the Graph in-process so raw retrieval contexts remain available."""
    from app.application.assistant import AssistantGraph
    from app.infrastructure.llm.llm import get_llm

    llm = get_llm()
    if llm is None:
        return {
            str(case["id"]): {
                "id": case["id"],
                "response": {"error": True, "error_code": "LLM_NOT_CONFIGURED", "answer": ""},
            }
            for case in cases
        }
    graph = AssistantGraph(llm)
    total = len(cases)
    results: dict[str, dict[str, Any]] = {}
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        scenario = case.get("scenario", "-")
        input_preview = (case.get("input") or "")[:40].replace("\n", " ")
        print(f"[direct {i:3}/{total}] {cid:12} [{scenario:22}] input={input_preview!r}", file=sys.stderr, flush=True)
        conversation_id = f"golden-direct-{case['id']}-{uuid4().hex[:8]}"
        setup_error = await _prepare_direct_conversation(
            graph, case, conversation_id, timeout_seconds, evaluation=evaluation,
        )
        if setup_error:
            results[str(case["id"])] = {"id": case["id"], "response": setup_error}
            print(f"    -> setup_error, skip", file=sys.stderr, flush=True)
            continue

        request = dict(case.get("request") or {})
        request.pop("endpoint", None)
        request["conversation_id"] = conversation_id
        trace_context = build_evaluation_trace_context(
            evaluation, case_id=str(case["id"]), operation="run",
        )
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                graph.run(
                    question=str(case.get("input") or ""),
                    trace_id=trace_context["trace_id"] if trace_context else None,
                    evaluation_context={key: value for key, value in (trace_context or {}).items() if key != "trace_id"},
                    **request,
                ),
                timeout=timeout_seconds,
            )
            latency = round((time.perf_counter() - started) * 1000, 2)
            record: dict[str, Any] = {
                "id": case["id"],
                "response": response,
                "latency_ms": latency,
            }
            _record_trace(record, trace_context)
            route = response.get("route") or response.get("task_type") or "-"
            err = " ERROR" if response.get("error") else ""
            print(f"    -> {latency:6.0f}ms route={route}{err}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            latency = round((time.perf_counter() - started) * 1000, 2)
            record = {
                "id": case["id"],
                "response": {"error": True, "error_code": "EVAL_DIRECT_ERROR", "message": str(exc), "answer": ""},
                "latency_ms": latency,
            }
            _record_trace(record, trace_context)
            print(f"    -> {latency:6.0f}ms EXCEPTION: {str(exc)[:120]}", file=sys.stderr, flush=True)
        if (case.get("expected") or {}).get("require_sse"):
            stream_conversation = f"golden-direct-stream-{case['id']}-{uuid4().hex[:8]}"
            stream_setup_error = await _prepare_direct_conversation(
                graph, case, stream_conversation, timeout_seconds,
                evaluation=evaluation, operation_prefix="stream-setup",
            )
            if stream_setup_error:
                record["sse_events"] = ["setup_error"]
                record["ttft_ms"] = None
                results[str(case["id"])] = record
                continue
            stream_request = dict(case.get("request") or {})
            stream_request.pop("endpoint", None)
            stream_request["conversation_id"] = stream_conversation
            stream_trace = build_evaluation_trace_context(
                evaluation, case_id=str(case["id"]), operation="stream",
            )

            async def consume_stream() -> tuple[list[str], float | None]:
                events: list[str] = []
                ttft_ms: float | None = None
                stream_started = time.perf_counter()
                async for event in graph.astream(
                    question=str(case.get("input") or ""),
                    trace_id=stream_trace["trace_id"] if stream_trace else None,
                    evaluation_context={key: value for key, value in (stream_trace or {}).items() if key != "trace_id"},
                    **stream_request,
                ):
                    event_type = str(event.get("type") or "")
                    events.append(event_type)
                    if ttft_ms is None and event_type in {"token", "final", "error"}:
                        ttft_ms = round((time.perf_counter() - stream_started) * 1000, 2)
                return events, ttft_ms

            try:
                record["sse_events"], record["ttft_ms"] = await asyncio.wait_for(
                    consume_stream(), timeout=timeout_seconds,
                )
                _record_trace(record, stream_trace, key="langsmith_stream_trace")
            except Exception:  # noqa: BLE001
                record["sse_events"] = ["transport_error"]
                record["ttft_ms"] = None
        results[str(case["id"])] = record
    return results


def evaluate(
    cases: list[dict[str, Any]],
    observations: dict[str, dict[str, Any]],
    *,
    deepeval_enabled: bool = False,
    ragas_enabled: bool = False,
    judge_threshold: float = 0.6,
    judge_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = len(cases)
    do_judge = deepeval_enabled or ragas_enabled
    if do_judge:
        print(f"[evaluate] deepeval={deepeval_enabled} ragas={ragas_enabled} total={total}", file=sys.stderr, flush=True)
    for i, case in enumerate(cases, 1):
        observation = observations.get(str(case["id"])) or {
            "id": case["id"],
            "response": {"error": True, "error_code": "EVAL_RESULT_MISSING", "answer": ""},
        }
        response = observation.get("response") if isinstance(observation.get("response"), dict) else observation
        contract = validate_agent_contract(case, observation)
        row: dict[str, Any] = {
            "id": case["id"],
            "scenario": case.get("scenario", "uncategorized"),
            "tags": case.get("tags") or [],
            "input": case.get("input", ""),
            "latency_ms": observation.get("latency_ms"),
            "ttft_ms": observation.get("ttft_ms"),
            "sse_events": observation.get("sse_events") or [],
            "token_usage": observation.get("token_usage") or {"available": False},
            "langsmith_trace": observation.get("langsmith_trace"),
            "langsmith_stream_trace": observation.get("langsmith_stream_trace"),
            "response": response,
            "contract": contract,
            "judge": {"enabled": False},
            "ragas": {"enabled": False},
            "retrieval": {
                "ranked_ids": _retrieved_ids(response),
                "relevance_grades": (case.get("expected") or {}).get("retrieval_grades") or {},
            },
        }
        # Agent metrics run regardless of contract result.
        if deepeval_enabled:
            try:
                print(f"[judge {i:3}/{total}] {case['id']:12} DeepEval...", file=sys.stderr, flush=True)
                row["judge"] = evaluate_with_deepeval(
                    case, response, threshold=judge_threshold, cache=judge_cache,
                )
                detail = row["judge"].get("metrics") or {}
                tc = detail.get("task_completion", {}).get("score", "-")
                tr = detail.get("tool_correctness", {}).get("score", "-")
                ga = detail.get("goal_accuracy", {}).get("score", "-")
                print(f"    -> TC={tc} TR={tr} GA={ga}", file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001
                row["judge"] = {
                    "enabled": True, "provider": "deepeval", "passed": False,
                    "score": 0.0, "error": str(exc),
                }
                print(f"    -> ERROR: {str(exc)[:120]}", file=sys.stderr, flush=True)
        if ragas_enabled and str(response.get("task_type") or "") == "knowledge":
            try:
                print(f"[ragas {i:3}/{total}] {case['id']:12} RAGAS scoring...", file=sys.stderr, flush=True)
                row["ragas"] = evaluate_with_ragas(case, response)
                scores = row["ragas"].get("scores") or {}
                skipped = row["ragas"].get("skipped") or row["ragas"].get("skipped_metrics")
                if scores:
                    print(f"    -> F={scores.get('faithfulness', '-')} AR={scores.get('answer_relevancy', '-')} CP={scores.get('context_precision', '-')} CR={scores.get('context_recall', '-')}", file=sys.stderr, flush=True)
                elif skipped:
                    print(f"    -> skipped: {skipped}", file=sys.stderr, flush=True)
            except Exception as exc:  # noqa: BLE001
                row["ragas"] = {"enabled": False, "provider": "ragas", "error": str(exc)}
                print(f"    -> ERROR: {str(exc)[:120]}", file=sys.stderr, flush=True)
        rows.append(row)

    report = {
        "schema_version": "agent-eval-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": _build_metadata(),
        "metrics": calculate_agent_metrics(rows),
        "cases": rows,
        "failures": [row for row in rows if not row["contract"]["passed"] or row["judge"].get("passed") is False],
        "evaluation_errors": [
            {"id": row["id"],
             "judge": next((f"{k}:{v.get('error')}" for k, v in (row["judge"].get("metrics") or {}).items() if v.get("error")), None),
             "ragas": row["ragas"].get("error")}
            for row in rows
            if any(v.get("error") for v in (row["judge"].get("metrics") or {}).values()) or row["ragas"].get("error")
        ],
    }
    report["ragas_summary"] = _summarize_ragas(rows)
    report["judge_summary"] = _summarize_judge(rows)
    report["retrieval_summary"] = summarize_retrieval_rows(
        [row["retrieval"] for row in rows], k=5,
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    latency = metrics["latency_ms"]
    ttft = metrics["ttft_ms"]
    tokens = metrics.get("token_usage") or {}
    judge = report.get("judge_summary") or {}
    ragas = report.get("ragas_summary") or {}
    retrieval = report.get("retrieval_summary") or {}
    lines = [
        "# Agent 评测报告", "",
        f"- 生成时间：{report['generated_at']}",
        f"- Git Commit：{report['metadata'].get('git_commit') or 'unknown'}",
        f"- Dataset：{report['metadata'].get('dataset') or 'not recorded'}", "",
        f"- 实验：{((report['metadata'].get('experiment') or {}).get('name')) or 'not named'}",
        f"- 实验运行 ID：{((report['metadata'].get('experiment') or {}).get('run_id')) or 'not recorded'}", "",
        "## 核心指标", "",
        "| 指标 | 结果 |", "|---|---:|",
        f"| Contract Pass Rate | {metrics['contract_pass_rate']:.2%} |",
        f"| Task Success Rate / Pass@1 | {metrics['task_success_rate']:.2%} |",
        f"| P50 Latency | {latency['p50'] if latency['p50'] is not None else '-'} ms |",
        f"| P95 Latency | {latency['p95'] if latency['p95'] is not None else '-'} ms |",
        f"| P95 TTFT | {ttft['p95'] if ttft['p95'] is not None else '-'} ms |",
        f"| Token 样本数 | {tokens.get('sample_count', 0)} |",
        f"| Total Token | {tokens.get('total', 0) if tokens.get('sample_count', 0) else '-'} |",
        f"| P50 Total Token / 请求 | {tokens.get('total_p50') if tokens.get('total_p50') is not None else '-'} |",
        f"| DeepEval Pass Rate | {_display_percent(judge.get('pass_rate'))} |",
        f"| DeepEval Avg Score | {_display_num(judge.get('average_score'))} |",
        f"| RAGAS Evaluated Cases | {ragas.get('evaluated_case_count', 0)} |",
        f"| Retrieval Labeled Cases | {retrieval.get('evaluated_case_count', 0)} |",
        "", "### DeepEval 子指标", "",
        "| 指标 | 平均分 | 通过率 | 样本数 |",
        "|---|---:|---:|---:|",
    ]
    for key, mb in (judge.get("metric_breakdown") or {}).items():
        label = {"task_completion": "Task Completion", "tool_correctness": "Tool Correctness", "goal_accuracy": "Goal Accuracy"}.get(key, key)
        lines.append(f"| {label} | {_display_num(mb.get('average_score'))} | {_display_percent(mb.get('pass_rate'))} | {mb.get('sample_count', 0)} |")
    lines.extend(["", "## 失败样本", ""])
    failures = report.get("failures") or []
    if not failures:
        lines.append("无。")
    else:
        lines.extend(f"- `{row['id']}`：{', '.join(row['contract'].get('failure_reasons') or ['judge_failed'])}" for row in failures)
    return "\n".join(lines) + "\n"


def _display_percent(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def _display_num(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _build_metadata() -> dict[str, Any]:
    return {
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "llm_model": config.LLM_MODEL or None,
        "evaluation_models": {
            "deepeval": os.getenv("DEEPEVAL_MODEL") or None,
            "ragas_llm": os.getenv("RAGAS_EVAL_MODEL") or None,
            "ragas_embedding": os.getenv("RAGAS_EVAL_EMBEDDING_MODEL") or None,
        },
        "prompt_fingerprint": _combined_file_hash(PROMPT_FILES),
        "prompt_files": {str(path.relative_to(Path(__file__).parents[1])): _file_hash(path) for path in PROMPT_FILES},
        "router": {
            "rule_min_confidence": config.ROUTER_RULE_MIN_CONFIDENCE,
            "llm_low_confidence_threshold": config.ROUTER_LOW_CONFIDENCE_THRESHOLD,
        },
        "agent_runtime": {
            "shopping": "deepagent_skills" if config.SHOPPING_DEEP_AGENT_ENABLED else "legacy_agent",
            "knowledge": "deepagent_skills" if config.KNOWLEDGE_DEEP_AGENT_ENABLED else "legacy_agent",
            "shopping_llm_judge_enabled": config.SHOPPING_LLM_JUDGE_ENABLED,
        },
        "conversation_context": {
            "rolling_summary_enabled": config.ROUTER_ROLLING_SUMMARY_ENABLED,
            "summary_char_threshold": config.ROUTER_SUMMARY_CHAR_THRESHOLD,
            "recent_message_window": config.ROUTER_CONTEXT_RECENT_MESSAGE_WINDOW,
            "summary_max_chars": config.ROUTER_SUMMARY_MAX_CHARS,
        },
        "langsmith": {
            "project": config.LANGSMITH_PROJECT,
            "environment": config.LANGSMITH_ENVIRONMENT,
            "dataset": config.LANGSMITH_EVAL_DATASET,
            "tracing_enabled": config.LANGSMITH_TRACING,
        },
        "rag": {
            "embedding_model": config.DASH_SCOPE_TEXT_EMBEDDING_MODEL,
            "rerank_model": config.DASH_SCOPE_TEXT_RERANK_MODEL,
            "initial_top_k": config.RAG_INITIAL_TOP_K,
            "chunk_size": config.CHUNK_SIZE,
            "chunk_overlap": config.CHUNK_OVERLAP,
            "milvus_collection": config.MILVUS_COLLECTION,
            "parent_child_enabled": config.RAG_PARENT_CHILD_ENABLED,
            "parent_child_chunking": config.RAG_PARENT_CHILD_CHUNKING,
            "parent_child_general_only": config.RAG_PARENT_CHILD_GENERAL_ONLY,
        },
    }


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_dirty() -> bool | None:
    try:
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL,
        ).strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def _file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _combined_file_hash(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parents[1]
    for path in paths:
        try:
            stable_name = str(path.relative_to(root))
        except ValueError:
            stable_name = path.name
        digest.update(stable_name.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()[:16]


def _summarize_ragas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = {}
    skipped = 0
    skipped_metrics: dict[str, int] = {}
    for row in rows:
        ragas = row.get("ragas") or {}
        if ragas.get("skipped"):
            skipped += 1
        for metric_name in (ragas.get("skipped_metrics") or {}):
            skipped_metrics[metric_name] = skipped_metrics.get(metric_name, 0) + 1
        for key, value in (ragas.get("scores") or {}).items():
            values.setdefault(key, []).append(float(value))
    return {
        "evaluated_case_count": sum(1 for row in rows if (row.get("ragas") or {}).get("enabled")),
        "skipped_case_count": skipped,
        "skipped_metric_counts": dict(sorted(skipped_metrics.items())),
        "metric_sample_counts": {key: len(items) for key, items in sorted(values.items())},
        "metrics": {key: round(sum(items) / len(items), 4) for key, items in sorted(values.items()) if items},
    }


def _summarize_judge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [row.get("judge") or {} for row in rows if (row.get("judge") or {}).get("enabled")]
    scores = [float(item["score"]) for item in enabled if item.get("score") is not None]
    passed = sum(item.get("passed") is True for item in enabled)

    # Per-metric breakdown
    metric_keys: set[str] = set()
    for item in enabled:
        metric_keys.update((item.get("metrics") or {}).keys())
    metric_breakdown: dict[str, dict[str, Any]] = {}
    for key in sorted(metric_keys):
        metric_scores = [
            float(m["score"])
            for item in enabled
            if (m := (item.get("metrics") or {}).get(key)) and m.get("score") is not None and not m.get("error")
        ]
        metric_passed = sum(
            1 for item in enabled
            if (m := (item.get("metrics") or {}).get(key)) and m.get("passed") is True
        )
        metric_errors = sum(
            1 for item in enabled
            if (m := (item.get("metrics") or {}).get(key)) and m.get("error")
        )
        metric_breakdown[key] = {
            "average_score": round(sum(metric_scores) / len(metric_scores), 4) if metric_scores else None,
            "pass_rate": round(metric_passed / len(metric_scores), 4) if metric_scores else None,
            "sample_count": len(metric_scores),
            "error_count": metric_errors,
        }

    return {
        "evaluated_case_count": len(enabled),
        "pass_rate": round(passed / len(enabled), 4) if enabled else None,
        "average_score": round(sum(scores) / len(scores), 4) if scores else None,
        "error_case_count": sum(bool(item.get("error")) for item in enabled),
        "metric_breakdown": metric_breakdown,
    }


def _retrieved_ids(response: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in response.get("sources") or []:
        if not isinstance(source, dict):
            continue
        value = source.get("chunk_id") or source.get("doc_id") or source.get("title") or source.get("doc")
        if value not in (None, ""):
            values.append(str(value))
    if values:
        return values
    for card in response.get("product_cards") or []:
        if isinstance(card, dict):
            value = card.get("product_id") or card.get("id")
            if value not in (None, ""):
                values.append(str(value))
    return values


def main() -> None:
    # Windows Python 3.12+:
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="Run unified Agent Golden Dataset evaluation")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--recorded-results", type=Path, help="JSONL records captured from a previous run")
    source.add_argument("--base-url", help="Running ai-service API root, e.g. http://127.0.0.1:8000/api/assistant")
    source.add_argument("--direct", action="store_true", help="Run AssistantGraph in-process and retain RAG contexts")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--scenario", action="append", help="Only run this scenario; repeatable")
    parser.add_argument("--tag", action="append", help="Require this case tag; repeatable")
    parser.add_argument("--case-id", action="append", help="Only run this case ID; repeatable")
    parser.add_argument("--limit", type=int, help="Run at most N selected cases")
    parser.add_argument("--deepeval", action="store_true", help="Run one DeepEval GEval rubric after Contract pass")
    parser.add_argument("--ragas", action="store_true", help="Run RAGAS only for Knowledge rows with raw retrieved_contexts")
    parser.add_argument("--judge-threshold", type=float, default=0.6)
    parser.add_argument("--judge-cache", type=Path, default=Path("evals/reports/judge-cache.local.json"))
    parser.add_argument("--baseline", type=Path, help="Prior JSON report for regression deltas")
    parser.add_argument(
        "--evaluation-run-id",
        help="Stable identifier attached to all LangSmith traces in this execution; default is generated",
    )
    parser.add_argument(
        "--experiment-name", default="current",
        help="Human-readable variant name, e.g. skills-summary-on",
    )
    parser.add_argument(
        "--langsmith-dataset-name", default=config.LANGSMITH_EVAL_DATASET,
        help="Remote LangSmith Dataset name used as this run's source reference",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    cases = filter_cases(
        load_jsonl(args.dataset),
        scenarios=args.scenario,
        tags=args.tag,
        case_ids=args.case_id,
        limit=args.limit,
    )
    if not cases:
        parser.error("no Golden Dataset cases matched the selected filters")
    evaluation = {
        "run_id": args.evaluation_run_id or (
            f"eval-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        ),
        "dataset": str(args.langsmith_dataset_name).strip(),
        "variant": str(args.experiment_name).strip() or "current",
    }
    if args.recorded_results:
        observations = load_recorded_results(args.recorded_results)
    elif args.direct:
        # Manual event loop: asyncio.run() closes the loop after the coroutine,
        # but httpx's cleanup callbacks may still reference it, causing
        # RuntimeError('Event loop is closed').  Keeping the loop alive avoids
        # the race; the OS reclaims everything on process exit.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        observations = loop.run_until_complete(
            collect_direct_results(cases, max(1.0, args.timeout_seconds), evaluation=evaluation)
        )
    else:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        observations = loop.run_until_complete(
            collect_http_results(cases, args.base_url, max(1.0, args.timeout_seconds), evaluation=evaluation)
        )
    cache = load_judge_cache(args.judge_cache) if args.deepeval else None
    report = evaluate(cases, observations, deepeval_enabled=args.deepeval, ragas_enabled=args.ragas,
                      judge_threshold=args.judge_threshold, judge_cache=cache)
    report["metadata"]["dataset"] = str(args.dataset)
    report["metadata"]["dataset_fingerprint"] = _file_hash(args.dataset)
    report["metadata"]["experiment"] = {
        "run_id": evaluation["run_id"],
        "name": evaluation["variant"],
        "langsmith_dataset": evaluation["dataset"],
        "langsmith_project": config.LANGSMITH_PROJECT,
        "trace_lookup": {
            "metadata_keys": [
                "evaluation_run_id", "evaluation_case_id", "evaluation_dataset", "evaluation_variant",
            ],
            "note": "Use evaluation_run_id + evaluation_case_id to filter root traces in LangSmith.",
        },
    }
    report["metadata"]["execution_mode"] = (
        "recorded" if args.recorded_results else "direct" if args.direct else "http"
    )
    if args.baseline:
        report["comparison"] = compare_reports(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    if cache is not None:
        save_judge_cache(args.judge_cache, cache)

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    # Windows GBK stdout 无法输出 emoji（报告里可能含 ✅/❌）——写文件后失败不阻塞。
    try:
        print(rendered)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(rendered.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
