from __future__ import annotations

import time
from typing import Any, Dict, Optional
from uuid import uuid4

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agents.memory import clear_pending_cart_action, remember_pending_cart_action
from agents.schemas import AgentRequestContext
from api.response_adapter import model_to_dict
from cart.java_client import CartJavaClient
from cart.models import CartToolResult


class ProductRefInput(BaseModel):
    product_id: Optional[int] = Field(None, description="Product ID")
    sku_id: Optional[int] = Field(None, description="SKU ID")
    cart_item_id: Optional[int] = Field(None, description="Cart item ID")
    quantity: int = Field(1, ge=1, description="Quantity")


def _tool_call(tool_name: str, input_params: Dict[str, Any], result: Dict[str, Any], started: float) -> dict:
    return {
        "tool_call_id": str(uuid4()),
        "tool_name": tool_name,
        "input_params": {key: value for key, value in input_params.items() if key != "jwt_token"},
        "output": result,
        "status": "success" if not result.get("error") else "failed",
        "duration_ms": (time.time() - started) * 1000,
        "error_message": result.get("message") if result.get("error") else None,
        "timestamp": time.time(),
    }


def _result_payload(tool_name: str, result: CartToolResult, started: float, input_params: Dict[str, Any]) -> dict:
    data = model_to_dict(result)
    payload = {
        "answer": result.message,
        "task_type": "cart",
        "error": not result.success,
        "error_code": result.error_code,
        "message": result.message,
        "tool_call": _tool_call(tool_name, input_params, data, started),
    }
    if result.action == "list" and result.success:
        payload["answer"] = "这是你当前购物车里的商品。"
        payload["cart_list"] = {"type": "cart_list", "message": "购物车列表", "items": _normalize_cart_items(result.data.get("raw") or [])}
    if result.action == "count" and result.success:
        payload["answer"] = f"购物车里共有 {result.data.get('raw') or 0} 件商品。"
    return payload


def _normalize_cart_items(raw_items: Any) -> list[dict]:
    items = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        product = item.get("product") or {}
        sku = item.get("sku") or {}
        items.append(
            {
                "product_id": item.get("productId") or item.get("product_id"),
                "title": product.get("title") or item.get("title") or "",
                "brand": product.get("brand") or item.get("brand") or "",
                "base_price": product.get("basePrice") or product.get("base_price") or item.get("base_price"),
                "image_url": product.get("imageUrl") or product.get("image_url") or item.get("image_url") or "",
                "rating": product.get("rating") or item.get("rating"),
                "quantity": item.get("quantity"),
                "sku_id": item.get("skuId") or item.get("sku_id"),
                "sku_name": sku.get("name", ""),
            }
        )
    return items


def _memory_product(context: AgentRequestContext) -> dict:
    memory = context.business_memory or {}
    return memory.get("last_focused_product") or {}


def _resolve_product_id(context: AgentRequestContext, product_id: Optional[int]) -> Optional[int]:
    if product_id:
        return product_id
    if context.product_id:
        return context.product_id
    product = _memory_product(context)
    return product.get("product_id") or product.get("id")


async def _confirm_payload(context: AgentRequestContext, action: str, product_id: Optional[int], sku_id: Optional[int], cart_item_id: Optional[int], quantity: int) -> dict:
    messages = {
        "add": f"确认把这件商品加入购物车吗？数量：{quantity}。",
        "remove": "确认从购物车移除这件商品吗？",
        "update": f"确认把这件商品数量改为 {quantity} 吗？",
    }
    pending = {"action": action, "product_id": product_id, "sku_id": sku_id, "cart_item_id": cart_item_id, "quantity": quantity}
    await remember_pending_cart_action(context.conversation_id, context.user_id, pending)
    return {
        "answer": messages.get(action, "请确认购物车操作。"),
        "task_type": "cart",
        "confirm_card": {
            "type": "confirm_card",
            "message": messages.get(action, "请确认购物车操作。"),
            "action": action,
            "product": pending,
            "buttons": [{"type": "confirm", "label": "确认"}, {"type": "cancel", "label": "取消"}],
        },
        "error": False,
    }


