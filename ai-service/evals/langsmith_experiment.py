"""Reusable building blocks for LangSmith Agent experiments.

This module deliberately keeps the business assertion source in
``agent_contract``.  LangSmith only receives the same deterministic outcome as
Feedback, instead of becoming a second, hand-maintained rule engine.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

from evals.agent_contract import validate_agent_contract
from evals.run_agent_eval import (
    _evaluation_headers,
    _record_trace,
    build_evaluation_trace_context,
)


def example_to_case(example: Any) -> dict[str, Any]:
    """Restore one local Golden Case shape from a LangSmith Example object."""

    inputs = _field(example, "inputs") or {}
    outputs = _field(example, "outputs") or {}
    metadata = _field(example, "metadata") or {}
    expected = outputs.get("expected") if isinstance(outputs, Mapping) else {}
    return {
        "id": str(inputs.get("case_id") or metadata.get("case_id") or "unknown"),
        "scenario": str(metadata.get("scenario") or "uncategorized"),
        "tags": list(metadata.get("tags") or []),
        "input": str(inputs.get("question") or ""),
        "request": dict(inputs.get("request") or {}),
        "setup": list(inputs.get("setup") or []),
        "expected": dict(expected or {}),
    }


def observation_from_run(run: Any) -> dict[str, Any]:
    """Read the target output from a LangSmith Run without SDK-version coupling."""

    outputs = _field(run, "outputs") or {}
    return dict(outputs) if isinstance(outputs, Mapping) else {}


def contract_feedback(run: Any, example: Any) -> dict[str, Any]:
    """Convert the deterministic Golden Contract into LangSmith Feedback rows."""

    case = example_to_case(example)
    observation = observation_from_run(run)
    contract = validate_agent_contract(case, observation)
    check_by_name = {str(check["name"]): bool(check["passed"]) for check in contract["checks"]}
    results: list[dict[str, Any]] = [{
        "key": "contract_pass",
        "score": float(contract["passed"]),
        "comment": ", ".join(contract["failure_reasons"]) or "passed",
    }]
    metric_checks = {
        "route": "route_accuracy",
        "task_type": "task_type_accuracy",
        "required_tools": "tool_selection_correctness",
        "tool_input_shape": "tool_input_shape",
        "product_cards": "product_card_validity",
        "product_categories": "product_card_relevance",
        "subtask_routes": "complex_subtask_coverage",
        "subtask_success": "complex_task_completion",
        "sse_final_done": "sse_integrity",
    }
    for check_name, metric_key in metric_checks.items():
        if check_name in check_by_name:
            results.append({"key": metric_key, "score": float(check_by_name[check_name])})

    card_scores = _product_card_relevance(case, observation)
    results.extend(card_scores)
    return {"results": results}


def performance_feedback(run: Any, example: Any) -> dict[str, Any]:
    """Write raw latency/TTFT values as experiment feedback, without pass/fail rules."""

    del example
    observation = observation_from_run(run)
    results: list[dict[str, Any]] = []
    for key in ("latency_ms", "ttft_ms"):
        value = observation.get(key)
        if value is None:
            continue
        try:
            results.append({"key": key, "score": float(value)})
        except (TypeError, ValueError):
            continue
    return {"results": results}


def summarize_trace_token_usage(
    client: Any,
    *,
    project_name: str,
    evaluation_run_id: str,
    case_ids: set[str],
    start_time: datetime,
    max_attempts: int = 4,
    retry_wait_seconds: float = 2.0,
) -> dict[str, dict[str, Any]]:
    """Collect real LLM leaf-run token usage for one offline experiment batch.

    The Experiment ``Target`` is an HTTP wrapper and has no model usage of its
    own. The real AssistantGraph trace is uploaded separately by ai-service.
    We therefore read only ``run_type=llm`` leaves labelled with this batch's
    evaluation metadata, excluding setup and stream replay calls from cost.
    """

    usage = {
        case_id: {
            "available": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_run_count": 0,
            "collection_attempts": 0,
        }
        for case_id in case_ids
    }
    remaining = set(case_ids)
    for attempt in range(1, max_attempts + 1):
        matched: dict[str, dict[str, Any]] = {
            case_id: {
                "available": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "llm_run_count": 0,
                "collection_attempts": attempt,
            }
            for case_id in case_ids
        }
        try:
            # ``limit=None`` lets the SDK page through a full batch. Passing a
            # high limit is rejected by the hosted API, while 100 can silently
            # omit later cases in a 142-case experiment.
            runs = client.list_runs(
                project_name=project_name,
                run_type="llm",
                start_time=start_time,
                limit=None,
            )
            for run in runs:
                metadata = _run_metadata(run)
                case_id = str(metadata.get("evaluation_case_id") or "")
                if (
                    case_id not in matched
                    or str(metadata.get("evaluation_run_id") or "") != evaluation_run_id
                    or str(metadata.get("evaluation_operation") or "") != "run"
                ):
                    continue
                input_tokens, output_tokens, total_tokens = _run_token_counts(run)
                # Some framework chain runs aggregate their descendants. The
                # query is already run_type=llm, so every row here is one real
                # provider model invocation and can be summed safely.
                item = matched[case_id]
                item["available"] = True
                item["input_tokens"] += input_tokens
                item["output_tokens"] += output_tokens
                item["total_tokens"] += total_tokens
                item["llm_run_count"] += 1
        except Exception as exc:  # noqa: BLE001 - observability must not fail evaluation output
            for item in matched.values():
                item["collection_error"] = str(exc)

        usage = matched
        remaining = {case_id for case_id, item in usage.items() if not item["available"]}
        if not remaining or attempt == max_attempts:
            break
        if retry_wait_seconds > 0:
            time.sleep(retry_wait_seconds)
    return usage


def write_token_feedback(
    client: Any,
    *,
    experiment_session_id: Any,
    target_run_ids: Mapping[str, Any],
    token_usage: Mapping[str, Mapping[str, Any]],
) -> int:
    """Attach aggregated real-token metrics to their LangSmith Experiment runs."""

    writes = 0
    for case_id, run_id in target_run_ids.items():
        usage = token_usage.get(case_id) or {}
        if not usage.get("available"):
            continue
        for key in ("input_tokens", "output_tokens", "total_tokens", "llm_run_count"):
            client.create_feedback(
                run_id=run_id,
                key=key,
                score=float(usage.get(key) or 0),
                session_id=experiment_session_id,
                source_info={"source": "assistant_trace_token_aggregation"},
            )
            writes += 1
    return writes


def deepeval_feedback(run: Any, example: Any, *, threshold: float) -> dict[str, Any]:
    """Optional, offline-only LLM judge. Never used by the online request path."""

    from evals.agent_judges import evaluate_with_deepeval

    case = example_to_case(example)
    observation = observation_from_run(run)
    response = observation.get("response") if isinstance(observation.get("response"), Mapping) else observation
    judged = evaluate_with_deepeval(case, dict(response or {}), threshold=threshold)
    results: list[dict[str, Any]] = []
    for metric_name, detail in (judged.get("metrics") or {}).items():
        score = detail.get("score")
        if score is None:
            continue
        results.append({
            "key": f"llm_{metric_name}",
            "score": float(score),
            "comment": str(detail.get("reason") or ""),
        })
    return {"results": results}


@dataclass
class HttpExperimentTarget:
    """Synchronous LangSmith target which invokes the real ai-service HTTP API.

    A fresh conversation is generated for each Example. Setup turns and the
    final request deliberately share it, matching ``run_agent_eval`` semantics.
    The generated evaluation batch ID is also passed to ai-service headers so
    the real AssistantGraph trace remains searchable next to the Experiment.
    """

    base_url: str
    timeout_seconds: float
    evaluation: dict[str, str]
    cases_by_id: Mapping[str, dict[str, Any]]
    include_stream: bool = False
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        case_id = str(inputs.get("case_id") or "unknown")
        case = dict(self.cases_by_id.get(case_id) or {
            "id": case_id,
            "input": str(inputs.get("question") or ""),
            "request": dict(inputs.get("request") or {}),
            "setup": list(inputs.get("setup") or []),
            "expected": {},
        })
        observation = self._execute(case)
        with self._lock:
            self.records[case_id] = observation
        return observation

    def _execute(self, case: dict[str, Any]) -> dict[str, Any]:
        conversation_id = f"langsmith-{case['id']}-{uuid4().hex[:8]}"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            setup_error = self._run_setup(client, case, conversation_id, operation_prefix="setup")
            if setup_error:
                return setup_error

            final_case = {
                **case,
                "request": {**(case.get("request") or {}), "conversation_id": conversation_id},
            }
            result = self._post_run(client, final_case, operation="run")
            if (case.get("expected") or {}).get("require_sse") or self.include_stream:
                # The streaming contract needs a clean copy of the same setup.
                # Reusing the completed sync conversation would send the final
                # question twice and turn an evaluation check into a new dialog.
                stream_conversation = f"langsmith-stream-{case['id']}-{uuid4().hex[:8]}"
                stream_error = self._run_setup(client, case, stream_conversation, operation_prefix="stream-setup")
                if stream_error:
                    result["sse_events"] = ["setup_error"]
                    result["ttft_ms"] = None
                else:
                    stream_case = {
                        **case,
                        "request": {**(case.get("request") or {}), "conversation_id": stream_conversation},
                    }
                    events, ttft_ms, stream_trace = self._stream(client, stream_case)
                    result["sse_events"] = events
                    result["ttft_ms"] = ttft_ms
                    _record_trace(result, stream_trace, key="langsmith_stream_trace")
                result["sse_checked"] = True
            return result

    def _run_setup(
        self, client: httpx.Client, case: dict[str, Any], conversation_id: str, *, operation_prefix: str,
    ) -> dict[str, Any] | None:
        for index, setup in enumerate(case.get("setup") or [], 1):
            setup_case = {
                "id": case["id"],
                "input": str((setup or {}).get("input") or ""),
                "request": {
                    **(case.get("request") or {}),
                    **((setup or {}).get("request") or {}),
                    "conversation_id": conversation_id,
                },
            }
            setup_result = self._post_run(client, setup_case, operation=f"{operation_prefix}-{index}")
            if bool((setup_result.get("response") or {}).get("error")):
                setup_result["response"] = {
                    **(setup_result.get("response") or {}),
                    "error_code": "EVAL_SETUP_FAILED",
                }
                return setup_result
        return None

    def _post_run(self, client: httpx.Client, case: dict[str, Any], *, operation: str) -> dict[str, Any]:
        request = dict(case.get("request") or {})
        endpoint = str(request.pop("endpoint", "") or "")
        if not endpoint:
            endpoint = "/multimodal/run" if request.get("image_url") else "/run"
        payload = {
            "question": str(case.get("input") or ""),
            "context": str(request.pop("context", "") or ""),
            "conversation_id": request.pop("conversation_id", f"langsmith-{case['id']}-{uuid4().hex[:8]}"),
            **request,
        }
        trace = build_evaluation_trace_context(self.evaluation, case_id=str(case["id"]), operation=operation)
        started = time.perf_counter()
        try:
            response = client.post(
                f"{self.base_url.rstrip('/')}{endpoint}", json=payload,
                headers=_evaluation_headers(trace),
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            response.raise_for_status()
            record = {"id": case["id"], "response": response.json(), "latency_ms": latency_ms}
        except (httpx.HTTPError, ValueError) as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            record = {
                "id": case["id"],
                "response": {"error": True, "error_code": "EVAL_HTTP_ERROR", "message": str(exc), "answer": ""},
                "latency_ms": latency_ms,
            }
        _record_trace(record, trace)
        return record

    def _stream(self, client: httpx.Client, case: dict[str, Any]) -> tuple[list[str], float | None, dict[str, str] | None]:
        request = dict(case.get("request") or {})
        request.pop("endpoint", None)
        endpoint = "/multimodal/stream" if request.get("image_url") else "/stream"
        payload = {
            "question": str(case.get("input") or ""),
            "context": str(request.pop("context", "") or ""),
            "conversation_id": request.pop("conversation_id", f"langsmith-stream-{case['id']}-{uuid4().hex[:8]}"),
            **request,
        }
        trace = build_evaluation_trace_context(self.evaluation, case_id=str(case["id"]), operation="stream")
        events: list[str] = []
        ttft_ms: float | None = None
        started = time.perf_counter()
        try:
            with client.stream(
                "POST", f"{self.base_url.rstrip('/')}{endpoint}", json=payload,
                headers=_evaluation_headers(trace),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                        events.append(event)
                        if ttft_ms is None and event in {"token", "final", "error"}:
                            ttft_ms = round((time.perf_counter() - started) * 1000, 2)
        except httpx.HTTPError:
            events.append("transport_error")
        return events, ttft_ms, trace


def _product_card_relevance(case: dict[str, Any], observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose card-level relevance and irrelevant-card rate when labels exist."""

    expected = case.get("expected") or {}
    categories = [str(value).casefold() for value in expected.get("product_categories") or [] if str(value).strip()]
    if not categories:
        return []
    response = observation.get("response") if isinstance(observation.get("response"), Mapping) else observation
    cards = list((response or {}).get("product_cards") or [])
    if not cards:
        return []
    matched = 0
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        raw_needs = card.get("_matched_needs") or []
        needs = [raw_needs] if isinstance(raw_needs, str) else list(raw_needs)
        text = " ".join(str(part) for part in (
            card.get("category"), card.get("sub_category"), card.get("title"), card.get("reason"), *needs,
        ) if part).casefold()
        if any(category in text for category in categories):
            matched += 1
    relevance = matched / len(cards)
    return [
        {"key": "product_card_relevance_rate", "score": relevance},
        {"key": "irrelevant_product_card_rate", "score": 1.0 - relevance},
    ]


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _run_metadata(run: Any) -> dict[str, Any]:
    extra = _field(run, "extra") or {}
    metadata = extra.get("metadata") if isinstance(extra, Mapping) else None
    return dict(metadata or {}) if isinstance(metadata, Mapping) else {}


def _run_token_counts(run: Any) -> tuple[int, int, int]:
    metadata = _run_metadata(run)
    usage = metadata.get("usage_metadata") if isinstance(metadata.get("usage_metadata"), Mapping) else {}

    def number(attribute: str, usage_key: str) -> int:
        value = _field(run, attribute)
        if value is None:
            value = usage.get(usage_key)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = number("prompt_tokens", "input_tokens")
    output_tokens = number("completion_tokens", "output_tokens")
    total_tokens = number("total_tokens", "total_tokens")
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens
