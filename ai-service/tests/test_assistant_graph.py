import asyncio
from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from app.application.assistant import AssistantGraph
from app.application.assistant.graph import _build_task_business_memory
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


class FakeDelayedAgent:
    def __init__(self, answer, delay):
        self.answer = answer
        self.delay = delay

    async def run(self, **_kwargs):
        await asyncio.sleep(self.delay)
        return {
            "answer": self.answer,
            "task_type": "shopping",
            "product_cards": [],
            "sources": [],
            "tool_calls": [],
            "error": False,
        }


class FakeStreamingDelayedAgent:
    def __init__(self, chunks, delays):
        self.chunks = chunks
        self.delays = delays

    async def run(self, **kwargs):
        sink = kwargs.get("token_sink")
        for chunk, delay in zip(self.chunks, self.delays):
            await asyncio.sleep(delay)
            if sink is not None:
                sink(chunk)
        return {
            "answer": "".join(self.chunks),
            "task_type": "shopping",
            "product_cards": [],
            "sources": [],
            "tool_calls": [],
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


def test_complex_shopping_and_knowledge_subtasks_do_not_receive_parent_history():
    async def run():
        shopping = FakeShoppingAgent()
        knowledge = FakeKnowledgeAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=shopping, knowledge_agent=knowledge)
        parent_state = {
            "question": "原始复杂问题",
            "conversation_id": "phase5-isolated",
            "messages": [
                HumanMessage(content="这是不应该传给商品或知识子任务的历史文本"),
            ],
        }
        base_memory = {
            "selected_product_ids": [7],
            "user_preferences": {"preference_tags": ["轻便"]},
            "last_product_cards": [{"product_id": 999, "title": "无关历史商品"}],
            "active_product_set": {"product_ids": [7, 999]},
        }

        await graph._execute_subtask(
            parent_state=parent_state,
            task={"id": "t1", "question": "推荐通勤耳机", "intent_hint": "shopping", "depends_on": [], "use_image": False},
            level_index=0,
            result_by_id={},
            base_memory=base_memory,
            semaphore=asyncio.Semaphore(1),
        )
        await graph._execute_subtask(
            parent_state=parent_state,
            task={"id": "t2", "question": "解释开放式耳机和入耳式耳机的区别", "intent_hint": "knowledge", "depends_on": [], "use_image": False},
            level_index=0,
            result_by_id={},
            base_memory=base_memory,
            semaphore=asyncio.Semaphore(1),
        )

        assert shopping.calls[0]["messages"] == [{"role": "user", "content": "推荐通勤耳机"}]
        assert "last_product_cards" not in shopping.calls[0]["business_memory"]
        assert shopping.calls[0]["business_memory"]["selected_product_ids"] == [7]
        knowledge_messages = knowledge.calls[0]["messages"]
        assert len(knowledge_messages) == 1
        assert knowledge_messages[0].content == "解释开放式耳机和入耳式耳机的区别"

    asyncio.run(run())


def test_complex_chitchat_subtask_keeps_preparation_history_and_profile():
    async def run():
        graph = AssistantGraph(
            llm=_dummy_llm(), shopping_agent=FakeShoppingAgent(), knowledge_agent=FakeKnowledgeAgent(),
        )
        captured = {}

        async def fake_chitchat_node(state):
            captured.update(state)
            return {"answer": "已根据对话历史回答。", "task_type": "chitchat"}

        graph._nodes["chitchat_node"] = fake_chitchat_node
        parent_state = {
            "question": "原始复杂问题",
            "conversation_id": "phase5-chitchat",
            "messages": [HumanMessage(content="之前聊过的内容")],
            "conversation_history": [{"role": "user", "content": "之前聊过的内容"}],
            "gender": "female",
            "skin_type": "混合皮",
            "preference_tags": ["简洁"],
        }
        await graph._execute_subtask(
            parent_state=parent_state,
            task={"id": "t1", "question": "回顾刚才的重点", "intent_hint": "chitchat", "depends_on": [], "use_image": False},
            level_index=0,
            result_by_id={},
            base_memory={},
            semaphore=asyncio.Semaphore(1),
        )

        assert captured["messages"][0].content == "之前聊过的内容"
        assert captured["conversation_history"] == parent_state["conversation_history"]
        assert captured["gender"] == "female"
        assert captured["skin_type"] == "混合皮"
        assert captured["preference_tags"] == ["简洁"]

    asyncio.run(run())


