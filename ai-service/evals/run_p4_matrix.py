"""Validate and merge four completed P4 Experiment reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.p4_matrix import P4_VARIANTS, build_matrix_summary, render_matrix_markdown


def _parse_report_spec(value: str) -> tuple[str, Path]:
    variant, separator, path_text = value.partition("=")
    variant = variant.strip()
    if not separator or variant not in P4_VARIANTS or not path_text.strip():
        choices = ", ".join(P4_VARIANTS)
        raise argparse.ArgumentTypeError(f"expected <variant>=<report.json>, variant in: {choices}")
    return variant, Path(path_text.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge four P4 LangSmith Experiment reports")
    parser.add_argument(
        "--report", action="append", type=_parse_report_spec, required=True,
        metavar="VARIANT=PATH", help="Repeat for legacy, skills, summary and current",
    )
    parser.add_argument("--output", type=Path, default=Path("evals/reports/p4-matrix.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("evals/reports/p4-matrix.md"))
    args = parser.parse_args()

    paths = dict(args.report)
    if len(paths) != len(args.report):
        parser.error("each P4 variant may be supplied only once")
    reports: dict[str, dict] = {}
    for variant, path in paths.items():
        if not path.is_file():
            parser.error(f"report not found for {variant}: {path}")
        try:
            reports[variant] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            parser.error(f"invalid JSON report for {variant}: {path}: {exc}")
    try:
        summary = build_matrix_summary(reports)
    except ValueError as exc:
        parser.error(str(exc))

    summary["report_paths"] = {variant: str(path) for variant, path in paths.items()}
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_matrix_markdown(summary), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
