import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from evals.p4_matrix import (
    P4_VARIANTS,
    build_matrix_summary,
    expected_environment,
    render_matrix_markdown,
    validate_variant_report,
)
from evals.run_p4_matrix import main


def _report(variant: str, *, case_count: int = 142) -> dict:
    spec = P4_VARIANTS[variant]
    server_runtime = (
        "deep_agent" if spec["shopping_runtime"] == "deepagent_skills" else "langchain_agent"
    )
    return {
        "metadata": {
            "git_commit": "abc123",
            "agent_runtime": {
                "shopping": spec["shopping_runtime"],
                "knowledge": spec["knowledge_runtime"],
            },
            "conversation_context": {
                "rolling_summary_enabled": spec["rolling_summary_enabled"],
            },
            "experiment": {"name": f"p4-{variant}-v1"},
        },
        "metrics": {
            "case_count": case_count,
            "contract_pass_rate": 0.90,
            "task_success_rate": 0.85,
            "latency_ms": {"p50": 1000, "p95": 2500},
            "ttft_ms": {"p95": 500},
            "token_usage": {"total": 10000, "sample_count": 142},
            "failure_reason_counts": {"missing_product_cards": 2},
            "scenario_breakdown": {"shopping": {"case_count": 40}},
        },
        "cases": [
            {"response": {"shopping_runtime": server_runtime}},
            {"response": {"knowledge_runtime": server_runtime}},
        ],
    }


def test_p4_variant_environment_is_limited_to_three_runtime_switches():
    assert expected_environment("legacy") == {
        "SHOPPING_DEEP_AGENT_ENABLED": "false",
        "KNOWLEDGE_DEEP_AGENT_ENABLED": "false",
        "ROUTER_ROLLING_SUMMARY_ENABLED": "false",
    }
    assert expected_environment("current") == {
        "SHOPPING_DEEP_AGENT_ENABLED": "true",
        "KNOWLEDGE_DEEP_AGENT_ENABLED": "true",
        "ROUTER_ROLLING_SUMMARY_ENABLED": "true",
    }


def test_p4_report_validation_rejects_runtime_or_case_count_mismatch():
    report = _report("skills")
    assert validate_variant_report("skills", report) == []

    report["metadata"]["agent_runtime"]["shopping"] = "legacy_agent"
    report["metrics"]["case_count"] = 141
    errors = validate_variant_report("skills", report)
    assert any("shopping runtime expected" in item for item in errors)
    assert any("142 cases" in item for item in errors)


def test_p4_report_validation_checks_runtime_returned_by_ai_service():
    report = _report("skills")
    report["cases"][0]["response"]["shopping_runtime"] = "langchain_agent"

    errors = validate_variant_report("skills", report)

    assert any("server shopping runtime expected 'deep_agent'" in item for item in errors)


def test_p4_matrix_calculates_deltas_and_renders_markdown():
    reports = {variant: _report(variant) for variant in P4_VARIANTS}
    reports["current"]["metrics"]["contract_pass_rate"] = 0.95
    reports["current"]["metrics"]["latency_ms"]["p95"] = 2000
    reports["current"]["metrics"]["token_usage"]["total"] = 8000

    summary = build_matrix_summary(reports)
    current = next(row for row in summary["variants"] if row["variant"] == "current")
    assert current["delta_vs_legacy"] == {
        "contract_pass_rate": 0.05,
        "task_success_rate": 0.0,
        "latency_p95_ms": -500.0,
        "ttft_p95_ms": 0.0,
        "token_total": -2000.0,
    }
    markdown = render_matrix_markdown(summary)
    assert "# P4：Agent Variant 对比报告" in markdown
    assert "Current（DeepAgent Skills、滚动摘要）" in markdown
    assert "-500.00 ms" in markdown


def test_p4_matrix_requires_all_four_valid_reports():
    reports = {variant: _report(variant) for variant in P4_VARIANTS if variant != "summary"}
    with pytest.raises(ValueError, match="missing=.*summary"):
        build_matrix_summary(reports)


def test_p4_matrix_cli_writes_json_and_markdown(monkeypatch):
    # The shared Windows runner may deny the global user Temp directory. Keep
    # this CLI fixture inside the writable repository test directory instead.
    with TemporaryDirectory(prefix="p4-matrix-", dir=Path(__file__).parent) as temp_dir:
        temp_path = Path(temp_dir)
        arguments = []
        for variant in P4_VARIANTS:
            path = temp_path / f"{variant}.json"
            path.write_text(json.dumps(_report(variant)), encoding="utf-8")
            arguments.extend(["--report", f"{variant}={path}"])
        output = temp_path / "matrix.json"
        markdown = temp_path / "matrix.md"
        monkeypatch.setattr(
            "sys.argv",
            ["run_p4_matrix", *arguments, "--output", str(output), "--markdown-output", str(markdown)],
        )

        main()

        assert json.loads(output.read_text(encoding="utf-8"))["shared_case_count"] == 142
        assert "核心指标" in markdown.read_text(encoding="utf-8")
