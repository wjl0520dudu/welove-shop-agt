"""Deterministic contracts for Golden Dataset Agent evaluations.

This module intentionally has no dependency on an LLM, HTTP client or external
service.  It makes execution requirements reproducible before a costly judge is
allowed to score language quality.
"""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase
from typing import Any


_TOOL_ALIASES = {
    # Golden Dataset 用面向能力的高层名字；当前 Skills runtime 会把推荐
    # 展开成候选召回 + 最终整理两个真实工具。两者都属于 recommend 能力。
    "recommend_products": {"search_product_candidates", "finalize_product_recommendation"},
    "search_products": {"recommend_products", "search_product_candidates", "finalize_product_recommendation"},
    "search_multimodal_v1": {"search_product_candidates"},
}
_ROUTE_ALIASES = {
    "orchestrator": {"complex"},
    "complex": {"orchestrator"},
}


def validate_agent_contract(case: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Validate one normalized Agent result against its Golden Dataset contract.

    ``observation`` may be either the raw Graph result or a runner record with a
    ``response`` member.  The return value is JSON serializable so it can be
    retained in reports and compared across versions.
    """
    response = observation.get("response") if isinstance(observation.get("response"), dict) else observation
    response = response or {}
    expected = case.get("expected") or {}
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    expected_routes = _as_strings(expected.get("routes") or expected.get("route"))
    actual_route = str(response.get("route") or response.get("task_type") or "unknown")
    if expected_routes:
        check(
            "route",
            any(actual_route == expected or actual_route in _ROUTE_ALIASES.get(expected, set()) for expected in expected_routes),
            f"expected={expected_routes}, actual={actual_route}",
        )

    expected_types = _as_strings(expected.get("task_types") or expected.get("task_type"))
    actual_type = str(response.get("task_type") or "unknown")
    if expected_types:
        check(
            "task_type",
            any(actual_type == expected or actual_type in _ROUTE_ALIASES.get(expected, set()) for expected in expected_types),
            f"expected={expected_types}, actual={actual_type}",
        )

    expected_error_codes = _as_strings(expected.get("error_codes"))
    if expected_error_codes:
        actual_error = str(response.get("error_code") or "")
        check("expected_error", bool(response.get("error")) and actual_error in expected_error_codes,
              f"expected={expected_error_codes}, actual={actual_error or 'none'}")
    elif expected.get("allow_error") is not True:
        check("no_unexpected_error", not bool(response.get("error")), str(response.get("error_code") or ""))

    answer = str(response.get("answer") or "").strip()
    if expected.get("require_answer", True):
        check("final_answer", bool(answer), "answer is empty" if not answer else "")

    must_answer = _as_strings(expected.get("must_answer"))
    if must_answer:
        missing = [term for term in must_answer if term.casefold() not in answer.casefold()]
        check("must_answer", not missing, f"missing={missing}" if missing else "")

    tool_calls = list(_all_tool_calls(response))
    required_tools = _as_strings(expected.get("required_tools"))
    if required_tools:
        actual_tools = [str(item.get("tool_name") or item.get("name") or "") for item in tool_calls]
        missing = [pattern for pattern in required_tools if not any(_tool_matches(pattern, name) for name in actual_tools)]
        check("required_tools", not missing, f"missing={missing}, actual={actual_tools}")

    if expected.get("validate_tool_inputs"):
        invalid = [
            str(item.get("tool_name") or item.get("name") or "unknown")
            for item in tool_calls
            if not isinstance(_tool_input(item), dict)
        ]
        check("tool_input_shape", not invalid, f"invalid={invalid}" if invalid else "")

    expected_subtask_routes = _as_strings(expected.get("subtask_routes"))
    if expected_subtask_routes:
        sub_results = [row for row in response.get("sub_results") or [] if isinstance(row, dict)]
        actual_subtask_routes = [str(row.get("route") or row.get("task_type") or "unknown") for row in sub_results]
        missing = [route for route in expected_subtask_routes if route not in actual_subtask_routes]
        check("subtask_routes", not missing, f"missing={missing}, actual={actual_subtask_routes}")
        unsuccessful = [
            route
            for route in expected_subtask_routes
            if not any(
                str(row.get("route") or row.get("task_type") or "unknown") == route
                and str(row.get("status") or "success") == "success"
                and bool(str(row.get("answer") or "").strip())
                for row in sub_results
            )
        ]
        check("subtask_success", not unsuccessful, f"unsuccessful={unsuccessful}" if unsuccessful else "")

    if expected.get("require_product_cards"):
        cards = _all_product_cards(response)
        invalid_ids = [index for index, card in enumerate(cards) if not _valid_product_id(card)]
        product_ids = [str(card.get("product_id", card.get("id"))) for card in cards if _valid_product_id(card)]
        duplicate_ids = sorted({value for value in product_ids if product_ids.count(value) > 1})
        check("product_cards", bool(cards) and not invalid_ids and not duplicate_ids,
              f"count={len(cards)}, invalid_id_indexes={invalid_ids}, duplicate_ids={duplicate_ids}")

    allowed_categories = _as_strings(expected.get("product_categories"))
    if allowed_categories:
        cards = _all_product_cards(response)
        unmatched = [card for card in cards if not _matches_category(card, allowed_categories)]
        check("product_categories", bool(cards) and not unmatched,
              f"allowed={allowed_categories}, unmatched={[_card_category_text(card) for card in unmatched]}")

    max_latency_ms = expected.get("max_latency_ms")
    if max_latency_ms is not None:
        actual_latency = observation.get("latency_ms")
        check("latency", actual_latency is not None and float(actual_latency) <= float(max_latency_ms),
              f"limit={max_latency_ms}, actual={actual_latency}")

    # ``require_sse`` is a Golden Case contract. ``sse_checked`` is set by the
    # offline evaluator's --include-stream sampling mode. Both use the same
    # strict sequence validation, so the Experiment and local report cannot
    # disagree about a streaming regression.
    if expected.get("require_sse") or observation.get("sse_checked"):
        events = [str(event).lower() for event in observation.get("sse_events") or []]
        check("sse_final_done", _valid_sse_sequence(events), f"events={events}")

    failures = [item for item in checks if not item["passed"]]
    return {
        "passed": not failures,
        "checks": checks,
        "failure_reasons": [item["name"] for item in failures],
    }


def _all_tool_calls(response: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for item in response.get("tool_calls") or []:
        if isinstance(item, dict):
            yield item
    for sub_result in response.get("sub_results") or []:
        if isinstance(sub_result, dict):
            yield from _all_tool_calls(sub_result)


def _all_product_cards(response: dict[str, Any]) -> list[dict[str, Any]]:
    cards = [card for card in response.get("product_cards") or [] if isinstance(card, dict)]
    # The orchestrator copies canonical subtask cards to the top level. Avoid
    # counting the same product twice when both representations are present.
    if cards:
        return cards
    for sub_result in response.get("sub_results") or []:
        if isinstance(sub_result, dict):
            cards.extend(_all_product_cards(sub_result))
    return cards


def _valid_product_id(card: dict[str, Any]) -> bool:
    value = card.get("product_id", card.get("id"))
    return value not in (None, "", 0)


def _tool_input(item: dict[str, Any]) -> Any:
    for key in ("input_params", "input", "args", "arguments"):
        if key in item:
            return item.get(key)
    return {}


def _matches_category(card: dict[str, Any], allowed_categories: list[str]) -> bool:
    text = _card_category_text(card).casefold()
    return any(category.casefold() in text for category in allowed_categories)


def _card_category_text(card: dict[str, Any]) -> str:
    matched_needs = card.get("_matched_needs") or []
    if isinstance(matched_needs, str):
        matched_needs = [matched_needs]
    parts = [
        card.get("category"), card.get("sub_category"), card.get("title"),
        card.get("reason"), *matched_needs,
    ]
    return " ".join(str(part) for part in parts if part)


def _as_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _tool_matches(expected_pattern: str, actual_name: str) -> bool:
    return fnmatchcase(actual_name, expected_pattern) or actual_name in _TOOL_ALIASES.get(expected_pattern, set())


def _valid_sse_sequence(events: list[str]) -> bool:
    """Validate the visible terminal SSE lifecycle without internal events.

    The assistant can emit route/tool/subtask events between these markers.
    A successful visible answer must start, produce at least one token, then
    finish and terminate in that order. Error-only streams are intentionally
    not considered successful SSE output.
    """

    try:
        start = events.index("start")
        token = events.index("token")
        final = events.index("final")
        done = events.index("done")
    except ValueError:
        return False
    return start < token < final < done
