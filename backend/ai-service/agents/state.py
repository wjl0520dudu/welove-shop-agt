from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict


class AssistantState(TypedDict, total=False):
    # 输入
    question: str
    context: str
    conversation_id: Optional[str]
    user_id: Optional[int]
    jwt_token: Optional[str]
    # 追踪
    run_id: str
    trace_id: str
    # 会话短期记忆（由主图 checkpointer 持久化）
    messages: List[Dict[str, Any]]          # [{"role":"user"/"assistant","content":...}]
    # 路由
    route: str                               # shopping|knowledge|chitchat|unknown
    route_reason: str
    # 业务记忆快照（router 加载，节点可读可写）
    business_memory: Dict[str, Any]
    # 节点产出
    answer: str
    task_type: str
    product_cards: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    tool_calls: List[Dict[str, Any]]
    # 错误
    error: bool
    error_code: Optional[str]
    message: Optional[str]
    # 最终输出
    result: Dict[str, Any]
    # 私有注入（运行时供节点访问；Llm/Agent 实例非可序列化，不参与业务字段）
    _llm: Any
    _shopping_agent: Any
    _knowledge_agent: Any
