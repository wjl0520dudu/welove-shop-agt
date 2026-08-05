from evals.compare_summary_context_perf import build_comparison
from evals.run_summary_context_perf import _expand_old_prefix, _rolling_history
from evals.summary_context_cases import summary_context_cases


def test_summary_cases_cover_all_context_routes():
    cases = summary_context_cases()
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    assert {turn["expected_route"] for case in cases for turn in case["continuations"]} == {
        "shopping", "knowledge", "chitchat"
    }
    assert all(len(case["recent_messages"]) == 10 for case in cases)
    assert all(len(case["continuations"]) == 3 for case in cases)


def test_comparison_keeps_summary_cost_separate_and_reports_break_even():
    full = {"mode": "full-history", "conversation_count": 20, "continuation_turns": 3, "turn_count": 60,
            "route_pass_rate": 1, "conversation_pass_rate": 1, "latency_ms": {"p50": 100, "p95": 200},
            "context_chars": {"sent_total": 8000}, "final_token_usage": {"total": 4000}}
    rolling = {"mode": "rolling-summary", "conversation_count": 20, "continuation_turns": 3, "turn_count": 60,
               "route_pass_rate": 1, "conversation_pass_rate": 1, "latency_ms": {"p50": 90, "p95": 180},
               "context_chars": {"sent_total": 3000}, "final_token_usage": {"total": 2500},
               "summary_token_usage": {"total": 1000}}
    result = build_comparison(full, rolling)
    assert result["context_chars"] == {"full_history": 8000, "rolling_summary": 3000}
    assert result["token_usage"]["final_turn_saving"] == 1500.0
    assert result["token_usage"]["end_to_end_saving"] == 500.0
    assert result["token_usage"]["break_even_future_turns"] == 0.67


def test_old_prefix_expansion_reaches_requested_size_and_message_count_without_mutating_source():
    original = [{"role": "user", "content": "原始消息"}]
    expanded = _expand_old_prefix(original, minimum_chars=8000, minimum_messages=10)
    assert len(expanded) >= 10
    assert sum(len(message["content"]) for message in expanded) >= 8000
    assert original == [{"role": "user", "content": "原始消息"}]


def test_rolling_history_keeps_unsummarized_bridge_when_window_moves():
    messages = [{"role": "user", "content": str(index)} for index in range(14)]
    history = _rolling_history(messages, covered_count=4, keep_messages=5)
    assert [message["content"] for message in history] == [str(index) for index in range(4, 14)]
