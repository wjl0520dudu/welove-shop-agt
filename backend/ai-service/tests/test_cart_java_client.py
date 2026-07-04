import asyncio

import httpx

from cart.java_client import CartJavaClient


class FakeAsyncClient:
    calls = []
    response = None
    exc = None

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, method, url, headers=None, params=None):
        self.__class__.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "params": params or {}}
        )
        if self.__class__.exc:
            raise self.__class__.exc
        return self.__class__.response


def reset_fake(response=None, exc=None):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response = response
    FakeAsyncClient.exc = exc


def test_missing_jwt_returns_login_required_without_http(monkeypatch):
    async def run():
        reset_fake(httpx.Response(200, json={"code": 200, "data": []}))
        monkeypatch.setattr("cart.java_client.httpx.AsyncClient", FakeAsyncClient)

        client = CartJavaClient(base_url="http://java")
        result = await client.list_cart(None)

        assert result.success is False
        assert result.error_code == "LOGIN_REQUIRED"
        assert FakeAsyncClient.calls == []

    asyncio.run(run())


def test_unauthorized_maps_to_login_expired(monkeypatch):
    async def run():
        reset_fake(httpx.Response(401, json={"code": 401, "message": "Unauthorized"}))
        monkeypatch.setattr("cart.java_client.httpx.AsyncClient", FakeAsyncClient)

        result = await CartJavaClient(base_url="http://java").list_cart("token")

        assert result.success is False
        assert result.error_code == "LOGIN_EXPIRED"
        assert FakeAsyncClient.calls[0]["headers"]["Authorization"] == "Bearer token"

    asyncio.run(run())


def test_success_result_wraps_java_data(monkeypatch):
    async def run():
        reset_fake(httpx.Response(200, json={"code": 200, "message": "Success", "data": [{"productId": 1}]}))
        monkeypatch.setattr("cart.java_client.httpx.AsyncClient", FakeAsyncClient)

        result = await CartJavaClient(base_url="http://java").list_cart("token")

        assert result.success is True
        assert result.data["raw"] == [{"productId": 1}]

    asyncio.run(run())


def test_business_error_maps_to_java_api_error(monkeypatch):
    async def run():
        reset_fake(httpx.Response(200, json={"code": 500, "message": "failed"}))
        monkeypatch.setattr("cart.java_client.httpx.AsyncClient", FakeAsyncClient)

        result = await CartJavaClient(base_url="http://java").add_item("token", 1)

        assert result.success is False
        assert result.error_code == "JAVA_API_ERROR"
        assert result.message == "failed"

    asyncio.run(run())


def test_timeout_maps_to_tool_timeout(monkeypatch):
    async def run():
        reset_fake(exc=httpx.TimeoutException("slow"))
        monkeypatch.setattr("cart.java_client.httpx.AsyncClient", FakeAsyncClient)

        result = await CartJavaClient(base_url="http://java").count_cart("token")

        assert result.success is False
        assert result.error_code == "TOOL_TIMEOUT"

    asyncio.run(run())
