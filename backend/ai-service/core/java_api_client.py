"""通用 Java 后端 HTTP 客户端。

Python agent 通过 HTTP 调用 Java 后端拿业务数据（收藏 / 浏览 / 订单 / 用户资料等）。
好处：
- 业务规则（下架、脱敏、权限）由 Java 单一维护，不再 Python/Java 双份实现
- 未来 Java 加字段/加校验，Python 侧无缝拿到

## 单例设计
`get_java_api_client()` 返回懒加载全局单例。httpx.AsyncClient 内部有连接池，
比每次 with 新建 client 高效。进程退出时通过 atexit 关闭。

## 错误处理
所有请求返回 JavaApiResult（success / status_code / data / error_code / message）。
调用方不用自己处理 httpx 异常，只看 result.success / result.data 即可。

## 与 cart/java_client.py 的关系
cart 模块的 CartJavaClient 仍保留（已在多处使用），本模块是它的通用化上位替代，
新增的 tools（user_tools.py 等）用这个。未来 cart 稳定后可以合并到这里。
"""

from __future__ import annotations

import atexit
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from core.config import config

logger = logging.getLogger("ai-service.java_api")


@dataclass
class JavaApiResult:
    """Java 后端接口调用结果。"""
    success: bool
    status_code: int = 0
    data: Any = None                                # Java Result.data 内容
    error_code: Optional[str] = None                # LOGIN_REQUIRED / LOGIN_EXPIRED / TOOL_TIMEOUT / JAVA_API_ERROR
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class JavaApiClient:
    """通用 Java 后端 REST 客户端。

    - base_url 与超时来自 config
    - 每次请求带 JWT（如提供）
    - 统一解析 Java 的 Result<T>: {code, message, data}
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self._base_url = (base_url or config.JAVA_API_BASE_URL).rstrip("/")
        self._timeout = timeout or config.JAVA_API_TIMEOUT_SECONDS
        # 复用 client 的连接池，比每次 with 新建高效
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        jwt_token: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> JavaApiResult:
        """通用请求。返回 JavaApiResult，不抛异常。"""
        if not path.startswith("/"):
            path = "/" + path

        headers: Dict[str, str] = {}
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        try:
            resp = await self._get_client().request(
                method.upper(),
                path,
                headers=headers or None,
                params=params,
                json=json_body,
            )
        except httpx.TimeoutException:
            return JavaApiResult(
                success=False, error_code="TOOL_TIMEOUT",
                message=f"Java 服务响应超时（{self._timeout}s）",
            )
        except httpx.HTTPError as exc:
            logger.warning("Java API HTTP error: %s %s → %s", method, path, exc)
            return JavaApiResult(
                success=False, error_code="JAVA_API_ERROR",
                message=f"Java 服务调用失败：{exc}",
            )

        if resp.status_code in (401, 403):
            return JavaApiResult(
                success=False, status_code=resp.status_code,
                error_code="LOGIN_EXPIRED",
                message="登录已过期，请重新登录。",
            )

        if not (200 <= resp.status_code < 300):
            return JavaApiResult(
                success=False, status_code=resp.status_code,
                error_code="JAVA_API_ERROR",
                message=f"Java 接口返回 HTTP {resp.status_code}",
            )

        try:
            payload = resp.json()
        except ValueError:
            return JavaApiResult(
                success=False, status_code=resp.status_code,
                error_code="JAVA_API_ERROR",
                message="Java 接口返回不是合法 JSON",
            )

        # Java Result<T>: {code:200, message:"...", data:...}
        code = payload.get("code")
        if code != 200:
            return JavaApiResult(
                success=False, status_code=resp.status_code,
                error_code="JAVA_API_ERROR",
                message=payload.get("message") or f"Java code={code}",
                raw=payload,
            )

        return JavaApiResult(
            success=True, status_code=resp.status_code,
            data=payload.get("data"),
            message=payload.get("message"),
            raw=payload,
        )

    # ---- 便捷方法 -----------------------------------------------------------
    async def get(self, path: str, jwt_token: Optional[str] = None,
                  params: Optional[Dict[str, Any]] = None) -> JavaApiResult:
        return await self.request("GET", path, jwt_token=jwt_token, params=params)

    async def post(self, path: str, jwt_token: Optional[str] = None,
                   json_body: Optional[Dict[str, Any]] = None) -> JavaApiResult:
        return await self.request("POST", path, jwt_token=jwt_token, json_body=json_body)


# ---- 单例 ------------------------------------------------------------------

_java_api_client_singleton: Optional[JavaApiClient] = None


def get_java_api_client() -> JavaApiClient:
    """懒加载全局 JavaApiClient 单例。"""
    global _java_api_client_singleton
    if _java_api_client_singleton is None:
        _java_api_client_singleton = JavaApiClient()
        atexit.register(_atexit_close)
    return _java_api_client_singleton


def _atexit_close() -> None:
    """进程退出时关闭 httpx client 释放连接池。同步包装 async close。"""
    global _java_api_client_singleton
    if _java_api_client_singleton is None:
        return
    try:
        import asyncio
        asyncio.run(_java_api_client_singleton.close())
    except Exception:  # noqa: BLE001
        # 退出阶段容忍失败
        pass
    _java_api_client_singleton = None
