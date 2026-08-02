import asyncio

from app.application.assistant import AssistantGraph
from app.application.assistant.schemas import IntentDecision
from app.application.assistant.router import normalize_llm_decision


class FakeStructuredRouter:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.calls = 0
        self.messages = []

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        self.messages = messages
        if self.error:
            raise self.error
        return self.decision


def _graph_with_router(router):
    graph = AssistantGraph(llm=None)
    graph._router_llm = router
    return graph


def test_router_uses_llm_for_simple_shopping_and_rewrites_question():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="shopping",
            confidence=0.98,
            reason="明确商品推荐",
            canonical_question="推荐一款适合通勤、预算 500 元以内的耳机",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "推荐通勤耳机，500 内",
            "messages": [],
            "business_memory": {},
        })
        assert result["route"] == "shopping"
        assert result["orchestrator_mode"] == "simple"
        assert result["route_source"] == "llm"
        assert result["question"] == "推荐一款适合通勤、预算 500 元以内的耳机"
        assert router.calls == 1

    asyncio.run(run())


def test_router_marks_compound_request_complex_without_generating_dag():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="complex",
            task_type="unknown",
            confidence=0.93,
            reason="商品推荐和知识解释是独立目标",
            canonical_question="推荐适合通勤的耳机，并解释开放式耳机与入耳式耳机的区别",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "推荐耳机，同时解释开放式和入耳式区别",
            "messages": [],
            "business_memory": {},
        })
        assert result["orchestrator_mode"] == "complex"
        assert result["route"] == "unknown"
        assert graph._after_route(result) == "complex"
        assert result["question"].startswith("推荐适合通勤")

    asyncio.run(run())


def test_router_keeps_full_card_set_without_entity_validation_or_slicing():
    async def run():
        cards = [
            {"product_id": index, "title": f"商品 {index}", "price": index * 10}
            for index in range(1, 8)
        ]
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="shopping",
            confidence=0.9,
            reason="商品追问",
            canonical_question="介绍商品 1 和商品 7 的差异",
            resolved_product_ids=[1, 7],
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "第一款和第七款呢？",
            "messages": [],
            "business_memory": {"last_product_cards": cards},
        })
        assert result["route"] == "shopping"
        assert result["business_memory"]["last_product_cards"] == cards
        assert result["business_memory"]["selected_product_ids"] == [1, 7]
        prompt_text = "\n".join(str(getattr(message, "content", "")) for message in router.messages)
        assert "商品 7" in prompt_text

    asyncio.run(run())


def test_router_routes_empty_text_image_as_a_new_shopping_search():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="shopping",
            confidence=0.97,
            reason="图片相似商品检索",
            canonical_question="根据图片检索相似商品",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "",
            "image_url": "/weloveshop/products/p.jpg",
            "messages": [],
            "business_memory": {},
        })
        assert result["route"] == "shopping"
        assert result["question"] == "根据当前图片查找相似商品"
        assert result["business_memory"]["selected_product_ids"] == []
        # An explicit image-only input must not inherit the preceding detail
        # turn, so it does not need an LLM context interpretation first.
        assert router.calls == 0

    asyncio.run(run())


def test_router_routes_image_led_vague_text_as_pure_image_search():
    """Image semantics come from the Router LLM, not a wording keyword list."""
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="shopping",
            confidence=0.96,
            reason="用户要求根据当前图片查找商品",
            canonical_question="根据当前图片查找相似商品",
            image_query_mode="image_only",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "给我找这个东西",
            "image_url": "https://img.example.test/shoe.jpg",
            "messages": [],
            "business_memory": {},
        })

        assert result["route"] == "shopping"
        assert result["question"] == "根据当前图片查找相似商品"
        assert result["input_mode"] == "image"
        assert result["route_source"] == "llm"

    asyncio.run(run())


def test_router_rejects_whole_binding_when_any_product_id_is_outside_active_cards():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="shopping",
            confidence=0.92,
            reason="模型错误地猜测了历史商品",
            canonical_question="查询第一款商品价格",
            resolved_product_ids=[42, 999],
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "第一款多少钱？",
            "messages": [],
            "business_memory": {
                "active_product_set": {"product_ids": [7, 9]},
                "last_product_cards": [{"product_id": 7}, {"product_id": 9}],
            },
        })
        assert result["route"] == "unknown"
        assert result["route_fallback_used"] is True
        assert result["route_clarification"] == (
            "当前只有 2 款商品可供查询，暂时无法定位你提到的商品。"
            "请问你是想查询当前这 2 款吗？"
        )
        assert result["business_memory"]["selected_product_ids"] == []

    asyncio.run(run())


def test_router_unknown_decision_can_supply_contextual_clarification():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="unknown",
            confidence=0.91,
            reason="第三款不在当前集合中",
            clarification="当前只有 2 款商品可供查询，请问你是想查询当前这 2 款吗？",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "第一款和第三款呢？",
            "messages": [],
            "business_memory": {
                "active_product_set": {"product_ids": [11, 12]},
                "last_product_cards": [{"product_id": 11}, {"product_id": 12}],
            },
        })

        assert result["route"] == "unknown"
        assert result["route_clarification"] == (
            "当前只有 2 款商品可供查询，请问你是想查询当前这 2 款吗？"
        )

    asyncio.run(run())


def test_router_prompt_forbids_partial_binding_for_out_of_range_ordinal():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            mode="simple",
            task_type="unknown",
            confidence=0.95,
            reason="the third card does not exist",
            canonical_question="first and third items",
            resolved_product_ids=[],
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "first and third items",
            "messages": [],
            "business_memory": {
                "active_product_set": {"product_ids": [11, 12]},
                "last_product_cards": [
                    {"product_id": 11, "title": "A"},
                    {"product_id": 12, "title": "B"},
                ],
            },
        })

        prompt_text = "\n".join(
            str(getattr(message, "content", "")) for message in router.messages
        )
        assert "第一款和第三款" in prompt_text
        assert "整个引用都视为无法可靠解析" in prompt_text
        assert result["route"] == "unknown"
        assert result["business_memory"]["selected_product_ids"] == []

    asyncio.run(run())


def test_router_unknown_and_transport_failures_use_unknown_fallback():
    async def run():
        unknown = _graph_with_router(FakeStructuredRouter(IntentDecision(
            mode="simple", task_type="unknown", confidence=0.2, reason="需求不明确",
        )))
        result = await unknown._route({"question": "随便看看", "messages": [], "business_memory": {}})
        assert result["route"] == "unknown"
        assert result["route_fallback_used"] is True

        failed = _graph_with_router(FakeStructuredRouter(error=RuntimeError("network")))
        result = await failed._route({"question": "推荐耳机", "messages": [], "business_memory": {}})
        assert result["route"] == "unknown"
        assert result["route_source"] == "fallback"

    asyncio.run(run())


def test_historical_cart_route_is_normalized_to_shopping():
    decision = normalize_llm_decision({
        "mode": "simple", "task_type": "cart", "confidence": 0.9, "reason": "历史模型输出",
    })
    assert decision.task_type == "shopping"