def build_cart_tools(client: CartJavaClient, context: AgentRequestContext):
    @tool
    async def list_cart() -> dict:
        """List the current user's cart through the Java Cart API."""
        started = time.time()
        result = await client.list_cart(context.jwt_token)
        return _result_payload("cart_list", result, started, {})

    @tool
    async def count_cart() -> dict:
        """Count the current user's cart items through the Java Cart API."""
        started = time.time()
        result = await client.count_cart(context.jwt_token)
        return _result_payload("cart_count", result, started, {})

    @tool(args_schema=ProductRefInput)
    async def prepare_add_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Prepare an add-to-cart confirmation card. Does not write cart data."""
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_sku_id = sku_id if sku_id is not None else context.sku_id
        resolved_quantity = quantity or context.quantity or 1
        if not resolved_product_id:
            return {"answer": "我还不确定要加入哪件商品，请先选择商品。", "task_type": "cart", "cart_selection": {"type": "cart_selection", "message": "请选择要加入购物车的商品。", "items": context.business_memory.get("last_product_cards", []) if context.business_memory else []}, "error": True, "error_code": "PRODUCT_NOT_SELECTED", "message": "缺少商品标识。"}
        return await _confirm_payload(context, "add", resolved_product_id, resolved_sku_id, None, resolved_quantity)

    @tool(args_schema=ProductRefInput)
    async def prepare_remove_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Prepare a remove-from-cart confirmation card. Does not write cart data."""
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_cart_item_id = cart_item_id or context.cart_item_id
        if not resolved_product_id and not resolved_cart_item_id:
            return {"answer": "我还不确定要移除哪件商品，请先选择商品。", "task_type": "cart", "cart_selection": {"type": "cart_selection", "message": "请选择要移除的商品。", "items": []}, "error": True, "error_code": "PRODUCT_NOT_SELECTED", "message": "缺少商品标识。"}
        return await _confirm_payload(context, "remove", resolved_product_id, sku_id, resolved_cart_item_id, quantity or context.quantity or 1)

    @tool(args_schema=ProductRefInput)
    async def prepare_update_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Prepare an update-cart-quantity confirmation card. Does not write cart data."""
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_quantity = quantity or context.quantity or 1
        if not resolved_product_id:
            return {"answer": "我还不确定要修改哪件商品，请先选择商品。", "task_type": "cart", "cart_selection": {"type": "cart_selection", "message": "请选择要修改的商品。", "items": []}, "error": True, "error_code": "PRODUCT_NOT_SELECTED", "message": "缺少商品标识。"}
        return await _confirm_payload(context, "update", resolved_product_id, sku_id, cart_item_id, resolved_quantity)

    @tool(args_schema=ProductRefInput)
    async def execute_add_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Execute add-to-cart after the user confirmed the operation."""
        if not context.confirmed:
            return await prepare_add_cart.ainvoke({"product_id": product_id, "sku_id": sku_id, "quantity": quantity})
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_sku_id = sku_id if sku_id is not None else context.sku_id
        if not resolved_product_id:
            pending = (context.business_memory or {}).get("pending_cart_action") or {}
            resolved_product_id = pending.get("product_id")
            resolved_sku_id = pending.get("sku_id", resolved_sku_id)
            quantity = pending.get("quantity", quantity)
        if not resolved_product_id:
            return {"answer": "缺少要加入购物车的商品。", "task_type": "cart", "error": True, "error_code": "PRODUCT_NOT_SELECTED", "message": "缺少商品标识。"}
        started = time.time()
        result = await client.add_item(context.jwt_token, resolved_product_id, resolved_sku_id)
        if result.success:
            await clear_pending_cart_action(context.conversation_id, context.user_id)
        return _result_payload("cart_add", result, started, {"product_id": resolved_product_id, "sku_id": resolved_sku_id, "quantity": quantity})

    @tool(args_schema=ProductRefInput)
    async def execute_remove_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Execute remove-from-cart after the user confirmed the operation."""
        if not context.confirmed:
            return await prepare_remove_cart.ainvoke({"product_id": product_id, "cart_item_id": cart_item_id, "quantity": quantity})
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_cart_item_id = cart_item_id or context.cart_item_id
        started = time.time()
        result = await client.remove_item(context.jwt_token, product_id=resolved_product_id, cart_item_id=resolved_cart_item_id, quantity=quantity)
        if result.success:
            await clear_pending_cart_action(context.conversation_id, context.user_id)
        return _result_payload("cart_remove", result, started, {"product_id": resolved_product_id, "cart_item_id": resolved_cart_item_id, "quantity": quantity})

    @tool(args_schema=ProductRefInput)
    async def execute_update_cart(product_id: Optional[int] = None, sku_id: Optional[int] = None, quantity: int = 1, cart_item_id: Optional[int] = None) -> dict:
        """Execute cart quantity update after the user confirmed the operation."""
        if not context.confirmed:
            return await prepare_update_cart.ainvoke({"product_id": product_id, "quantity": quantity})
        resolved_product_id = _resolve_product_id(context, product_id)
        resolved_quantity = quantity or context.quantity or 1
        if not resolved_product_id:
            return {"answer": "缺少要修改的商品。", "task_type": "cart", "error": True, "error_code": "PRODUCT_NOT_SELECTED", "message": "缺少商品标识。"}
        started = time.time()
        result = await client.update_quantity(context.jwt_token, resolved_product_id, resolved_quantity)
        if result.success:
            await clear_pending_cart_action(context.conversation_id, context.user_id)
        return _result_payload("cart_update", result, started, {"product_id": resolved_product_id, "quantity": resolved_quantity})

    return [list_cart, count_cart, prepare_add_cart, prepare_remove_cart, prepare_update_cart, execute_add_cart, execute_remove_cart, execute_update_cart]