import asyncio

from app.application.assistant.schemas import IntentDecision
from app.application.assistant import AssistantGraph
from app.application.assistant.router import (
    can_short_circuit_orchestrator,
    classify_high_confidence_rule,
    normalize_llm_decision,
)
from evals.router_metrics import calculate_router_metrics


class FakeStructuredRouter:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.decision


def _graph_with_router(router):
    graph = AssistantGraph(llm=None)
    graph._router_llm = router
    return graph


def test_high_certainty_rules_cover_core_domains():
    assert classify_high_confidence_rule("推荐一款防晒").route == "shopping"
    assert classify_high_confidence_rule("这个商品有货吗").route == "shopping"
    assert classify_high_confidence_rule("烟酰胺有什么功效").route == "knowledge"
    assert classify_high_confidence_rule("你好").route == "chitchat"
    assert classify_high_confidence_rule("找同款", has_image=True).route == "shopping"


def test_mixed_signal_is_deferred_to_llm():
    decision = classify_high_confidence_rule("我想买防晒，但不知道应该怎么选")
    assert decision.matched is False
    assert decision.route == "unknown"


def test_llm_is_primary_even_when_a_rule_would_match(monkeypatch):
    monkeypatch.setattr("app.application.assistant.graph.config.ROUTER_LOW_CONFIDENCE_THRESHOLD", 0.65)
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            task_type="shopping", confidence=0.98, reason="明确商品推荐",
            canonical_question="推荐一款防晒",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({"question": "推荐一款防晒", "messages": []})
        assert result["route"] == "shopping"
        assert result["route_source"] == "llm"
        assert result["rule_route"] == "shopping"
        assert result["llm_route"] == "shopping"
        assert result["question"] == "推荐一款防晒"
        assert router.calls == 1

    asyncio.run(run())


def test_unresolved_rule_uses_confident_llm_route(monkeypatch):
    monkeypatch.setattr("app.application.assistant.graph.config.ROUTER_LOW_CONFIDENCE_THRESHOLD", 0.65)
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            task_type="knowledge", confidence=0.86, reason="用户在询问选择方法",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "我想买防晒，但不知道应该怎么选",
            "messages": [],
        })
        assert result["route"] == "knowledge"
        assert result["route_source"] == "llm"
        assert result["llm_route"] == "knowledge"
        assert result["llm_confidence"] == 0.86
        assert result["route_fallback_used"] is False
        assert router.calls == 1

    asyncio.run(run())


def test_low_confidence_llm_asks_for_clarification(monkeypatch):
    monkeypatch.setattr("app.application.assistant.graph.config.ROUTER_LOW_CONFIDENCE_THRESHOLD", 0.65)
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            task_type="shopping", confidence=0.42, reason="表达含糊",
        ))
        graph = _graph_with_router(router)
        result = await graph._route({"question": "帮我看看这个", "messages": []})
        assert result["route"] == "unknown"
        assert result["route_source"] == "fallback"
        assert result["llm_route"] == "shopping"
        assert result["route_fallback_used"] is True
        assert "请补充" in result["route_clarification"]

    asyncio.run(run())


def test_router_binds_only_offered_product_ids():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            task_type="shopping", confidence=0.91, reason="商品追问",
            canonical_question="介绍商品 A 和商品 C 的差异",
            resolved_product_ids=[11, 13],
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "第一款和第三款呢？",
            "messages": [],
            "business_memory": {"last_product_cards": [
                {"product_id": 11, "title": "商品 A"},
                {"product_id": 12, "title": "商品 B"},
                {"product_id": 13, "title": "商品 C"},
            ]},
        })
        assert result["route"] == "shopping"
        assert result["question"] == "介绍商品 A 和商品 C 的差异"
        assert [card["product_id"] for card in result["business_memory"]["last_product_cards"]] == [11, 13]

    asyncio.run(run())


def test_router_rejects_hallucinated_product_id():
    async def run():
        router = FakeStructuredRouter(IntentDecision(
            task_type="shopping", confidence=0.91, reason="商品追问",
            canonical_question="介绍不存在的商品",
            resolved_product_ids=[999],
        ))
        graph = _graph_with_router(router)
        result = await graph._route({
            "question": "第一款呢？",
            "messages": [],
            "business_memory": {"last_product_cards": [{"product_id": 11, "title": "商品 A"}]},
        })
        assert result["route"] == "unknown"
        assert result["route_fallback_used"] is True

    asyncio.run(run())


def test_rule_can_override_conflicting_orchestrator_hint():
    async def run():
        graph = _graph_with_router(FakeStructuredRouter())
        result = await graph._route({
            "question": "烟酰胺有什么功效",
            "messages": [],
            "active_subtask": {"intent_hint": "shopping", "use_image": False},
        })
        assert result["route"] == "knowledge"
        assert result["route_source"] == "rule_override"

    asyncio.run(run())


def test_obvious_single_intent_can_skip_orchestrator():
    assert can_short_circuit_orchestrator("你好") is True
    assert can_short_circuit_orchestrator("推荐面霜，然后解释烟酰胺功效") is False
    assert can_short_circuit_orchestrator("介绍图片里的成分", has_image=True) is False
    assert can_short_circuit_orchestrator("推荐 iPhone 和 MacBook 各一款") is False
    assert can_short_circuit_orchestrator("推荐一款面霜、一款防晒") is False


def test_historical_cart_route_is_normalized_to_shopping():
    decision = normalize_llm_decision({
        "task_type": "cart", "confidence": 0.9, "reason": "历史模型输出",
    })
    assert decision.task_type == "shopping"


def test_router_metrics_separate_safe_fallback_from_misroute():
    metrics = calculate_router_metrics([
        {"expected_route": "shopping", "predicted_route": "shopping", "route_source": "rule"},
        {"expected_route": "knowledge", "predicted_route": "shopping", "route_source": "llm"},
        {"expected_route": "knowledge", "predicted_route": "unknown", "route_source": "fallback", "fallback_used": True},
    ])
    assert metrics["route_accuracy"] == 0.3333
    assert metrics["misroute_rate"] == 0.3333
    assert metrics["low_confidence_rate"] == 0.3333
    assert metrics["rule_direct_rate"] == 0.3333
