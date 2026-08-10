from unittest.mock import MagicMock

from app.application.assistant.graph import AssistantGraph


def test_studio_export_lets_langgraph_server_manage_persistence(monkeypatch):
    captured = {}

    class FakeBuilder:
        def add_node(self, *_args, **_kwargs):
            pass

        def add_edge(self, *_args, **_kwargs):
            pass

        def add_conditional_edges(self, *_args, **_kwargs):
            pass

        def compile(self, **kwargs):
            captured.update(kwargs)
            return "compiled-graph"

    monkeypatch.setattr("app.application.assistant.graph.StateGraph", lambda *_args, **_kwargs: FakeBuilder())

    llm = MagicMock()
    llm.with_structured_output.return_value = MagicMock()
    graph = AssistantGraph(llm, use_platform_persistence=True)

    assert graph.graph == "compiled-graph"
    assert captured == {}
