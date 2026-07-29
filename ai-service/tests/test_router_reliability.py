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


def test_router_uses_llm_for_image_input_instead_of_rule_shortcut():
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
        assert router.calls == 1
        assert any("上传了参考图片" in str(getattr(message, "content", "")) for message in router.messages)

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
