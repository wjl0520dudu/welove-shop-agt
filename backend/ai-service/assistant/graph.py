from __future__ import annotations

import json
import re
from typing import Literal, Optional, TypedDict
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from agents.memory import get_business_memory, remember_focused_product, remember_product_cards
from agents.prompts import PLAN_EXECUTE_PROMPT, ROUTER_PROMPT
from agents.response_parser import agent_state_to_result, error_result
from agents.runtime import agent_config, checkpointer, store
from agents.schemas import AgentRequestContext, IntentDecision
from cart.cart_agent import CartAgent
from cart.java_client import CartJavaClient
from cart.models import CartAction
from shopping.agent import ShoppingAgent
from shopping.product_repository import ProductRepository
from tools.cart_tools import build_cart_tools
from tools.shopping_tools import build_shopping_tools


RouteName = Literal["shopping", "cart", "knowledge", "chitchat", "unknown", "plan_execute"]


class AssistantState(TypedDict, total=False):
    question: str
    context: str
    conversation_id: Optional[str]
    user_id: Optional[int]
    jwt_token: Optional[str]
    run_id: str
    trace_id: str
    route: RouteName
    route_reason: str
    confirmed: bool
    cart_action: Optional[CartAction]
    product_id: Optional[int]
    sku_id: Optional[int]
    cart_item_id: Optional[int]
    quantity: int
    result: dict