def test_dependency_artifact_binds_products_without_restoring_parent_cards():
    memory = _build_task_business_memory(
        {
            "last_product_cards": [{"product_id": 999, "title": "父级历史商品"}],
            "user_preferences": {"preference_tags": ["轻便"]},
        },
        [{
            "task_id": "t1",
            "status": "success",
            "product_cards": [
                {"product_id": 7, "title": "上游商品 A"},
                {"product_id": 8, "title": "上游商品 B"},
            ],
        }],
    )

    assert memory["selected_product_ids"] == [7, 8]
    assert [card["product_id"] for card in memory["last_product_cards"]] == [7, 8]
    assert all(card["product_id"] != 999 for card in memory["last_product_cards"])


def test_complex_stream_emits_completed_subtasks_before_final():
    async def run():
        llm = _dummy_llm()
        graph = AssistantGraph(
            llm=llm,
            shopping_agent=FakeStreamingDelayedAgent(["商品", "结果"], [0.02, 0.01]),
            # The knowledge task produces its first token before Shopping has
            # completed, then produces the rest after Shopping.  This verifies
            # that its buffered prefix is released before its later live token.
            knowledge_agent=FakeStreamingDelayedAgent(["知识", "结果"], [0.01, 0.04]),
        )
        graph._router_llm = FakeStructuredLLM(IntentDecision(
            mode="complex", task_type="unknown", confidence=0.95,
            reason="两个独立目标", canonical_question="推荐耳机并解释耳机类型",
        ))
        graph._orchestrator_llm = FakeStructuredLLM(OrchestratorDecision(
            mode="complex",
            tasks=[
                {"id": "t1", "question": "推荐耳机", "intent_hint": "shopping", "depends_on": [], "use_image": False},
                {"id": "t2", "question": "解释耳机类型", "intent_hint": "knowledge", "depends_on": [], "use_image": False},
            ],
        ))

        events = [
            event async for event in graph.astream(
                question="推荐耳机并解释耳机类型",
                conversation_id="phase5-stream",
            )
        ]
        event_types = [event["type"] for event in events]
        completed = [event for event in events if event["type"] == "subtask_result"]

        assert "synthesize_final" not in graph.graph.get_graph().nodes
        # t2 finishes first internally, but user-visible results must preserve
        # Planner order so the answer never jumps from question 2 back to 1.
        # Execution remains concurrent; only publication is ordered.
        assert [event["data"]["task_id"] for event in completed] == ["t1", "t2"]
        assert [event["data"]["sequence"] for event in completed] == [1, 2]
        assert all(event["data"]["answer"] == "" for event in completed)
        assert event_types.index("subtask_result") < event_types.index("final")
        assert event_types.count("final") == 1
        assert event_types.count("done") == 1
        final = next(event["data"] for event in events if event["type"] == "final")
        assert final["answer"] == "商品结果\n\n知识结果"
        visible_text = "".join(
            event["data"]["content"]
            for event in events
            if event["type"] == "token"
        )
        assert visible_text == final["answer"]

    asyncio.run(run())


def test_stream_uses_custom_as_the_only_user_visible_token_channel():
    async def run():
        graph = AssistantGraph(llm=None)
        captured = {}

        class FakeCompiledGraph:
            async def aupdate_state(self, config, values):
                captured["reset_config"] = config
                captured["reset_values"] = values

            async def astream(self, state, config, stream_mode, subgraphs):
                captured["stream_mode"] = stream_mode
                captured["subgraphs"] = subgraphs
                yield (), "custom", {"type": "token", "data": {"content": "只发一次"}}
                yield (), "updates", {"format_response": {"result": {"answer": "只发一次"}}}

        graph.graph = FakeCompiledGraph()
        events = [
            event async for event in graph.astream(
                question="你好",
                conversation_id="single-token-channel",
            )
        ]

        assert captured["stream_mode"] == ["updates", "custom"]
        assert captured["subgraphs"] is True
        # ContextResolver owns construction of the shared summary + recent
        # visible messages. Before graph execution the Checkpointer is cleared
        # rather than seeded with a second raw-history copy.
        assert len(captured["reset_values"]["messages"]) == 1
        assert [event["data"]["content"] for event in events if event["type"] == "token"] == ["只发一次"]
        assert next(event["data"] for event in events if event["type"] == "final")["answer"] == "只发一次"

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

        async def astream(self, messages, **_kwargs):
            self.prompts = messages
            yield FakeChunk()

    async def run():
        llm = FakeLlm()
        result = await make_nodes(llm)["unknown_node"]({"question": "推荐一下"})
        assert result["answer"] == "你可以先告诉我想购买的商品品类和使用场景。"
        assert "当前用户问题：\n推荐一下" in llm.prompts[0].content

    asyncio.run(run())
