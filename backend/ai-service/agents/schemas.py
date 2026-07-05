from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# 主图只产 shopping|knowledge|chitchat|unknown；cart 仅为兼容旧购物车库保留。
TaskType = Literal["shopping", "knowledge", "chitchat", "unknown", "cart"]


class IntentDecision(BaseModel):
    task_type: TaskType = Field(..., description="best route")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reason: str = Field("")


class AgentFinalResponse(BaseModel):
    answer: str = ""
    task_type: TaskType = "unknown"
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    error: bool = False
    error_code: Optional[str] = None
    message: Optional[str] = None


class AgentRequestContext(BaseModel):
    """cart 库工具上下文（不接入主图，仅购物车库使用）。"""
    question: str = ""
    context: str = ""
    conversation_id: Optional[str] = None
    user_id: Optional[int] = None
    jwt_token: Optional[str] = None
    is_admin: bool = False
    confirmed: bool = False
    cart_action: Optional[str] = None
    product_id: Optional[int] = None
    sku_id: Optional[int] = None
    cart_item_id: Optional[int] = None
    quantity: int = 1
    business_memory: Dict[str, Any] = Field(default_factory=dict)
