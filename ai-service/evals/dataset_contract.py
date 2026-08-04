"""Golden Dataset 的离线结构校验。

该校验只检查评测输入的稳定数据契约，不调用模型或外部服务。这样在
导入 LangSmith Dataset 或运行本地实验之前，可以尽早发现漏标、错误的
图片请求和不完整的多轮 Case。
"""

from __future__ import annotations

from collections import Counter
from typing import Any


GOLDEN_DATASET_VERSION = "v1"
GOLDEN_CASE_COUNT = 142
SCENARIO_COUNTS = {
    "shopping": 46,
    "knowledge": 32,
    "chitchat": 32,
    "multimodal_shopping": 20,
    "multi_agent": 12,
}
ALLOWED_SCENARIOS = frozenset(SCENARIO_COUNTS)


def validate_golden_dataset(cases: list[dict[str, Any]]) -> list[str]:
    """返回全部数据契约错误；空列表代表数据集可用于正式实验。"""
    errors: list[str] = []
    ids: set[str] = set()

    for position, case in enumerate(cases, 1):
        case_id = str(case.get("id") or "")
        prefix = f"case[{position}]({case_id or '<missing-id>'})"
        if not case_id:
            errors.append(f"{prefix}: id is required")
        elif case_id in ids:
            errors.append(f"{prefix}: duplicate id")
        ids.add(case_id)

        scenario = str(case.get("scenario") or "")
        if scenario not in ALLOWED_SCENARIOS:
            errors.append(f"{prefix}: unsupported scenario={scenario!r}")
        tags = case.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
            errors.append(f"{prefix}: tags must be a non-empty string list")
            tags = []
        if not tags:
            errors.append(f"{prefix}: at least one tag is required")

        input_text = case.get("input")
        if not isinstance(input_text, str):
            errors.append(f"{prefix}: input must be a string")
        elif not input_text.strip() and not ({"empty", "image"} & set(tags)):
            errors.append(f"{prefix}: non-empty input is required unless tagged empty or image")

        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{prefix}: expected object is required")
            expected = {}
        for field in ("routes", "task_types"):
            value = expected.get(field)
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                errors.append(f"{prefix}: expected.{field} must be a non-empty string list")

        request = case.get("request") or {}
        if not isinstance(request, dict):
            errors.append(f"{prefix}: request must be an object when supplied")
            request = {}
        if "image" in tags and not str(request.get("image_url") or "").strip():
            errors.append(f"{prefix}: image tag requires request.image_url")

        setup = case.get("setup") or []
        if not isinstance(setup, list):
            errors.append(f"{prefix}: setup must be a list when supplied")
            setup = []
        if "multi_turn" in tags and not setup:
            errors.append(f"{prefix}: multi_turn tag requires at least one setup turn")
        for turn_index, turn in enumerate(setup, 1):
            if not isinstance(turn, dict) or not isinstance(turn.get("input"), str) or not turn["input"].strip():
                errors.append(f"{prefix}: setup[{turn_index}] needs a non-empty input")

    if len(cases) != GOLDEN_CASE_COUNT:
        errors.append(
            f"dataset case count expected {GOLDEN_CASE_COUNT}, got {len(cases)}; "
            "update the manifest and review the experiment baseline intentionally"
        )

    actual_counts = Counter(str(case.get("scenario") or "") for case in cases)
    if dict(actual_counts) != SCENARIO_COUNTS:
        errors.append(
            f"scenario counts expected {SCENARIO_COUNTS}, got {dict(sorted(actual_counts.items()))}"
        )
    return errors
