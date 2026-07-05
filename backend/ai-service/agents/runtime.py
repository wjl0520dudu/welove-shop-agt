from __future__ import annotations
from uuid import uuid4
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

# 短期记忆：按 thread_id 保存整轮对话 messages
checkpointer = InMemorySaver()
# 长期记忆：跨 thread 业务记忆（商品卡、偏好）
store = InMemoryStore()


def thread_id_for(conversation_id: str | None, user_id: int | None = None) -> str:
    if conversation_id:
        return str(conversation_id)
    if user_id is not None:
        return f"user-{user_id}"
    return f"anonymous-{uuid4()}"


def run_config(conversation_id: str | None, user_id: int | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id_for(conversation_id, user_id)}}


# 兼容旧 cart 库的别名
agent_config = run_config
