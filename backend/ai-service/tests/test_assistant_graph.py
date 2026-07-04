import asyncio

from agents.schemas import AgentFinalResponse, IntentDecision
from assistant.graph import AssistantGraph
from api.response_adapter import normalize_ai_response


class FakeRouterCompiled:
    def __init__(self, route):
        self.route = route

    async def ainvoke(self, payload, config=None):
        return {"structured_response": IntentDecision(task_type=self.route, confidence=0.9, reason="test")}


class FakeCartAgent:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return normalize_ai_response(
            {"answer": "cart", "task_type": "cart", "confirm_card": {"type": "confirm_card", "action": "add", "buttons": []}},
            run_id=kwargs.get("run_id"),
            trace_id=kwargs.get("trace_id"),
        )


class FakeShoppingAgent:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return normalize_ai_response(
            {"answer": "shopping", "task_type": "shopping", "product_cards": [{"product_id": 1, "title": "Test", "brand": "B"}]},
            run_id=kwargs.get("run_id"),
            trace_id=kwargs.get("trace_id"),
        )


def test_router_agent_routes_to_cart(monkeypatch):
    async def run():
        cart_agent = FakeCartAgent()
        shopping_agent = FakeShoppingAgent()
        monkeypatch.setattr("assistant.graph.create_agent", lambda *args, **kwargs: FakeRouterCompiled("cart"))
        graph = AssistantGraph(llm=object(), repository=object(), cart_agent=cart_agent, shopping_agent=shopping_agent)

        result = await graph.run(question="加入购物车", conversation_id="c1", product_id=1)

        assert result["task_type"] == "cart"
        assert result["confirm_card"]["action"] == "add"
        assert cart_agent.calls[0]["conversation_id"] == "c1"

    asyncio.run(run())


def test_router_agent_routes_to_shopping(monkeypatch):
    async def run():
        monkeypatch.setattr("assistant.graph.create_agent", lambda *args, **kwargs: FakeRouterCompiled("shopping"))
        graph = AssistantGraph(llm=object(), repository=object(), cart_agent=FakeCartAgent(), shopping_agent=FakeShoppingAgent())

        result = await graph.run(question="推荐一款防晒")

        assert result["task_type"] == "shopping"
        assert result["product_cards"][0]["product_id"] == 1

    asyncio.run(run())


def test_no_llm_returns_agent_error():
    async def run():
        graph = AssistantGraph(llm=None, repository=object(), cart_agent=FakeCartAgent(), shopping_agent=FakeShoppingAgent())

        result = await graph.run(question="推荐一款防晒")

        assert result["error"] is True
        assert result["error_code"] == "AI_LLM_NOT_CONFIGURED"

    asyncio.run(run())
class FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.result


def test_product_name_purchase_searches_then_prepares_confirm(monkeypatch):
    async def run():
        search_tool = FakeTool("search_products_by_name", [{"product_id": 9, "title": "Shiseido Serum", "brand": "Shiseido"}])
        cards_tool = FakeTool("build_product_cards", {"product_cards": [{"product_id": 9, "title": "Shiseido Serum"}]})
        prepare_tool = FakeTool("prepare_add_cart", {"answer": "confirm", "task_type": "cart", "confirm_card": {"type": "confirm_card", "action": "add", "product": {"product_id": 9, "quantity": 2}}})

        monkeypatch.setattr("assistant.graph.create_agent", lambda *args, **kwargs: FakeRouterCompiled("shopping"))
        monkeypatch.setattr("assistant.graph.build_shopping_tools", lambda repository, memory_context=None: [search_tool, cards_tool])
        monkeypatch.setattr("assistant.graph.build_cart_tools", lambda client, context: [prepare_tool])

        graph = AssistantGraph(llm=object(), repository=object(), cart_agent=FakeCartAgent(), shopping_agent=FakeShoppingAgent(), cart_client=object())
        result = await graph.run(question="我要2个资生堂红腰子", conversation_id="c-buy", user_id=1, quantity=1)

        assert result["confirm_card"]["action"] == "add"
        assert result["confirm_card"]["product"]["product_id"] == 9
        assert prepare_tool.calls[0]["quantity"] == 2
        assert search_tool.calls[0]["query"] == "资生堂红腰子"

    asyncio.run(run())


def test_second_one_short_reference_routes_to_shopping_memory(monkeypatch):
    async def run():
        from agents.memory import clear_business_memory, remember_product_cards

        clear_business_memory()
        remember_product_cards("c-ref", 1, [{"product_id": 10, "title": "A"}, {"product_id": 20, "title": "B"}])
        monkeypatch.setattr("assistant.graph.create_agent", lambda *args, **kwargs: FakeRouterCompiled("unknown"))
        graph = AssistantGraph(llm=object(), repository=object(), cart_agent=FakeCartAgent(), shopping_agent=FakeShoppingAgent())

        result = await graph.run(question="\u7b2c\u4e8c\u4e2a\u5427", conversation_id="c-ref", user_id=1)

        assert result["task_type"] == "shopping"
        assert result["product_cards"][0]["product_id"] == 20

    asyncio.run(run())
