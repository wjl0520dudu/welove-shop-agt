import asyncio

from agents.schemas import AgentFinalResponse
from cart.cart_agent import CartAgent
from cart.models import CartToolResult
from tools.cart_tools import build_cart_tools
from agents.schemas import AgentRequestContext


class FakeCartClient:
    def __init__(self):
        self.add_calls = []
        self.list_calls = []

    async def list_cart(self, jwt_token):
        self.list_calls.append(jwt_token)
        return CartToolResult(success=True, action="list", message="Success", data={"raw": [{"productId": 1, "quantity": 2, "product": {"title": "Sunscreen"}}]})

    async def count_cart(self, jwt_token):
        return CartToolResult(success=True, action="count", message="Success", data={"raw": 2})

    async def add_item(self, jwt_token, product_id, sku_id=None):
        self.add_calls.append((jwt_token, product_id, sku_id))
        return CartToolResult(success=True, action="add", message="已加入购物车。")

    async def update_quantity(self, jwt_token, product_id, quantity):
        return CartToolResult(success=True, action="update", message="已更新数量。")

    async def remove_item(self, jwt_token, product_id=None, cart_item_id=None, quantity=None):
        return CartToolResult(success=True, action="remove", message="已移除商品。")


class FakeCompiledAgent:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def ainvoke(self, payload, config=None):
        self.calls.append((payload, config))
        return {"structured_response": self.response}


def test_cart_agent_uses_react_agent_and_memory_config(monkeypatch):
    async def run():
        compiled = FakeCompiledAgent(AgentFinalResponse(answer="ok", task_type="cart"))
        captured = {}

        def fake_create_react_agent(model, tools, **kwargs):
            captured["model"] = model
            captured["tools"] = tools
            captured["kwargs"] = kwargs
            return compiled

        monkeypatch.setattr("cart.cart_agent.create_react_agent", fake_create_react_agent)
        response = await CartAgent(llm=object(), client=FakeCartClient()).run(
            question="查看购物车",
            jwt_token="token",
            conversation_id="c1",
            user_id=7,
        )

        assert response.task_type == "cart"
        assert captured["tools"]
        assert captured["kwargs"]["checkpointer"] is not None
        assert compiled.calls[0][1]["configurable"]["thread_id"] == "c1"

    asyncio.run(run())


def test_prepare_add_returns_confirm_without_java_call():
    async def run():
        client = FakeCartClient()
        tools = build_cart_tools(
            client,
            AgentRequestContext(jwt_token="token", confirmed=False, product_id=1, quantity=2),
        )
        prepare_add = next(tool for tool in tools if tool.name == "prepare_add_cart")
        result = await prepare_add.ainvoke({"product_id": 1, "quantity": 2})

        assert result["confirm_card"]["action"] == "add"
        assert client.add_calls == []

    asyncio.run(run())


def test_execute_add_after_confirm_calls_java_without_logging_token():
    async def run():
        client = FakeCartClient()
        tools = build_cart_tools(
            client,
            AgentRequestContext(jwt_token="token", confirmed=True, product_id=1),
        )
        execute_add = next(tool for tool in tools if tool.name == "execute_add_cart")
        result = await execute_add.ainvoke({"product_id": 1})

        assert client.add_calls == [("token", 1, None)]
        assert result["tool_call"]["tool_name"] == "cart_add"
        assert "jwt_token" not in result["tool_call"]["input_params"]

    asyncio.run(run())


def test_list_cart_tool_returns_cart_list():
    async def run():
        client = FakeCartClient()
        tools = build_cart_tools(client, AgentRequestContext(jwt_token="token"))
        list_cart = next(tool for tool in tools if tool.name == "list_cart")
        result = await list_cart.ainvoke({})

        assert client.list_calls == ["token"]
        assert result["cart_list"]["items"][0]["product_id"] == 1

    asyncio.run(run())

def test_prepare_add_uses_business_memory_focused_product():
    async def run():
        client = FakeCartClient()
        tools = build_cart_tools(
            client,
            AgentRequestContext(
                jwt_token="token",
                confirmed=False,
                quantity=1,
                business_memory={"last_focused_product": {"product_id": 88, "title": "Remembered"}},
            ),
        )
        prepare_add = next(tool for tool in tools if tool.name == "prepare_add_cart")
        result = await prepare_add.ainvoke({})

        assert result["confirm_card"]["product"]["product_id"] == 88
        assert client.add_calls == []

    asyncio.run(run())
