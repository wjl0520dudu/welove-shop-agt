"""LangGraph Studio export for inspecting the existing assistant topology.

This module is deliberately separate from ``main.py``: Studio starts its own
local LangGraph development server, while production traffic continues to use
the FastAPI/uvicorn entrypoint.
"""

from app.application.assistant.graph import AssistantGraph
from app.infrastructure.llm.llm import get_llm


# ``langgraph dev`` imports this symbol from langgraph.json.  The graph uses
# the same nodes and edge topology as the FastAPI assistant.  Studio is for
# topology / trace inspection; normal product testing still goes through the
# /api/assistant endpoints, which build the complete request state.
graph = AssistantGraph(
    get_llm(),
    use_platform_persistence=True,
).graph
