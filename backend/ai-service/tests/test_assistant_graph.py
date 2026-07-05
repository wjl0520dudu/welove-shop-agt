import asyncio
from agents.schemas import IntentDecision
from agents.memory import clear_business_memory, remember_product_cards, get_business_memory
from assistant.graph import AssistantGraph


class FakeShoppingAgent:
    def __init__(self):
        self.calls = []

    async def run(self, *, question, messages, business_memory, conversation_id=None, user_id=None):
        self.calls.append({"question": question, "business_memory": business_memory})
        return {"answer": "找到的防晒商品如下。", "task_type": "shopping",
                "product_cards": [{"product_id": 7, "title": "安耐晒", "brand": "Shiseido"}],
                "sources": [], "tool_calls": [], "error": False}


class FakeKnowledgeAgent:
    def __init__(self):
        self.calls = []

    async def ask(self, *, question, business_memory):
        self.calls.append({"question": question})
        return {"answer": "防晒霜的成分主要包括二氧化钛等。", "task_type": "knowledge",
                "sources": [{"doc_id": 1, "doc_name": "成分手册"}], "error": False}


def _patch_router(monkeypatch, route):
    async def fake_classify(llm, *, question, messages, business_memory):
        return IntentDecision(task_type=route, confidence=0.9, reason="test")
    monkeypatch.setattr("assistant.graph.classify_intent", fake_classify)


def test_router_routes_to_shopping(monkeypatch):
    async def run():
        clear_business_memory()
        _patch_router(monkeypatch, "shopping")
        shopping = FakeShoppingAgent()
        graph = AssistantGraph(llm=object(), shopping_agent=shopping, knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="推荐一款防晒", conversation_id="c1", user_id=1)
        assert result["task_type"] == "shopping"
        assert result["product_cards"][0]["product_id"] == 7
        assert shopping.calls[0]["question"] == "推荐一款防晒"
    asyncio.run(run())


def test_router_routes_to_knowledge(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "knowledge")
        knowledge = FakeKnowledgeAgent()
        graph = AssistantGraph(llm=object(), shopping_agent=FakeShoppingAgent(), knowledge_agent=knowledge)
        result = await graph.run(question="防晒霜的成分是什么")
        assert result["task_type"] == "knowledge"
        assert result["sources"][0]["doc_name"] == "成分手册"
        assert knowledge.calls[0]["question"] == "防晒霜的成分是什么"
    asyncio.run(run())


def test_router_routes_to_chitchat(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "chitchat")
        # LCEL 管道要求 llm 是 Runnable；用 RunnableLambda 构造可组合的真 Runnable
        from langchain_core.runnables import RunnableLambda
        from langchain_core.messages import AIMessage
        async def _fake_llm(messages, config=None, **kwargs):
            return AIMessage(content="你好呀！有什么想买的吗？")
        llm = RunnableLambda(_fake_llm)
        graph = AssistantGraph(llm=llm, shopping_agent=FakeShoppingAgent(), knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="你好")
        assert result["task_type"] == "chitchat"
        assert "你好" in result["answer"]
    asyncio.run(run())



def test_router_routes_to_unknown(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "unknown")
        graph = AssistantGraph(llm=object(), shopping_agent=FakeShoppingAgent(), knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="随便说点啥")
        assert result["task_type"] == "unknown"
        assert result["answer"]
    asyncio.run(run())


def test_no_llm_routes_to_unknown(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "unknown")
        graph = AssistantGraph(llm=None, shopping_agent=None, knowledge_agent=None)
        result = await graph.run(question="推荐一款防晒")
        assert result["task_type"] == "unknown"
    asyncio.run(run())


def test_business_memory_shared_across_turns(monkeypatch):
    async def run():
        clear_business_memory()
        _patch_router(monkeypatch, "shopping")
        shopping = FakeShoppingAgent()
        graph = AssistantGraph(llm=object(), shopping_agent=shopping, knowledge_agent=FakeKnowledgeAgent())
        await graph.run(question="推荐一款防晒", conversation_id="c-mem", user_id=42)
        mem = get_business_memory("c-mem", 42)
        assert mem.get("last_product_cards")
        assert mem["last_product_cards"][0]["product_id"] == 7
        shopping.calls.clear()
        await graph.run(question="第一个怎么样", conversation_id="c-mem", user_id=42)
        assert shopping.calls[0]["business_memory"].get("last_product_cards")
    asyncio.run(run())


def test_error_node_returns_error_fields(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "shopping")
        class BoomShopping:
            async def run(self, **kwargs):
                raise RuntimeError("boom")
        graph = AssistantGraph(llm=object(), shopping_agent=BoomShopping(), knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="推荐一款防晒")
        assert result["error"] is True
        assert result["error_code"] == "AI_SHOPPING_ERROR"
    asyncio.run(run())


def test_run_id_and_trace_id_present(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "unknown")
        graph = AssistantGraph(llm=object(), shopping_agent=None, knowledge_agent=None)
        result = await graph.run(question="hi", conversation_id="c-rt")
        assert result["run_id"]
        assert result["trace_id"]
    asyncio.run(run())
