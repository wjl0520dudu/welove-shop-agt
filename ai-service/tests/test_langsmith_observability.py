from app.infrastructure.observability.langsmith import (
    build_assistant_run_config,
    child_run_config,
)


def test_root_run_config_has_safe_request_context():
    config = build_assistant_run_config(
        conversation_id="conversation-123",
        user_id="user-456",
        trace_id="trace-789",
        stream=True,
        has_image=True,
        environment="development",
    )

    assert config["run_name"] == "assistant.request"
    assert "transport:sse" in config["tags"]
    assert "input:image" in config["tags"]
    assert "env:development" in config["tags"]
    assert config["configurable"]["thread_id"] == "conversation-123"
    assert config["metadata"]["conversation_ref"] != "conversation-123"
    assert config["metadata"]["user_ref"] != "user-456"
    assert config["metadata"]["request_ref"] != "trace-789"


def test_child_config_preserves_parent_observability_and_isolates_thread():
    root = build_assistant_run_config(
        conversation_id="conversation-123",
        user_id=None,
        trace_id="trace-789",
        stream=False,
        has_image=False,
    )
    child = child_run_config(
        root,
        run_name="shopping-agent.tool-loop",
        tags=["agent:shopping", "runtime:deep_agent"],
        metadata={"shopping_runtime": "deep_agent"},
        thread_id="shopping-isolated-thread",
        recursion_limit=40,
    )

    assert child["run_name"] == "shopping-agent.tool-loop"
    assert "multi-agent" in child["tags"]
    assert "agent:shopping" in child["tags"]
    assert child["metadata"]["conversation_ref"] == root["metadata"]["conversation_ref"]
    assert child["metadata"]["shopping_runtime"] == "deep_agent"
    assert child["configurable"]["thread_id"] == "shopping-isolated-thread"
    assert child["recursion_limit"] == 40
