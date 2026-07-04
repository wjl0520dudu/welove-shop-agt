from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from cart.models import CartAction, CartToolResult


JAVA_API_URL = os.getenv("JAVA_API_URL", "http://localhost:8888")


class CartJavaClient:
    def __init__(self, base_url: str = JAVA_API_URL, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, jwt_token: Optional[str]) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
        return headers

    async def list_cart(self, jwt_token: Optional[str]) -> CartToolResult:
        return await self._request("list", "GET", "/api/cart/list", jwt_token)

    async def count_cart(self, jwt_token: Optional[str]) -> CartToolResult:
        return await self._request("count", "GET", "/api/cart/count", jwt_token)

    async def add_item(
        self,
        jwt_token: Optional[str],
        product_id: int,
        sku_id: Optional[int] = None,
    ) -> CartToolResult:
        params: Dict[str, Any] = {"productId": product_id}
        if sku_id is not None:
            params["skuId"] = sku_id
        return await self._request("add", "POST", "/api/cart/add", jwt_token, params=params)

    async def update_quantity(
        self,
        jwt_token: Optional[str],
        product_id: int,
        quantity: int,
    ) -> CartToolResult:
        return await self._request(
            "update",
            "PUT",
            "/api/cart/update",
            jwt_token,
            params={"productId": product_id, "quantity": quantity},
        )

    async def remove_item(
        self,
        jwt_token: Optional[str],
        product_id: Optional[int] = None,
        cart_item_id: Optional[int] = None,
        quantity: Optional[int] = None,
    ) -> CartToolResult:
        if cart_item_id is not None:
            return await self._request(
                "remove",
                "DELETE",
                "/api/cart/removeById",
                jwt_token,
                params={"cartItemId": cart_item_id},
            )

        if product_id is None:
            return CartToolResult(
                success=False,
                action="remove",
                error_code="INVALID_CART_INPUT",
                message="缺少要删除的商品。",
            )

        params: Dict[str, Any] = {"productId": product_id}
        if quantity is not None:
            params["quantity"] = quantity
        return await self._request("remove", "DELETE", "/api/cart/remove", jwt_token, params=params)

    async def _request(
        self,
        action: CartAction,
        method: str,
        path: str,
        jwt_token: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> CartToolResult:
        if not jwt_token:
            return CartToolResult(
                success=False,
                action=action,
                error_code="LOGIN_REQUIRED",
                message="请先登录后再操作购物车。",
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(jwt_token),
                    params=params,
                )
        except httpx.TimeoutException:
            return CartToolResult(
                success=False,
                action=action,
                error_code="TOOL_TIMEOUT",
                message="购物车服务响应超时。",
            )
        except httpx.HTTPError as exc:
            return CartToolResult(
                success=False,
                action=action,
                error_code="JAVA_API_ERROR",
                message=f"购物车服务调用失败：{exc}",
            )

        if response.status_code in (401, 403):
            return CartToolResult(
                success=False,
                action=action,
                status_code=response.status_code,
                error_code="LOGIN_EXPIRED",
                message="登录已过期，请重新登录。",
            )

        if response.status_code < 200 or response.status_code >= 300:
            return CartToolResult(
                success=False,
                action=action,
                status_code=response.status_code,
                error_code="JAVA_API_ERROR",
                message=f"购物车接口调用失败：HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            return CartToolResult(
                success=False,
                action=action,
                status_code=response.status_code,
                error_code="JAVA_API_ERROR",
                message="购物车接口返回了无法解析的数据。",
            )

        if payload.get("code") != 200:
            return CartToolResult(
                success=False,
                action=action,
                status_code=response.status_code,
                error_code="JAVA_API_ERROR",
                message=payload.get("message") or "购物车接口返回失败。",
                data=payload,
            )

        return CartToolResult(
            success=True,
            action=action,
            status_code=response.status_code,
            message=payload.get("message") or "操作成功。",
            data={"raw": payload.get("data")},
        )
