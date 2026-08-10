"""Unified assistant package."""
from app.application.assistant.context_resolver import resolve_turn_context

__all__ = ["AssistantGraph", "resolve_turn_context"]


def __getattr__(name: str):
    """Avoid importing the graph while a domain Agent imports assistant state."""
    if name == "AssistantGraph":
        from app.application.assistant.graph import AssistantGraph
        return AssistantGraph
    raise AttributeError(name)
