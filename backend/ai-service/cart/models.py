from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


CartAction = Literal["list", "count", "add", "remove", "update", "unknown"]


class CartIntent(BaseModel):
    action: CartAction = Field(default="unknown", description="Cart operation")
    product_id: Optional[int] = Field(default=None, description="Product ID")
    sku_id: Optional[int] = Field(default=None, description="SKU ID")
    cart_item_id: Optional[int] = Field(default=None, description="Cart item ID")
    quantity: int = Field(default=1, ge=1, description="Quantity")
    need_confirm: bool = Field(default=True, description="Whether user confirmation is required")
    confirm_message: str = Field(default="", description="Confirmation message")


class CartToolResult(BaseModel):
    success: bool
    action: CartAction
    data: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error_code: Optional[str] = None
    status_code: Optional[int] = None


class CartState(TypedDict, total=False):
    question: str
    context: str
    user_id: Optional[int]
    jwt_token: Optional[str]
    run_id: str
    trace_id: str
    confirmed: bool
    intent: CartIntent
    tool_result: CartToolResult
    answer: str
    confirm_card: Optional[dict]
    cart_selection: Optional[dict]
    cart_list: Optional[dict]
    tool_calls: List[dict]
    error: bool
    error_code: Optional[str]
    message: Optional[str]
