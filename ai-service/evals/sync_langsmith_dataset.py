"""将本地 Agent Golden JSONL 幂等同步到 LangSmith Dataset。

默认 dry-run，不产生网络写入：

    python -m evals.sync_langsmith_dataset

确认环境变量配置后才执行：

    python -m evals.sync_langsmith_dataset --apply
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.infrastructure.config import config
from evals.dataset_contract import GOLDEN_DATASET_VERSION
from evals.langsmith_dataset import (
    DEFAULT_DESCRIPTION,
    build_langsmith_examples,
    dataset_fingerprint,
    sync_langsmith_dataset,
)
from evals.run_agent_eval import DEFAULT_DATASET, load_jsonl


def _preview(*, dataset_path: Path, dataset_name: str) -> dict[str, Any]:
    cases = load_jsonl(dataset_path)
    fingerprint = dataset_fingerprint(dataset_path)
    examples = build_langsmith_examples(
        cases, dataset_name=dataset_name, source_fingerprint=fingerprint,
    )
    return {
        "mode": "dry-run",
        "dataset_name": dataset_name,
        "dataset_version": GOLDEN_DATASET_VERSION,
        "dataset_path": str(dataset_path),
        "source_fingerprint": fingerprint,
        "example_count": len(examples),
        "example_ids": [str(example["id"]) for example in examples],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync WeLove Shop Golden JSONL to a LangSmith Dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--dataset-name", default=config.LANGSMITH_EVAL_DATASET)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--apply", action="store_true", help="Create/update remote Dataset; default is safe dry-run")
    args = parser.parse_args()

    preview = _preview(dataset_path=args.dataset, dataset_name=args.dataset_name)
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return
    if not config.LANGSMITH_API_KEY:
        parser.error("LANGSMITH_API_KEY is required with --apply; dry-run does not require it")

    from langsmith import Client

    cases = load_jsonl(args.dataset)
    result = sync_langsmith_dataset(
        Client(api_url=config.LANGSMITH_ENDPOINT, api_key=config.LANGSMITH_API_KEY),
        dataset_name=args.dataset_name,
        description=args.description,
        cases=cases,
        source_fingerprint=dataset_fingerprint(args.dataset),
    )
    result["mode"] = "apply"
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
