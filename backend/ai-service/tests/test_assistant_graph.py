import asyncio
from unittest.mock import MagicMock

from agents.schemas import IntentDecision
from agents.memory import remember_product_cards, get_business_memory
from assistant.graph import AssistantGraph


def clear_business_memory():
    """老测试遗留的钩子，现在业务记忆按 conversation_id 隔离，测试用不同 cid 即可，
    这里保留空实现避免 import 失败。"""
    pass


def _dummy_llm():
    """构造一个够用的 llm mock：只需要 `.with_structured_output(...)` 不报错即可。

    AssistantGraph.__init__ 里调 `llm.with_structured_output(IntentDecision, method="function_calling")`
    产出 `self._router_llm`，但被 _patch_router 覆盖 _route 后 _router_llm 根本用不上，
    所以返回值是啥无所谓。历史用 llm=_dummy_llm() 直接抛 AttributeError。
    """
    llm = MagicMock()
    llm.with_structured_output.return_value = MagicMock()
    return llm


class FakeShoppingAgent:
    def __init__(self):
        self.calls = []

    async def run(self, *, question, messages, business_memory,
                  conversation_id=None, user_id=None, jwt_token=None):
        # 记录调用参数供断言（包括 business_memory，用于跨轮共享测试）
        self.calls.append({
            "question": question,
            "business_memory": business_memory,
            "conversation_id": conversation_id,
        })
        product_cards = [{"product_id": 7, "title": "安耐晒", "brand": "Shiseido"}]
        # 真的 ShoppingAgent 会把 product_cards 写进 Store（供下一轮跨轮记忆读取）
        # Fake agent 也得模拟这个行为，否则 test_business_memory_shared_across_turns 拿不到
        if conversation_id:
            try:
                await remember_product_cards(conversation_id, user_id, product_cards)
            except Exception:  # noqa: BLE001
                pass
        return {
            "answer": "找到的防晒商品如下。",
            "task_type": "shopping",
            "product_cards": product_cards,
            "sources": [], "tool_calls": [], "error": False,
        }


class FakeKnowledgeAgent:
    def __init__(self):
        self.calls = []

    async def run(self, *, messages, conversation_id="", user_id=None):
        # knowledge_node 调 .run（不是 .ask）；参数是 messages / conversation_id / user_id
        # question 从 messages 里最后一条 human message 取（供老测试断言）
        last_user = ""
        for m in reversed(messages or []):
            role = getattr(m, "type", "") or (m.get("role", "") if isinstance(m, dict) else "")
            content = getattr(m, "content", "") if not isinstance(m, dict) else m.get("content", "")
            if role in ("human", "user") and content:
                last_user = content
                break
        self.calls.append({"question": last_user, "conversation_id": conversation_id})
        return {
            "answer": "防晒霜的成分主要包括二氧化钛等。",
            "task_type": "knowledge",
            "sources": [{"doc_id": 1, "doc_name": "成分手册"}],
            "has_answer": True,
            "error": False,
        }


def _patch_router(monkeypatch, route):
    """让 AssistantGraph._route 直接返回预设 route，跳过真 LLM。

    历史版本 patch 的是 `assistant.graph.classify_intent`（老 API），但当前 graph
    走 `_route` 方法内部的 `self._router_llm.ainvoke(...)`（with_structured_output 直链）
    ，那个函数已经被移除。这里改成 patch `AssistantGraph._route` 本身，
    覆盖面更精确、不依赖 LLM 的具体实现。
    """
    async def fake_route(self, state):
        return {"route": route, "route_reason": "test"}

    monkeypatch.setattr("assistant.graph.AssistantGraph._route", fake_route)


def test_router_routes_to_shopping(monkeypatch):
    async def run():
        clear_business_memory()
        _patch_router(monkeypatch, "shopping")
        shopping = FakeShoppingAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=shopping, knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="推荐一款防晒", conversation_id="c1", user_id=1)
        assert result["task_type"] == "shopping"
        assert result["product_cards"][0]["product_id"] == 7
        assert shopping.calls[0]["question"] == "推荐一款防晒"
    asyncio.run(run())


