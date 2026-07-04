from __future__ import annotations

from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


checkpointer = InMemorySaver()
store = InMemoryStore()


def thread_id_for(conversation_id: str | None, user_id: int | None = None) -> str:
    if conversation_id:
        return str(conversation_id)
    if user_id is not None:
        return f"user-{user_id}"
    return f"anonymous-{uuid4()}"


def agent_config(conversation_id: str | None, user_id: int | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id_for(conversation_id, user_id)}}