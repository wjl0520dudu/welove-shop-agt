from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


TaskType = Literal["shopping", "cart", "knowledge", "chitchat", "unknown", "plan_execute"]


class IntentDecision(BaseModel):
    task_type: TaskType = Field(..., description="Best agent route for the user request")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Routing confidence")
    reason: str = Field("", description="Short routing reason")


class AgentFinalResponse(BaseModel):
    answer: str = Field("", description="Final user-facing answer")
    task_type: TaskType = Field("unknown", description="Final task type")
    product_cards: list[Dict[str, Any]] = Field(default_factory=list, description="Product cards")
    confirm_card: Optional[Dict[str, Any]] = Field(None, description="Confirmation card")
    cart_selection: Optional[Dict[str, Any]] = Field(None, description="Cart or product selection card")
    cart_list: Optional[Dict[str, Any]] = Field(None, description="Cart list card")
    tool_calls: list[Dict[str, Any]] = Field(default_factory=list, description="Tool call records")
    error: bool = Field(False, description="Whether the response is an error")
    error_code: Optional[str] = Field(None, description="Stable error code")
    message: Optional[str] = Field(None, description="Stable status or error message")


class AgentRequestContext(BaseModel):
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