def test_router_routes_to_knowledge(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "knowledge")
        knowledge = FakeKnowledgeAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=FakeShoppingAgent(), knowledge_agent=knowledge)
        result = await graph.run(question="防晒霜的成分是什么")
        assert result["task_type"] == "knowledge"
        assert result["sources"][0]["doc_name"] == "成分手册"
        assert knowledge.calls[0]["question"] == "防晒霜的成分是什么"
    asyncio.run(run())


def test_router_routes_to_chitchat(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "chitchat")
        # chitchat_node 内部会跟 llm 交互；用 RunnableLambda 构造可组合的假 LLM。
        # AssistantGraph 构造时会调 llm.with_structured_output(...)，为此在外面套一层
        # duck-type mock 让它不炸（真正的 chitchat 走 llm 本身，不走 _router_llm）。
        from langchain_core.runnables import RunnableLambda
        from langchain_core.messages import AIMessage
        async def _fake_llm(messages, config=None, **kwargs):
            return AIMessage(content="你好呀！有什么想买的吗？")
        chitchat_llm = RunnableLambda(_fake_llm)
        # 给它加个 .with_structured_output（AssistantGraph.__init__ 需要）
        chitchat_llm.with_structured_output = lambda *a, **k: MagicMock()
        graph = AssistantGraph(llm=chitchat_llm, shopping_agent=FakeShoppingAgent(),
                               knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="你好")
        assert result["task_type"] == "chitchat"
        assert "你好" in result["answer"]
    asyncio.run(run())



def test_router_routes_to_unknown(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "unknown")
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=FakeShoppingAgent(), knowledge_agent=FakeKnowledgeAgent())
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
    """跨轮记忆：第一轮 shopping 写入的 last_product_cards，第二轮从 Store 读到。

    真的 ShoppingAgent.run 内部自己从 Store 拿 memory（不依赖 state["business_memory"]），
    所以断言点改成"直接查 Store"，不再断言 shopping.calls[i]["business_memory"]。
    """
    async def run():
        clear_business_memory()
        _patch_router(monkeypatch, "shopping")
        shopping = FakeShoppingAgent()
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=shopping,
                               knowledge_agent=FakeKnowledgeAgent())
        await graph.run(question="推荐一款防晒", conversation_id="c-mem", user_id=42)

        # 第一轮跑完，Store 里应该有 last_product_cards（FakeShoppingAgent 内部会写）
        mem = await get_business_memory("c-mem", 42)
        assert mem.get("last_product_cards")
        assert mem["last_product_cards"][0]["product_id"] == 7

        # 第二轮再跑一次，Store 里的记忆继续存在（未被清空）
        shopping.calls.clear()
        await graph.run(question="第一个怎么样", conversation_id="c-mem", user_id=42)
        mem2 = await get_business_memory("c-mem", 42)
        assert mem2.get("last_product_cards")
    asyncio.run(run())


def test_error_node_returns_error_fields(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "shopping")
        class BoomShopping:
            async def run(self, **kwargs):
                raise RuntimeError("boom")
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=BoomShopping(), knowledge_agent=FakeKnowledgeAgent())
        result = await graph.run(question="推荐一款防晒")
        assert result["error"] is True
        assert result["error_code"] == "AI_SHOPPING_ERROR"
    asyncio.run(run())


def test_run_id_and_trace_id_present(monkeypatch):
    async def run():
        _patch_router(monkeypatch, "unknown")
        graph = AssistantGraph(llm=_dummy_llm(), shopping_agent=None, knowledge_agent=None)
        result = await graph.run(question="hi", conversation_id="c-rt")
        assert result["run_id"]
        assert result["trace_id"]
    asyncio.run(run())
