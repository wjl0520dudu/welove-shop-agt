"""Run the Golden Dataset as a formal LangSmith Experiment.

The command is intentionally the only P3 entry point: it invokes the real
ai-service, creates the LangSmith Experiment, uploads deterministic Feedback,
and writes a version-comparable local JSON/Markdown report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.infrastructure.config import config
from evals.agent_metrics import compare_reports
from evals.langsmith_experiment import (
    HttpExperimentTarget,
    contract_feedback,
    deepeval_feedback,
    performance_feedback,
    summarize_trace_token_usage,
    write_token_feedback,
)
from evals.run_agent_eval import (
    DEFAULT_DATASET,
    _build_metadata,
    _file_hash,
    evaluate as build_local_report,
    filter_cases,
    load_jsonl,
    render_markdown,
)


def build_experiment_metadata(*, evaluation_run_id: str, variant: str, dataset_path: Path) -> dict[str, Any]:
    """Keep version/config metadata identical to the existing local evaluator."""

    return {
        **_build_metadata(),
        "evaluation_run_id": evaluation_run_id,
        "evaluation_variant": variant,
        "dataset_path": str(dataset_path),
        "dataset_fingerprint": _file_hash(dataset_path),
        "execution_mode": "http_langsmith_experiment",
    }


def _experiment_details(result: Any) -> dict[str, Any]:
    experiment = getattr(result, "experiment", None) or getattr(result, "_experiment", None)
    return {
        "name": getattr(result, "experiment_name", None) or getattr(experiment, "name", None),
        "id": str(getattr(result, "experiment_id", None) or getattr(experiment, "id", "") or "") or None,
        "url": getattr(result, "url", None) or getattr(experiment, "url", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run WeLove Shop Golden Dataset as a LangSmith Experiment")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/assistant")
    parser.add_argument("--dataset-name", default=config.LANGSMITH_EVAL_DATASET)
    parser.add_argument("--variant", default="skills-summary-on")
    parser.add_argument("--experiment-prefix", help="Defaults to <variant>-<UTC timestamp>")
    parser.add_argument("--evaluation-run-id", help="Stable ID attached to all real AssistantGraph traces")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--max-concurrency", type=int, default=1, help="Default 1 protects local dependencies")
    parser.add_argument(
        "--include-stream", action="store_true",
        help="Replay every selected Case via SSE to record TTFT and validate start→token→final→done",
    )
    parser.add_argument("--token-trace-attempts", type=int, default=4, help="Retries while waiting for AssistantGraph token traces")
    parser.add_argument("--scenario", action="append", help="Only run this scenario; repeatable")
    parser.add_argument("--tag", action="append", help="Require this case tag; repeatable")
    parser.add_argument("--case-id", action="append", help="Only run this case ID; repeatable")
    parser.add_argument("--limit", type=int, help="Run at most N selected cases")
    parser.add_argument("--deepeval", action="store_true", help="Opt-in LLM-as-a-Judge; never runs on the online path")
    parser.add_argument("--judge-threshold", type=float, default=0.6)
    parser.add_argument("--dry-run", action="store_true", help="Validate Dataset selection only; do not call ai-service or create an Experiment")
    parser.add_argument("--baseline", type=Path, help="Prior P3 JSON report for deltas")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    if not config.LANGSMITH_API_KEY:
        parser.error("LANGSMITH_API_KEY is required to create a formal LangSmith Experiment")
    if not config.LANGSMITH_TRACING:
        parser.error("LANGSMITH_TRACING must be true so the real AssistantGraph traces are linked")
    if args.max_concurrency < 1:
        parser.error("--max-concurrency must be at least 1")

    cases = filter_cases(
        load_jsonl(args.dataset), scenarios=args.scenario, tags=args.tag,
        case_ids=args.case_id, limit=args.limit,
    )
    if not cases:
        parser.error("no Golden Dataset cases matched the selected filters")

    now = datetime.now(timezone.utc)
    variant = str(args.variant).strip() or "current"
    evaluation_run_id = args.evaluation_run_id or f"experiment-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    experiment_prefix = args.experiment_prefix or f"{variant}-{now.strftime('%Y%m%d-%H%M%S')}"
    evaluation = {
        "run_id": evaluation_run_id,
        "dataset": str(args.dataset_name).strip(),
        "variant": variant,
    }
    target = HttpExperimentTarget(
        base_url=args.base_url,
        timeout_seconds=max(1.0, args.timeout_seconds),
        evaluation=evaluation,
        cases_by_id={str(case["id"]): case for case in cases},
        include_stream=args.include_stream,
    )
    evaluators = [contract_feedback, performance_feedback]
    if args.deepeval:
        def _judge(run: Any, example: Any) -> dict[str, Any]:
            return deepeval_feedback(run, example, threshold=args.judge_threshold)
        _judge.__name__ = "deepeval_feedback"
        evaluators.append(_judge)

    from langsmith import Client, evaluate

    client = Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY)
    selected_ids = {str(case["id"]) for case in cases}
    remote_examples = [
        example
        for example in client.list_examples(dataset_name=args.dataset_name)
        if str((getattr(example, "inputs", {}) or {}).get("case_id") or "") in selected_ids
    ]
    remote_ids = {
        str((getattr(example, "inputs", {}) or {}).get("case_id") or "")
        for example in remote_examples
    }
    missing_remote_ids = sorted(selected_ids - remote_ids)
    if missing_remote_ids:
        parser.error(
            "selected local Golden cases are missing from LangSmith Dataset; run "
            f"python -m evals.sync_langsmith_dataset --apply first. missing={missing_remote_ids}"
        )
    if args.dry_run:
        print(json.dumps({
            "mode": "dry-run",
            "dataset": args.dataset_name,
            "selected_case_count": len(cases),
            "selected_case_ids": sorted(selected_ids),
            "remote_example_count": len(remote_examples),
            "evaluation_run_id": evaluation_run_id,
            "variant": variant,
        }, ensure_ascii=False, indent=2))
        return
    print(
        f"[experiment] dataset={args.dataset_name} cases={len(cases)} prefix={experiment_prefix} "
        f"run_id={evaluation_run_id} concurrency={args.max_concurrency}",
        file=sys.stderr,
        flush=True,
    )
    experiment_started_at = datetime.now(timezone.utc)
    result = evaluate(
        target,
        data=remote_examples,
        evaluators=evaluators,
        metadata=build_experiment_metadata(
            evaluation_run_id=evaluation_run_id, variant=variant, dataset_path=args.dataset,
        ),
        experiment_prefix=experiment_prefix,
        description="WeLove Shop Assistant Golden Dataset evaluation (P3)",
        max_concurrency=args.max_concurrency,
        client=client,
        blocking=True,
        upload_results=True,
        error_handling="log",
    )
    # Materialise results. This also makes any late evaluator exception visible
    # before the local report is written.
    experiment_rows = list(result)
    target_run_ids = {
        str((getattr(row.get("example"), "inputs", {}) or {}).get("case_id") or ""): row["run"].id
        for row in experiment_rows
        if isinstance(row, dict) and row.get("run") is not None and row.get("example") is not None
    }
    token_usage = summarize_trace_token_usage(
        client,
        project_name=config.LANGSMITH_PROJECT,
        evaluation_run_id=evaluation_run_id,
        case_ids={str(case["id"]) for case in cases},
        start_time=experiment_started_at,
        max_attempts=max(1, args.token_trace_attempts),
    )
    token_feedback_writes = write_token_feedback(
        client,
        experiment_session_id=result.experiment_id,
        target_run_ids=target_run_ids,
        token_usage=token_usage,
    )
    for case_id, usage in token_usage.items():
        if case_id in target.records:
            target.records[case_id]["token_usage"] = usage

    report = build_local_report(cases, target.records)
    details = _experiment_details(result)
    report["metadata"].update({
        "dataset": str(args.dataset),
        "dataset_fingerprint": _file_hash(args.dataset),
        "experiment": {
            "name": details.get("name"),
            "id": details.get("id"),
            "url": details.get("url"),
            "evaluation_run_id": evaluation_run_id,
            "variant": variant,
            "langsmith_dataset": args.dataset_name,
            "langsmith_project": config.LANGSMITH_PROJECT,
            "details": details,
            "deepeval_enabled": args.deepeval,
            "include_stream": args.include_stream,
            "token_feedback_writes": token_feedback_writes,
            "token_trace_available_case_count": sum(bool(item.get("available")) for item in token_usage.values()),
        },
    })
    if args.baseline:
        report["comparison"] = compare_reports(
            report, json.loads(args.baseline.read_text(encoding="utf-8")),
        )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    output = args.output or Path("evals/reports") / f"{experiment_prefix}.json"
    markdown = args.markdown_output or output.with_suffix(".md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(rendered)
    print(f"[experiment] local_report={output} markdown={markdown}", file=sys.stderr)


if __name__ == "__main__":
    main()
