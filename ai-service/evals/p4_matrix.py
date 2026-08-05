"""P4 四 Variant 实验的配置契约与报告汇总。

P4 不在脚本中修改 .env 或重启 ai-service。每个 Variant 由操作者显式
切换、重启并调用 P3 的 ``run_langsmith_experiment``；本模块只验证报告
记录的实际运行配置，并生成可复现的横向结果。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any


P4_VARIANTS: dict[str, dict[str, Any]] = {
    "legacy": {
        "label": "Legacy（旧 Agent、无摘要）",
        "shopping_runtime": "legacy_agent",
        "knowledge_runtime": "legacy_agent",
        "rolling_summary_enabled": False,
    },
    "skills": {
        "label": "Skills（DeepAgent Skills、无摘要）",
        "shopping_runtime": "deepagent_skills",
        "knowledge_runtime": "deepagent_skills",
        "rolling_summary_enabled": False,
    },
    "summary": {
        "label": "Summary（旧 Agent、滚动摘要）",
        "shopping_runtime": "legacy_agent",
        "knowledge_runtime": "legacy_agent",
        "rolling_summary_enabled": True,
    },
    "current": {
        "label": "Current（DeepAgent Skills、滚动摘要）",
        "shopping_runtime": "deepagent_skills",
        "knowledge_runtime": "deepagent_skills",
        "rolling_summary_enabled": True,
    },
}


def expected_environment(variant: str) -> dict[str, str]:
    """Return the only three environment switches P4 is allowed to vary."""

    spec = P4_VARIANTS[variant]
    return {
        "SHOPPING_DEEP_AGENT_ENABLED": str(spec["shopping_runtime"] == "deepagent_skills").lower(),
        "KNOWLEDGE_DEEP_AGENT_ENABLED": str(spec["knowledge_runtime"] == "deepagent_skills").lower(),
        "ROUTER_ROLLING_SUMMARY_ENABLED": str(spec["rolling_summary_enabled"]).lower(),
    }


def validate_variant_report(variant: str, report: Mapping[str, Any]) -> list[str]:
    """Ensure the report was produced by the Variant it claims to represent.

    The evaluator process and the long-running ai-service are separate Python
    processes. Its local ``.env`` metadata alone cannot prove that the server
    was restarted after a switch. Therefore P4 checks both the evaluator
    configuration *and* the ``shopping_runtime`` / ``knowledge_runtime``
    values returned by the real HTTP responses.
    """

    if variant not in P4_VARIANTS:
        return [f"unknown P4 variant: {variant}"]
    expected = P4_VARIANTS[variant]
    metadata = dict(report.get("metadata") or {})
    runtime = dict(metadata.get("agent_runtime") or {})
    context = dict(metadata.get("conversation_context") or {})
    errors: list[str] = []
    if runtime.get("shopping") != expected["shopping_runtime"]:
        errors.append(
            f"shopping runtime expected {expected['shopping_runtime']!r}, got {runtime.get('shopping')!r}"
        )
    if runtime.get("knowledge") != expected["knowledge_runtime"]:
        errors.append(
            f"knowledge runtime expected {expected['knowledge_runtime']!r}, got {runtime.get('knowledge')!r}"
        )
    if context.get("rolling_summary_enabled") is not expected["rolling_summary_enabled"]:
        errors.append(
            "rolling summary expected "
            f"{expected['rolling_summary_enabled']!r}, got {context.get('rolling_summary_enabled')!r}"
        )
    errors.extend(_validate_server_runtime(report, domain="shopping", expected=expected))
    errors.extend(_validate_server_runtime(report, domain="knowledge", expected=expected))
    metrics = dict(report.get("metrics") or {})
    if int(metrics.get("case_count") or 0) != 142:
        errors.append(f"P4 full experiment must contain 142 cases, got {metrics.get('case_count')!r}")
    return errors


def _validate_server_runtime(
    report: Mapping[str, Any], *, domain: str, expected: Mapping[str, Any],
) -> list[str]:
    """Verify the runtime observed in successful server HTTP responses."""

    runtime_key = f"{domain}_runtime"
    expected_runtime = (
        "deep_agent"
        if expected[f"{domain}_runtime"] == "deepagent_skills"
        else "langchain_agent"
    )
    observed: set[str] = set()
    for case in report.get("cases") or []:
        if not isinstance(case, Mapping):
            continue
        response = case.get("response")
        if not isinstance(response, Mapping):
            continue
        value = str(response.get(runtime_key) or "").strip()
        if value:
            observed.add(value)

    if not observed:
        return [
            f"server {domain} runtime expected {expected_runtime!r}, but no "
            f"{runtime_key!r} was observed in HTTP responses"
        ]
    if observed != {expected_runtime}:
        return [
            f"server {domain} runtime expected {expected_runtime!r}, "
            f"observed {sorted(observed)!r}"
        ]
    return []


def build_matrix_summary(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Build a stable comparison object for the four completed P4 reports."""

    missing = [variant for variant in P4_VARIANTS if variant not in reports]
    if missing:
        raise ValueError(f"P4 requires all reports; missing={missing}")
    validation_errors = {
        variant: validate_variant_report(variant, report)
        for variant, report in reports.items()
    }
    invalid = {variant: errors for variant, errors in validation_errors.items() if errors}
    if invalid:
        joined = "; ".join(f"{variant}: {', '.join(errors)}" for variant, errors in invalid.items())
        raise ValueError(f"P4 report configuration mismatch: {joined}")

    rows: list[dict[str, Any]] = []
    baseline = reports["legacy"]
    baseline_metrics = dict(baseline.get("metrics") or {})
    for variant, spec in P4_VARIANTS.items():
        report = reports[variant]
        metrics = dict(report.get("metrics") or {})
        token = dict(metrics.get("token_usage") or {})
        latency = dict(metrics.get("latency_ms") or {})
        ttft = dict(metrics.get("ttft_ms") or {})
        experiment = dict((report.get("metadata") or {}).get("experiment") or {})
        rows.append({
            "variant": variant,
            "label": spec["label"],
            "experiment": experiment.get("name") or experiment.get("details", {}).get("name"),
            "git_commit": (report.get("metadata") or {}).get("git_commit"),
            "contract_pass_rate": metrics.get("contract_pass_rate"),
            "task_success_rate": metrics.get("task_success_rate"),
            "latency_p50_ms": latency.get("p50"),
            "latency_p95_ms": latency.get("p95"),
            "ttft_p95_ms": ttft.get("p95"),
            "token_total": token.get("total"),
            "token_case_count": token.get("sample_count"),
            "failure_reason_counts": metrics.get("failure_reason_counts") or {},
            "scenario_breakdown": metrics.get("scenario_breakdown") or {},
            "delta_vs_legacy": _deltas(metrics, baseline_metrics),
        })

    return {
        "schema_version": "p4-matrix-v1",
        "variants": rows,
        "baseline": "legacy",
        "shared_case_count": 142,
        "notes": [
            "All variants use the same 142-case Golden Dataset and the same external dependencies.",
            "Negative latency/token deltas are improvements; positive quality deltas are improvements.",
            "Reports are rejected when recorded runtime switches do not match the named P4 variant.",
        ],
    }


