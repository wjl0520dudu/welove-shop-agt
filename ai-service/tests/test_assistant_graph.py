import asyncio
from unittest.mock import MagicMock

from app.application.assistant import AssistantGraph
from app.application.assistant.router_tools import format_business_memory_for_router
from app.application.assistant.schemas import IntentDecision, OrchestratorDecision


class FakeStructuredLLM:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):
        self.calls += 1
        return self.decision


class FakeShoppingAgent:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "answer": "找到适合的商品。",
            "task_type": "shopping",
            "product_cards": [{"product_id": 7, "title": "通勤耳机"}],
            "sources": [],
            "tool_calls": [],
            "error": False,
        }


class FakeKnowledgeAgent:
    def __init__(self):
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "answer": "开放式耳机更开放，入耳式隔音更好。",
            "task_type": "knowledge",
            "sources": [{"doc_id": 1, "doc_name": "耳机知识"}],
            "has_answer": True,
            "error": False,
        }


def _dummy_llm():
    llm = MagicMock()
    llm.with_structured_output.return_value = MagicMock()
    return llm


def test_simple_router_path_does_not_call_planner():
    async def run():
        shopping = FakeShoppingAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=shopping, knowledge_agent=FakeKnowledgeAgent())
        graph._router_llm = FakeStructuredLLM(IntentDecision(
            mode="simple", task_type="shopping", confidence=0.96,
            reason="明确商品推荐", canonical_question="推荐适合通勤的耳机",
        ))
        planner = FakeStructuredLLM(None)
        graph._orchestrator_llm = planner

        result = await graph.run(question="推荐通勤耳机", conversation_id="phase1-simple")
        assert result["task_type"] == "shopping"
        assert shopping.calls[0]["question"] == "推荐适合通勤的耳机"
        assert graph._router_llm.calls == 1
        assert planner.calls == 0

    asyncio.run(run())


def test_complex_router_calls_planner_once_and_subtasks_do_not_reroute():
    async def run():
        shopping = FakeShoppingAgent()
        knowledge = FakeKnowledgeAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=shopping, knowledge_agent=knowledge)
        router = FakeStructuredLLM(IntentDecision(
            mode="complex", task_type="unknown", confidence=0.95,
            reason="推荐和知识解释是独立目标",
            canonical_question="推荐适合通勤的耳机，并解释开放式耳机和入耳式耳机的区别",
        ))
        planner = FakeStructuredLLM(OrchestratorDecision(
            mode="complex",
            reason="拆分推荐与知识解释",
            tasks=[
                {"id": "t1", "question": "推荐适合通勤的耳机", "intent_hint": "shopping", "depends_on": [], "use_image": False},
                {"id": "t2", "question": "解释开放式耳机和入耳式耳机的区别", "intent_hint": "knowledge", "depends_on": [], "use_image": False},
            ],
        ))
        graph._router_llm = router
        graph._orchestrator_llm = planner

        result = await graph.run(question="推荐耳机，同时解释开放式和入耳式区别", conversation_id="phase1-complex")
        assert result["task_type"] == "complex"
        assert result["route"] == "complex"
        assert result["orchestrator_mode"] == "complex"
        assert router.calls == 1
        assert planner.calls == 1
        assert len(shopping.calls) == 1
        assert len(knowledge.calls) == 1
        assert [item["route_source"] for item in result["sub_results"]] == ["planner", "planner"]

    asyncio.run(run())


def test_complex_planner_failure_does_not_use_heuristic_splitter():
    async def run():
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=FakeShoppingAgent(), knowledge_agent=FakeKnowledgeAgent())
        graph._orchestrator_llm = FakeStructuredLLM(None)
        result = await graph._plan_complex({
            "question": "推荐耳机并解释开放式和入耳式区别",
            "canonical_question": "推荐耳机并解释开放式和入耳式区别",
            "business_memory": {},
        })
        assert result["error"] is True
        assert result["sub_questions"] == []
        assert result["orchestrator_plan_error"]
        assert result["task_type"] == "complex"
        assert result["route"] == "complex"

    asyncio.run(run())


def test_full_conversation_history_is_not_truncated():
    graph = AssistantGraph.__new__(AssistantGraph)
    history = [
        {"id": index, "role": "user" if index % 2 else "assistant", "content": f"第 {index} 条"}
        for index in range(1, 19)
    ]
    state, _, _ = graph._make_initial_state(question="最后的问题", conversation_history=history)
    assert len(state["conversation_history"]) == 19
    assert state["conversation_history"][0]["content"] == "第 1 条"


def test_router_context_keeps_all_product_cards_in_order():
    cards = [{"product_id": index, "title": f"商品 {index}", "price": index} for index in range(1, 9)]
    rendered = format_business_memory_for_router({"last_product_cards": cards})
    assert "1. [product_id=1]" in rendered
    assert "8. [product_id=8]" in rendered


def test_unknown_node_uses_plain_need_description_prompt():
    async def run():
        graph = AssistantGraph(llm=None)
        result = await graph._nodes["unknown_node"]({})
        assert "清楚描述" in result["answer"]

    asyncio.run(run())


def test_unknown_node_uses_contextual_product_clarification():
    async def run():
        graph = AssistantGraph(llm=None)
        result = await graph._nodes["unknown_node"]({
            "route_clarification": "当前只有 2 款商品可供查询，请问你是想查询当前这 2 款吗？",
        })
        assert result["answer"] == "当前只有 2 款商品可供查询，请问你是想查询当前这 2 款吗？"

    asyncio.run(run())


def test_unknown_node_uses_llm_to_naturally_express_fallback():
    from app.application.assistant.nodes import make_nodes

    class FakeChunk:
        content = "你可以先告诉我想购买的商品品类和使用场景。"

    class FakeLlm:
        def __init__(self):
            self.prompts = []

        async def astream(self, messages):
            self.prompts = messages
            yield FakeChunk()

    async def run():
        llm = FakeLlm()
        result = await make_nodes(llm)["unknown_node"]({"question": "推荐一下"})
        assert result["answer"] == "你可以先告诉我想购买的商品品类和使用场景。"
        assert "当前用户问题：\n推荐一下" in llm.prompts[0].content

    asyncio.run(run())
