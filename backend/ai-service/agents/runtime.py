from __future__ import annotations
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

# 短期记忆：按 thread_id 保存整轮对话 messages
checkpointer = InMemorySaver()
# 长期记忆：跨 thread 业务记忆（商品卡、偏好）
store = InMemoryStore()