class AssistantGraph:
    """Supervisor graph that routes to specialized LangChain agents."""

    def __init__(
        self,
        llm,
        repository: Optional[ProductRepository] = None,
        cart_agent: Optional[CartAgent] = None,
        shopping_agent: Optional[ShoppingAgent] = None,
        cart_client: Optional[CartJavaClient] = None,
    ):
        self.llm = llm
        self.repository = repository or ProductRepository()
        self.cart_client = cart_client or CartJavaClient()
        self.cart_agent = cart_agent or CartAgent(llm, self.cart_client)
        self.shopping_agent = shopping_agent or ShoppingAgent(llm, self.repository)
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(AssistantState)
        graph.add_node("route_intent", self._route_intent_node)
        graph.add_node("shopping", self._shopping_node)
        graph.add_node("cart", self._cart_node)
        graph.add_node("plan_execute", self._plan_execute_node)
        graph.add_node("knowledge", self._not_implemented_node)
        graph.add_node("chitchat", self._chitchat_node)
        graph.add_node("unknown", self._unknown_node)
        graph.add_edge(START, "route_intent")
        graph.add_conditional_edges(
            "route_intent",
            self._route_after_intent,
            {
                "shopping": "shopping",
                "cart": "cart",
                "plan_execute": "plan_execute",
                "knowledge": "knowledge",
                "chitchat": "chitchat",
                "unknown": "unknown",
            },
        )
        for node in ("shopping", "cart", "plan_execute", "knowledge", "chitchat", "unknown"):
            graph.add_edge(node, END)
        return graph.compile()

    async def run(self, **kwargs) -> dict:
        question = kwargs.get("question", "") or ""
        explicit_quantity = kwargs.get("quantity") or 1
        text_quantity = self._extract_quantity(question)
        state: AssistantState = {
            "question": question,
            "context": kwargs.get("context", "") or "",
            "conversation_id": kwargs.get("conversation_id"),
            "user_id": kwargs.get("user_id"),
            "jwt_token": kwargs.get("jwt_token"),
            "run_id": kwargs.get("run_id") or str(uuid4()),
            "trace_id": kwargs.get("trace_id") or str(uuid4()),
            "confirmed": bool(kwargs.get("confirmed", False)),
            "cart_action": kwargs.get("cart_action"),
            "product_id": kwargs.get("product_id"),
            "sku_id": kwargs.get("sku_id"),
            "cart_item_id": kwargs.get("cart_item_id"),
            "quantity": text_quantity or explicit_quantity,
        }
        final_state = await self.graph.ainvoke(state)
        result = final_state.get("result", {})
        result.setdefault("run_id", state["run_id"])
        result.setdefault("trace_id", state["trace_id"])
        return result

    async def _route_intent_node(self, state: AssistantState) -> AssistantState:
        if self.llm is None:
            return {**state, "route": "unknown", "result": error_result("LLM is not configured.", "AI_LLM_NOT_CONFIGURED", "unknown")}

        router = create_agent(
            self.llm,
            tools=[],
            system_prompt=self._router_prompt(),
            checkpointer=checkpointer,
            store=store,
            name="router_agent",
        )
        message = (
            f"Question: {state.get('question', '')}\n"
            f"Context: {state.get('context', '')}\n"
            f"Business memory: {json.dumps(get_business_memory(state.get('conversation_id'), state.get('user_id')), ensure_ascii=False)}\n"
            f"Explicit cart_action: {state.get('cart_action')}\n"
            f"confirmed: {state.get('confirmed')} product_id: {state.get('product_id')} quantity: {state.get('quantity')}"
        )
        router_state = await router.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config=agent_config(state.get("conversation_id"), state.get("user_id")),
        )
        decision = self._parse_router_decision(router_state)
        route = self._apply_route_guardrails(state, decision.task_type)
        return {**state, "route": route, "route_reason": decision.reason}

    @staticmethod
    def _router_prompt() -> str:
        return (
            ROUTER_PROMPT
            + "\nRequests like 'I want 2 of <product name>' or 'buy this/add this to cart after recommendation' are plan_execute."
            + "\nShort references like 'the second one' with product memory are shopping unless they include purchase/cart intent."
            + "\nReturn JSON text only, no markdown. Shape: "
            + '{"task_type":"shopping|cart|knowledge|chitchat|unknown|plan_execute","confidence":0.0,"reason":"short reason"}'
        )

    @staticmethod
    def _parse_router_decision(router_state: dict) -> IntentDecision:
        structured = router_state.get("structured_response")
        if isinstance(structured, IntentDecision):
            return structured
        if isinstance(structured, dict):
            try:
                return IntentDecision(**structured)
            except Exception:
                pass
        content = ""
        for message in reversed(router_state.get("messages") or []):
            if isinstance(message, AIMessage) or getattr(message, "type", None) == "ai":
                content = str(getattr(message, "content", "") or "")
                break
        data = AssistantGraph._extract_json(content)
        if data:
            try:
                return IntentDecision(**data)
            except Exception:
                pass
        return IntentDecision(task_type="unknown", confidence=0.0, reason="Router output was not valid JSON")

    @staticmethod
    def _extract_json(content: str) -> dict:
        text = (content or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _apply_route_guardrails(self, state: AssistantState, route: str) -> RouteName:
        memory = get_business_memory(state.get("conversation_id"), state.get("user_id"))
        if self._is_product_reference(state.get("question", "")) and memory.get("last_product_cards"):
            if self._is_purchase_request(state.get("question", "")):
                return "plan_execute"
            return "shopping"
        if self._is_purchase_request(state.get("question", "")) and self._extract_product_query(state.get("question", "")):
            return "plan_execute"
        if state.get("cart_action") and state.get("confirmed"):
            return "cart"
        if route in ("shopping", "cart", "knowledge", "chitchat", "plan_execute"):
            return route  # type: ignore[return-value]
        return "unknown"

    @staticmethod
    def _route_after_intent(state: AssistantState) -> RouteName:
        if state.get("result") and state.get("route") == "unknown":
            return "unknown"
        route = state.get("route") or "unknown"
        if route in ("shopping", "cart", "knowledge", "chitchat", "plan_execute"):
            return route
        return "unknown"

    async def _shopping_node(self, state: AssistantState) -> AssistantState:
        selected = self._select_product_from_memory(state)
        if selected:
            return {**state, "result": selected}

        response = await self.shopping_agent.run(
            question=state["question"],
            context=state.get("context", ""),
            user_id=state.get("user_id"),
            conversation_id=state.get("conversation_id"),
            run_id=state.get("run_id"),
            trace_id=state.get("trace_id"),
        )
        result = self._response_to_result(response)
        remember_product_cards(state.get("conversation_id"), state.get("user_id"), result.get("product_cards") or [])
        return {**state, "result": result}

    async def _cart_node(self, state: AssistantState) -> AssistantState:
        response = await self.cart_agent.run(
            question=state["question"],
            context=state.get("context", ""),
            conversation_id=state.get("conversation_id"),
            jwt_token=state.get("jwt_token"),
            user_id=state.get("user_id"),
            run_id=state.get("run_id"),
            trace_id=state.get("trace_id"),
            confirmed=state.get("confirmed", False),
            cart_action=state.get("cart_action"),
            product_id=state.get("product_id"),
            sku_id=state.get("sku_id"),
            cart_item_id=state.get("cart_item_id"),
            quantity=state.get("quantity", 1),
        )
        return {**state, "result": self._response_to_result(response)}

    async def _plan_execute_node(self, state: AssistantState) -> AssistantState:
        selected = self._select_product_from_memory(state)
        if selected and self._is_purchase_request(state.get("question", "")):
            state = {**state, "product_id": selected.get("product_cards", [{}])[0].get("product_id")}

        direct_result = await self._try_product_name_cart_flow(state)
        if direct_result is not None:
            return {**state, "result": direct_result}

        request_context = self._request_context(state)
        tools = [
            *build_shopping_tools(self.repository, {"conversation_id": state.get("conversation_id"), "user_id": state.get("user_id")}),
            *build_cart_tools(self.cart_client, request_context),
        ]
        agent = create_agent(self.llm, tools=tools, system_prompt=PLAN_EXECUTE_PROMPT, checkpointer=checkpointer, store=store, name="plan_execute_agent")
        agent_state = await agent.ainvoke(
            {"messages": [SystemMessage(content=self._context_message(state)), HumanMessage(content=state.get("question", ""))]},
            config=agent_config(state.get("conversation_id"), state.get("user_id")),
        )
        result = agent_state_to_result(agent_state, default_task_type="plan_execute")
        remember_product_cards(state.get("conversation_id"), state.get("user_id"), result.get("product_cards") or [])
        return {**state, "result": result}

    async def _try_product_name_cart_flow(self, state: AssistantState) -> Optional[dict]:
        if not self._is_purchase_request(state.get("question", "")):
            return None
        query = self._extract_product_query(state.get("question", ""))
        quantity = state.get("quantity", 1)
        memory_context = {"conversation_id": state.get("conversation_id"), "user_id": state.get("user_id")}
        shopping_tools = {tool.name: tool for tool in build_shopping_tools(self.repository, memory_context)}
        products = []
        if query:
            products = await shopping_tools["search_products_by_name"].ainvoke({"query": query, "limit": 5})

        if products:
            cards_payload = await shopping_tools["build_product_cards"].ainvoke({"products": products, "limit": min(len(products), 3)})
            cards = cards_payload.get("product_cards") or []
            if len(products) > 1 and not self._has_exact_match(query, products[0]):
                return {
                    "answer": "Multiple matching products were found. Please choose which one to add to cart.",
                    "task_type": "shopping",
                    "product_cards": cards,
                    "cart_selection": {"type": "cart_selection", "message": "Please choose the product to add to cart.", "items": cards},
                    "error": False,
                }
            product_id = products[0].get("product_id") or products[0].get("id")
        else:
            product_id = state.get("product_id")
            cards = []

        if not product_id:
            return {
                "answer": "No matching product was found. Please try another product name or choose from product cards.",
                "task_type": "shopping",
                "product_cards": [],
                "error": True,
                "error_code": "PRODUCT_NOT_FOUND",
                "message": "No matching product found.",
            }

        request_context = self._request_context({**state, "product_id": product_id, "quantity": quantity})
        cart_tools = {tool.name: tool for tool in build_cart_tools(self.cart_client, request_context)}
        if state.get("confirmed"):
            result = await cart_tools["execute_add_cart"].ainvoke({"product_id": product_id, "sku_id": state.get("sku_id"), "quantity": quantity})
        else:
            result = await cart_tools["prepare_add_cart"].ainvoke({"product_id": product_id, "sku_id": state.get("sku_id"), "quantity": quantity})
        if products:
            result.setdefault("product_cards", cards)
        return result

    def _request_context(self, state: AssistantState) -> AgentRequestContext:
        return AgentRequestContext(
            question=state.get("question", ""),
            context=state.get("context", ""),
            conversation_id=state.get("conversation_id"),
            user_id=state.get("user_id"),
            jwt_token=state.get("jwt_token"),
            confirmed=state.get("confirmed", False),
            cart_action=state.get("cart_action"),
            product_id=state.get("product_id"),
            sku_id=state.get("sku_id"),
            cart_item_id=state.get("cart_item_id"),
            quantity=state.get("quantity", 1),
            business_memory=get_business_memory(state.get("conversation_id"), state.get("user_id")),
        )

    def _select_product_from_memory(self, state: AssistantState) -> Optional[dict]:
        index = self._extract_product_index(state.get("question", ""))
        if index is None:
            return None
        memory = get_business_memory(state.get("conversation_id"), state.get("user_id"))
        cards = memory.get("last_product_cards") or []
        if not isinstance(cards, list) or not (0 <= index < len(cards)):
            return None
        product = cards[index]
        remember_product_cards(state.get("conversation_id"), state.get("user_id"), cards)
        remember_focused_product(state.get("conversation_id"), state.get("user_id"), product)
        return {
            "answer": "Selected the referenced product from previous recommendations.",
            "task_type": "shopping",
            "product_cards": [product],
            "error": False,
        }

    @staticmethod
    def _context_message(state: AssistantState) -> str:
        memory = get_business_memory(state.get("conversation_id"), state.get("user_id"))
        return f"External context: {state.get('context', '')}. Business memory: {json.dumps(memory, ensure_ascii=False)}. Never reveal jwt_token."

    async def _not_implemented_node(self, state: AssistantState) -> AssistantState:
        return {**state, "result": error_result("This agent capability has not been connected yet.", "AI_AGENT_NOT_IMPLEMENTED", state.get("route", "unknown"))}

    async def _chitchat_node(self, state: AssistantState) -> AssistantState:
        agent = create_agent(self.llm, tools=[], system_prompt="You are a concise helpful assistant. Use conversation memory.", checkpointer=checkpointer, store=store, name="chitchat_agent")
        agent_state = await agent.ainvoke({"messages": [HumanMessage(content=state.get("question", ""))]}, config=agent_config(state.get("conversation_id"), state.get("user_id")))
        return {**state, "result": agent_state_to_result(agent_state, default_task_type="chitchat")}

    async def _unknown_node(self, state: AssistantState) -> AssistantState:
        if state.get("result"):
            return state
        return {**state, "result": {"answer": "I can help with product shopping, cart operations, or questions. Please tell me what you need.", "task_type": "unknown", "error": False}}

    @staticmethod
    def _response_to_result(response) -> dict:
        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "dict"):
            return response.dict()
        return dict(response)

    @staticmethod
    def _extract_quantity(question: str) -> Optional[int]:
        match = re.search(r"(\d+)\s*(?:\u4e2a|\u4ef6|\u74f6|\u652f|\u76d2|\u4efd)?", question or "")
        if match:
            return max(int(match.group(1)), 1)
        return None

    @staticmethod
    def _is_purchase_request(question: str) -> bool:
        text = question or ""
        purchase_words = (
            "\u6211\u8981",
            "\u6211\u60f3\u8981",
            "\u4e70",
            "\u6765",
            "\u52a0\u8d2d",
            "\u52a0\u5165\u8d2d\u7269\u8f66",
            "\u52a0\u8d2d\u7269\u8f66",
            "\u4e0b\u5355",
            "\u5c31\u8981",
            "\u8981\u8fd9\u4e2a",
            "\u8fd9\u4e2a\u5427",
        )
        return any(word in text for word in purchase_words)

    @staticmethod
    def _is_product_reference(question: str) -> bool:
        text = question or ""
        reference_words = (
            "\u8fd9\u4e2a",
            "\u90a3\u4e2a",
            "\u521a\u624d\u90a3\u4e2a",
            "\u4e0a\u4e00\u4e2a",
            "\u4e0b\u4e00\u4e2a",
            "\u7b2c\u4e00\u4e2a",
            "\u7b2c\u4e8c\u4e2a",
            "\u7b2c\u4e09\u4e2a",
            "\u7b2c\u4e00\u6b3e",
            "\u7b2c\u4e8c\u6b3e",
            "\u7b2c\u4e09\u6b3e",
        )
        return any(word in text for word in reference_words) or re.search(r"\u7b2c\s*\d+\s*(?:\u4e2a|\u6b3e|\u4ef6)?", text) is not None

    @staticmethod
    def _extract_product_index(question: str) -> Optional[int]:
        text = question or ""
        digit_match = re.search(r"\u7b2c\s*(\d+)\s*(?:\u4e2a|\u6b3e|\u4ef6)?", text)
        if digit_match:
            return max(int(digit_match.group(1)) - 1, 0)
        ordinal_words = {
            "\u7b2c\u4e00\u4e2a": 0,
            "\u7b2c\u4e00\u6b3e": 0,
            "\u7b2c\u4e8c\u4e2a": 1,
            "\u7b2c\u4e8c\u6b3e": 1,
            "\u7b2c\u4e09\u4e2a": 2,
            "\u7b2c\u4e09\u6b3e": 2,
        }
        for word, index in ordinal_words.items():
            if word in text:
                return index
        if any(word in text for word in ("\u8fd9\u4e2a", "\u90a3\u4e2a", "\u521a\u624d\u90a3\u4e2a")):
            return 0
        return None

    @staticmethod
    def _extract_product_query(question: str) -> str:
        text = question or ""
        text = re.sub(r"\d+\s*(?:\u4e2a|\u4ef6|\u74f6|\u652f|\u76d2|\u4efd)?", "", text)
        remove_words = (
            "\u6211\u8981",
            "\u6211\u60f3\u8981",
            "\u5e2e\u6211",
            "\u4e70",
            "\u6765",
            "\u52a0\u8d2d",
            "\u52a0\u5165\u8d2d\u7269\u8f66",
            "\u52a0\u8d2d\u7269\u8f66",
            "\u4e0b\u5355",
            "\u5c31\u8981",
            "\u8981\u8fd9\u4e2a",
            "\u8fd9\u4e2a",
            "\u90a3\u4e2a",
            "\u5427",
        )
        for word in remove_words:
            text = text.replace(word, "")
        return text.strip(" \u3002\uff0c,.!\uff01")

    @staticmethod
    def _has_exact_match(query: str, product: dict) -> bool:
        title = product.get("title") or ""
        if not query or not title:
            return False
        return query in title or title in query