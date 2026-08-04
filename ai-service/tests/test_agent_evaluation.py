import json
from pathlib import Path

from evals.agent_contract import validate_agent_contract
from evals.dataset_contract import GOLDEN_CASE_COUNT, SCENARIO_COUNTS, validate_golden_dataset
from evals.agent_metrics import calculate_agent_metrics, compare_reports
from evals.run_agent_eval import DEFAULT_DATASET, evaluate, load_jsonl
from evals.retrieval_metrics import retrieval_metrics_at_k


def _case(**expected):
    return {"id": "case-1", "scenario": "multi_agent", "input": "推荐并解释", "expected": expected}


def test_contract_accepts_complete_multi_agent_result():
    case = _case(
        routes=["complex"], task_types=["complex"],
        subtask_routes=["shopping", "knowledge"], required_tools=["search_*"],
        require_product_cards=True, product_categories=["防晒"], require_sse=True,
        max_latency_ms=1000,
    )
    observation = {
        "latency_ms": 800,
        "sse_events": ["start", "final", "done"],
        "response": {
            "route": "complex", "task_type": "complex", "answer": "已完成推荐和说明。",
            "product_cards": [{"product_id": 1, "title": "清爽防晒", "sub_category": "防晒"}],
            "sub_results": [
                {"route": "shopping", "status": "success", "answer": "已推荐商品", "tool_calls": [{"tool_name": "search_products", "input_params": {}}]},
                {"route": "knowledge", "status": "success", "answer": "已说明成分", "tool_calls": [{"tool_name": "search_knowledge", "input_params": {"query": "成分"}}]},
            ],
        },
    }
    result = validate_agent_contract(case, observation)
    assert result["passed"] is True


def test_contract_reports_route_and_sse_failures():
    result = validate_agent_contract(
        _case(routes=["shopping"], require_sse=True, require_product_cards=True),
        {"response": {"route": "knowledge", "task_type": "knowledge", "answer": "有答案"}, "sse_events": ["start"]},
    )
    assert result["passed"] is False
    assert {"route", "product_cards", "sse_final_done"}.issubset(result["failure_reasons"])


def test_contract_accepts_legacy_product_search_capability_alias():
    result = validate_agent_contract(
        _case(required_tools=["search_products"]),
        {"response": {"answer": "已推荐", "tool_calls": [{"tool_name": "recommend_products"}]}},
    )
    assert result["passed"] is True


def test_metrics_treat_judge_as_task_success_gate_and_compare_baseline():
    rows = [
        {"id": "a", "scenario": "shopping", "latency_ms": 100, "ttft_ms": 20,
         "contract": {"passed": True, "failure_reasons": []}, "judge": {"enabled": False}},
        {"id": "b", "scenario": "knowledge", "latency_ms": 300, "ttft_ms": 90,
         "contract": {"passed": True, "failure_reasons": []}, "judge": {"enabled": True, "passed": False}},
    ]
    metrics = calculate_agent_metrics(rows)
    assert metrics["contract_pass_rate"] == 1.0
    assert metrics["task_success_rate"] == 0.5
    assert metrics["latency_ms"]["p95"] == 290.0
    comparison = compare_reports({"metrics": metrics, "cases": rows}, {"metrics": {"contract_pass_rate": 0.5, "task_success_rate": 1.0, "pass@1": 1.0}, "cases": []})
    assert comparison["metric_deltas"]["contract_pass_rate"] == 0.5
    assert comparison["new_failures"] == ["b"]


def test_golden_dataset_is_stratified_and_evaluate_is_dependency_free():
    cases = load_jsonl(DEFAULT_DATASET)
    assert len(cases) == GOLDEN_CASE_COUNT
    assert validate_golden_dataset(cases) == []
    scenarios = {case["scenario"] for case in cases}
    assert {"shopping", "knowledge", "multimodal_shopping", "multi_agent", "chitchat"}.issubset(scenarios)
    assert {scenario: sum(case["scenario"] == scenario for case in cases) for scenario in scenarios} == SCENARIO_COUNTS

    manifest_path = Path(DEFAULT_DATASET).with_name("agent_golden_cases.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["case_count"] == GOLDEN_CASE_COUNT
    assert manifest["scenarios"] == SCENARIO_COUNTS

    case = _case(routes=["shopping"], task_types=["shopping"])
    report = evaluate([case], {"case-1": {"id": "case-1", "latency_ms": 12, "response": {"route": "shopping", "task_type": "shopping", "answer": "可以"}}})
    assert report["metrics"]["task_success_rate"] == 1.0
    assert report["failures"] == []


def test_standard_retrieval_metrics():
    metrics = retrieval_metrics_at_k(["x", "b", "a"], {"a": 2, "b": 1}, k=3)
    assert metrics["recall@3"] == 1.0
    assert metrics["mrr@3"] == 0.5
    assert 0 < metrics["ndcg@3"] < 1
