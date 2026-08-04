"""LangSmith Dataset 同步的可测试、幂等核心逻辑。

本模块只负责把本地 Golden JSONL 映射为 LangSmith Dataset Example。CLI
负责读取环境变量和实际网络调用；因此本地单元测试无需 API Key 或网络。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from evals.dataset_contract import GOLDEN_DATASET_VERSION, validate_golden_dataset


DATASET_NAMESPACE = NAMESPACE_URL
DEFAULT_DESCRIPTION = (
    "WeLove Shop Assistant 的固定 Golden Dataset。"
    "本地 JSONL 是唯一编辑源，所有同步均使用稳定 Example ID 幂等 upsert。"
)


class LangSmithDatasetClient(Protocol):
    def list_datasets(self, **kwargs: Any) -> Iterable[Any]: ...

    def create_dataset(self, dataset_name: str, **kwargs: Any) -> Any: ...

    def create_examples(self, **kwargs: Any) -> Any: ...

    def list_examples(self, **kwargs: Any) -> Iterable[Any]: ...

    def update_examples(self, **kwargs: Any) -> Any: ...


def dataset_fingerprint(dataset_path: Path) -> str:
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()[:16]


def stable_example_id(dataset_name: str, case_id: str) -> UUID:
    """Stable UUID makes repeated `create_examples` calls an upsert, not append."""

    return uuid5(DATASET_NAMESPACE, f"welove-shop/{dataset_name}/{GOLDEN_DATASET_VERSION}/{case_id}")


def build_langsmith_examples(
    cases: list[dict[str, Any]],
    *,
    dataset_name: str,
    source_fingerprint: str,
) -> list[dict[str, Any]]:
    errors = validate_golden_dataset(cases)
    if errors:
        raise ValueError("Golden Dataset contract failed:\n- " + "\n- ".join(errors))

    examples: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["id"])
        examples.append({
            "id": stable_example_id(dataset_name, case_id),
            "inputs": {
                "case_id": case_id,
                "question": case["input"],
                "request": dict(case.get("request") or {}),
                "setup": list(case.get("setup") or []),
            },
            "outputs": {"expected": dict(case["expected"])},
            "metadata": {
                "case_id": case_id,
                "scenario": str(case["scenario"]),
                "tags": list(case.get("tags") or []),
                "golden_dataset_version": GOLDEN_DATASET_VERSION,
                "source_fingerprint": source_fingerprint,
            },
            "split": "test",
        })
    return examples


def _dataset_id(dataset: Any) -> str:
    if isinstance(dataset, Mapping):
        value = dataset.get("id")
    else:
        value = getattr(dataset, "id", None)
    if not value:
        raise ValueError("LangSmith Dataset response does not contain id")
    return str(value)


def _example_id(example: Any) -> str | None:
    if isinstance(example, Mapping):
        value = example.get("id")
    else:
        value = getattr(example, "id", None)
    return str(value) if value else None


def _to_update(example: dict[str, Any]) -> dict[str, Any]:
    """Convert a create payload into the subset accepted by update_examples."""

    return {
        key: value
        for key, value in example.items()
        if key in {"id", "inputs", "outputs", "metadata", "split"}
    }


def sync_langsmith_dataset(
    client: LangSmithDatasetClient,
    *,
    dataset_name: str,
    description: str,
    cases: list[dict[str, Any]],
    source_fingerprint: str,
) -> dict[str, Any]:
    """Create the Dataset once and idempotently upsert all stable examples."""

    examples = build_langsmith_examples(
        cases, dataset_name=dataset_name, source_fingerprint=source_fingerprint,
    )
    dataset = next(iter(client.list_datasets(dataset_name=dataset_name, limit=1)), None)
    created = dataset is None
    if dataset is None:
        dataset = client.create_dataset(
            dataset_name,
            description=description,
            metadata={
                "golden_dataset_version": GOLDEN_DATASET_VERSION,
                "source_fingerprint": source_fingerprint,
                "case_count": len(examples),
                "source_of_truth": "ai-service/evals/datasets/agent_golden_cases.jsonl",
            },
        )
    remote_dataset_id = _dataset_id(dataset)
    existing_ids = {
        example_id
        for example in client.list_examples(dataset_id=remote_dataset_id)
        if (example_id := _example_id(example))
    }
    creates = [example for example in examples if str(example["id"]) not in existing_ids]
    updates = [_to_update(example) for example in examples if str(example["id"]) in existing_ids]
    create_response = client.create_examples(dataset_id=remote_dataset_id, examples=creates) if creates else {}
    update_response = client.update_examples(dataset_id=remote_dataset_id, updates=updates) if updates else {}

    def response_data(value: Any) -> dict[str, Any]:
        return dict(value or {}) if isinstance(value, Mapping) else {}

    return {
        "dataset_name": dataset_name,
        "dataset_id": remote_dataset_id,
        "dataset_created": created,
        "dataset_version": GOLDEN_DATASET_VERSION,
        "source_fingerprint": source_fingerprint,
        "example_count": len(examples),
        "created_example_count": len(creates),
        "updated_example_count": len(updates),
        "langsmith_response": {
            "create": response_data(create_response),
            "update": response_data(update_response),
        },
    }