def render_matrix_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# P4：Agent Variant 对比报告", "",
        f"- 基线：`{summary.get('baseline')}`", f"- 共同 Case：{summary.get('shared_case_count')}", "",
        "## 核心指标", "",
        "| Variant | Contract | Task Success | P50 | P95 | P95 TTFT | Token 总量 |", 
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.get("variants") or []:
        lines.append(
            "| {label} | {contract} | {task} | {p50} ms | {p95} ms | {ttft} ms | {tokens} |".format(
                label=row["label"],
                contract=_percent(row.get("contract_pass_rate")),
                task=_percent(row.get("task_success_rate")),
                p50=_value(row.get("latency_p50_ms")),
                p95=_value(row.get("latency_p95_ms")),
                ttft=_value(row.get("ttft_p95_ms")),
                tokens=_value(row.get("token_total")),
            )
        )
    lines.extend(["", "## 相对 Legacy 的变化", "", "| Variant | Contract Δ | Task Success Δ | P95 Δ | P95 TTFT Δ | Token Δ |", "|---|---:|---:|---:|---:|---:|"])
    for row in summary.get("variants") or []:
        delta = row.get("delta_vs_legacy") or {}
        lines.append(
            "| {label} | {contract} | {task} | {p95} ms | {ttft} ms | {tokens} |".format(
                label=row["label"],
                contract=_signed_percent(delta.get("contract_pass_rate")),
                task=_signed_percent(delta.get("task_success_rate")),
                p95=_signed(delta.get("latency_p95_ms")),
                ttft=_signed(delta.get("ttft_p95_ms")),
                tokens=_signed(delta.get("token_total")),
            )
        )
    lines.extend(["", "## 失败归因", ""])
    for row in summary.get("variants") or []:
        counts = row.get("failure_reason_counts") or {}
        reason = "、".join(f"{key}={value}" for key, value in sorted(counts.items())) or "无"
        lines.append(f"- **{row['label']}**：{reason}")
    return "\n".join(lines) + "\n"


def _deltas(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float | int | None]:
    def diff(left: Any, right: Any) -> float | None:
        if left is None or right is None:
            return None
        try:
            return round(float(left) - float(right), 4)
        except (TypeError, ValueError):
            return None

    return {
        "contract_pass_rate": diff(current.get("contract_pass_rate"), baseline.get("contract_pass_rate")),
        "task_success_rate": diff(current.get("task_success_rate"), baseline.get("task_success_rate")),
        "latency_p95_ms": diff(
            (current.get("latency_ms") or {}).get("p95"), (baseline.get("latency_ms") or {}).get("p95"),
        ),
        "ttft_p95_ms": diff(
            (current.get("ttft_ms") or {}).get("p95"), (baseline.get("ttft_ms") or {}).get("p95"),
        ),
        "token_total": diff(
            (current.get("token_usage") or {}).get("total"), (baseline.get("token_usage") or {}).get("total"),
        ),
    }


def _percent(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def _signed_percent(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.2%}"


def _value(value: Any) -> str:
    return "-" if value is None else str(value)


def _signed(value: Any) -> str:
    return "-" if value is None else f"{float(value):+.2f}"
