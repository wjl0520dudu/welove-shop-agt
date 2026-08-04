from dataclasses import dataclass

from evals.langsmith_dataset import (
    build_langsmith_examples,
    stable_example_id,
    sync_langsmith_dataset,
)
from evals.run_agent_eval import build_evaluation_trace_context, _evaluation_headers
from app.infrastructure.observability.langsmith import build_assistant_run_config


def _case(case_id: str = "shop-test"):
    return {
        "id": case_id,
        "scenario": "shopping",
        "tags": ["single_turn"],
        "input": "推荐一款通勤耳机",
        "expected": {"routes": ["shopping"], "task_types": ["shopping"]},
    }


def test_langsmith_example_mapping_uses_stable_ids_and_preserves_contract_fields(monkeypatch):
    # 单条 fixture 不满足 142 条生产集总量契约；这里隔离验证映射字段。
    monkeypatch.setattr("evals.langsmith_dataset.validate_golden_dataset", lambda cases: [])
    examples = build_langsmith_examples([_case()], dataset_name="golden-v1", source_fingerprint="abc123")

    assert examples[0]["id"] == stable_example_id("golden-v1", "shop-test")
    assert examples[0]["inputs"]["question"] == "推荐一款通勤耳机"
    assert examples[0]["outputs"]["expected"]["routes"] == ["shopping"]
    assert examples[0]["metadata"] == {
        "case_id": "shop-test",
        "scenario": "shopping",
        "tags": ["single_turn"],
        "golden_dataset_version": "v1",
        "source_fingerprint": "abc123",
    }


@dataclass
class _Dataset:
    id: str = "dataset-001"


class _FakeLangSmithClient:
    def __init__(self, existing=None, existing_example_ids=None):
        self.existing = existing
        self.existing_example_ids = list(existing_example_ids or [])
        self.created_dataset = None
        self.created_examples = None
        self.updated_examples = None

    def list_examples(self, **kwargs):
        return iter([{"id": example_id} for example_id in self.existing_example_ids])

    def list_datasets(self, **kwargs):
        assert kwargs["dataset_name"] == "golden-v1"
        return iter([self.existing] if self.existing else [])

    def create_dataset(self, dataset_name, **kwargs):
        self.created_dataset = (dataset_name, kwargs)
        return _Dataset()

    def create_examples(self, **kwargs):
        self.created_examples = kwargs
        return {"count": len(kwargs["examples"]), "example_ids": [str(row["id"]) for row in kwargs["examples"]]}

    def update_examples(self, **kwargs):
        self.updated_examples = kwargs
        return {"count": len(kwargs["updates"])}


def test_sync_creates_dataset_once_and_upserts_deterministic_examples(monkeypatch):
    monkeypatch.setattr("evals.langsmith_dataset.validate_golden_dataset", lambda cases: [])
    client = _FakeLangSmithClient()
    result = sync_langsmith_dataset(
        client,
        dataset_name="golden-v1",
        description="test",
        cases=[_case()],
        source_fingerprint="fingerprint",
    )
    assert result["dataset_created"] is True
    assert client.created_dataset[0] == "golden-v1"
    first_id = client.created_examples["examples"][0]["id"]

    existing_client = _FakeLangSmithClient(existing=_Dataset(), existing_example_ids=[first_id])
    repeated = sync_langsmith_dataset(
        existing_client,
        dataset_name="golden-v1",
        description="test",
        cases=[_case()],
        source_fingerprint="fingerprint",
    )
    assert repeated["dataset_created"] is False
    assert existing_client.created_dataset is None
    assert existing_client.created_examples is None
    assert existing_client.updated_examples["updates"][0]["id"] == first_id


def test_evaluation_trace_context_is_stable_and_becomes_api_headers():
    evaluation = {"run_id": "eval-001", "dataset": "welove-shop-agent-golden-v1", "variant": "skills-summary-on"}
    context = build_evaluation_trace_context(evaluation, case_id="shop-001", operation="run")
    assert context == build_evaluation_trace_context(evaluation, case_id="shop-001", operation="run")
    headers = _evaluation_headers(context)
    assert headers["X-Trace-Id"] == context["trace_id"]
    assert headers["X-Evaluation-Run-Id"] == "eval-001"
    assert headers["X-Evaluation-Case-Id"] == "shop-001"
    assert headers["X-Evaluation-Variant"] == "skills-summary-on"

    config = build_assistant_run_config(
        conversation_id="conversation-1",
        user_id="user-1",
        trace_id=context["trace_id"],
        stream=False,
        has_image=False,
        evaluation_context={key: value for key, value in context.items() if key != "trace_id"},
    )
    assert "evaluation:golden-dataset" in config["tags"]
    assert config["metadata"]["evaluation_run_id"] == "eval-001"
    assert config["metadata"]["evaluation_case_id"] == "shop-001"
