from dataclasses import dataclass
from pathlib import Path

from evals.langsmith_experiment import (
    contract_feedback,
    example_to_case,
    performance_feedback,
    summarize_trace_token_usage,
    write_token_feedback,
)
from evals.run_langsmith_experiment import build_experiment_metadata


@dataclass
class _Example:
    inputs: dict
    outputs: dict
    metadata: dict


@dataclass
class _Run:
    outputs: dict


def _example() -> _Example:
    return _Example(
        inputs={"case_id": "shop-001", "question": "推荐通勤耳机", "request": {}, "setup": []},
        outputs={
            "expected": {
                "routes": ["shopping"],
                "task_types": ["shopping"],
                "required_tools": ["recommend_products"],
                "require_product_cards": True,
                "product_categories": ["耳机"],
                "require_sse": True,
            },
        },
        metadata={"case_id": "shop-001", "scenario": "shopping", "tags": ["recommend"]},
    )


def _run() -> _Run:
    return _Run(outputs={
        "response": {
            "route": "shopping",
            "task_type": "shopping",
            "answer": "这款适合通勤。",
            "tool_calls": [{"tool_name": "search_product_candidates", "input_params": {}}],
            "product_cards": [{"product_id": 1, "title": "降噪耳机", "sub_category": "耳机"}],
        },
        "latency_ms": 123.4,
        "ttft_ms": 45.6,
        "sse_events": ["start", "token", "final", "done"],
    })


def test_example_to_case_restores_golden_contract():
    case = example_to_case(_example())
    assert case["id"] == "shop-001"
    assert case["scenario"] == "shopping"
    assert case["expected"]["routes"] == ["shopping"]


def test_contract_feedback_reuses_contract_and_emits_product_metrics():
    feedback = contract_feedback(_run(), _example())
    scores = {row["key"]: row["score"] for row in feedback["results"]}
    assert scores["contract_pass"] == 1.0
    assert scores["route_accuracy"] == 1.0
    assert scores["tool_selection_correctness"] == 1.0
    assert scores["product_card_relevance_rate"] == 1.0
    assert scores["irrelevant_product_card_rate"] == 0.0


def test_performance_feedback_keeps_raw_milliseconds():
    feedback = performance_feedback(_run(), _example())
    assert feedback == {"results": [{"key": "latency_ms", "score": 123.4}, {"key": "ttft_ms", "score": 45.6}]}


@dataclass
class _TraceRun:
    extra: dict
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class _TokenClient:
    def list_runs(self, **kwargs):
        assert kwargs["run_type"] == "llm"
        return iter([
            _TraceRun(
                extra={"metadata": {
                    "evaluation_run_id": "batch-1", "evaluation_case_id": "shop-001",
                    "evaluation_operation": "run",
                }},
                prompt_tokens=100, completion_tokens=20, total_tokens=120,
            ),
            _TraceRun(
                extra={"metadata": {
                    "evaluation_run_id": "batch-1", "evaluation_case_id": "shop-001",
                    "evaluation_operation": "stream",
                }},
                prompt_tokens=30, completion_tokens=5, total_tokens=35,
            ),
        ])


def test_trace_token_collector_uses_only_real_run_operation_llm_leaves():
    usage = summarize_trace_token_usage(
        _TokenClient(), project_name="project", evaluation_run_id="batch-1",
        case_ids={"shop-001", "shop-002"}, start_time=__import__("datetime").datetime.now(),
        max_attempts=1, retry_wait_seconds=0,
    )
    assert usage["shop-001"] == {
        "available": True, "input_tokens": 100, "output_tokens": 20,
        "total_tokens": 120, "llm_run_count": 1, "collection_attempts": 1,
    }
    assert usage["shop-002"]["available"] is False


class _FeedbackClient:
    def __init__(self):
        self.calls = []

    def create_feedback(self, **kwargs):
        self.calls.append(kwargs)


def test_trace_token_feedback_targets_experiment_run_without_project_id():
    client = _FeedbackClient()
    writes = write_token_feedback(
        client,
        experiment_session_id="experiment-session",
        target_run_ids={"shop-001": "target-run", "shop-002": "unused-run"},
        token_usage={
            "shop-001": {"available": True, "input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "llm_run_count": 1},
            "shop-002": {"available": False},
        },
    )
    assert writes == 4
    assert {call["key"] for call in client.calls} == {"input_tokens", "output_tokens", "total_tokens", "llm_run_count"}
    assert all(
        call["run_id"] == "target-run"
        and call["session_id"] == "experiment-session"
        and "project_id" not in call
        for call in client.calls
    )


def test_experiment_metadata_reuses_current_runtime_fingerprint():
    metadata = build_experiment_metadata(
        evaluation_run_id="run-001", variant="skills-summary-on", dataset_path=Path(__file__),
    )
    assert metadata["evaluation_run_id"] == "run-001"
    assert metadata["agent_runtime"]["shopping"] in {"deepagent_skills", "legacy_agent"}
