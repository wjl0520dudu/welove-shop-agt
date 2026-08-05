from evals.summary_context_cases import summary_context_cases
from evals.compare_summary_context_perf import build_comparison
from evals.run_summary_context_perf import _expand_prefix, _rolling_history


def test_summary_context_cases_are_long_conversations_and_cover_context_routes():
    cases = summary_context_cases()
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    expected_routes = {
        turn["expected_route"]
        for case in cases for turn in case["continuations"]
    }
    assert expected_routes == {"shopping", "knowledge", "chitchat"}
    assert all(len(case["recent_messages"]) == 10 for case in cases)
    assert all(len(case["continuations"]) == 3 for case in cases)
    assert all(case["eligible_prefix_messages"] for case in cases)


def test_comparison_keeps_summary_generation_cost_separate_and_reports_break_even():
    full = {"mode": "full-history", "conversation_count": 20, "continuation_turns": 3, "turn_count": 60, "route_pass_rate": 1, "conversation_pass_rate": 1, "latency_ms": {"p50": 100, "p95": 200}, "context_chars": {"sent_total": 8000}, "final_token_usage": {"total": 4000}}
    rolling = {"mode": "rolling-summary", "conversation_count": 20, "continuation_turns": 3, "turn_count": 60, "route_pass_rate": 1, "conversation_pass_rate": 1, "latency_ms": {"p50": 90, "p95": 180}, "context_chars": {"sent_total": 3000}, "final_token_usage": {"total": 2500}, "summary_token_usage": {"total": 1000}}
    result = build_comparison(full, rolling)
    assert result["context_chars"] == {"full_history": 8000, "rolling_summary": 3000}
    assert result["token_usage"]["final_turn_saving"] == 1500.0
    assert result["token_usage"]["end_to_end_saving"] == 500.0
    assert result["token_usage"]["break_even_future_turns"] == 0.67


def test_prefix_expansion_reaches_requested_threshold_without_mutating_source():
    original = [{"role": "user", "content": "原始消息"}]
    expanded = _expand_prefix(original, 8000)
    assert len(expanded) == 2
    assert sum(len(message["content"]) for message in expanded) >= 8000
    assert original == [{"role": "user", "content": "原始消息"}]


def test_rolling_history_keeps_unsummarized_bridge_when_window_moves():
    messages = [{"role": "user", "content": str(index)} for index in range(14)]
    # First four messages are already represented by the persisted summary;
    # messages 4..8 fell outside the newest five but cannot be dropped until
    # the next batched summary update.
    history = _rolling_history(messages, covered_count=4, recent_window=5)
    assert [message["content"] for message in history] == [str(index) for index in range(4, 14)]
