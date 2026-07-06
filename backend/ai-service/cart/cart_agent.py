from __future__ import annotations

from typing import Optional
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from agents.memory import get_business_memory
from agents.prompts import CART_AGENT_PROMPT
from agents.response_parser import agent_state_to_result, error_result
from agents.runtime import agent_config, checkpointer, store
from agents.schemas import AgentRequestContext
from api.response_adapter import normalize_ai_response
from cart.java_client import CartJavaClient
from tools.cart_tools import build_cart_tools


class CartAgent:
    """LangGraph React agent for cart operations."""

    def __init__(self, llm=None, client: Optional[CartJavaClient] = None):
        self.llm = llm
        self.client = client or CartJavaClient()

    async def run(
        self,
        question: str,
        jwt_token: Optional[str],
        user_id: Optional[int] = None,
        run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        context: str = "",
        conversation_id: Optional[str] = None,
        confirmed: bool = False,
        cart_action: Optional[str] = None,
        product_id: Optional[int] = None,
        sku_id: Optional[int] = None,
        cart_item_id: Optional[int] = None,
        quantity: int = 1,
    ):
        run_id = run_id or str(uuid4())
        trace_id = trace_id or str(uuid4())
        if self.llm is None:
            return normalize_ai_response(
                error_result("LLM 未配置，购物车 Agent 暂不可用。", "AI_LLM_NOT_CONFIGURED", "cart"),
                run_id=run_id,
                trace_id=trace_id,
            )

        request_context = AgentRequestContext(
            question=question or "",
            context=context or "",
            conversation_id=conversation_id,
            user_id=user_id,
            jwt_token=jwt_token,
            confirmed=confirmed,
            cart_action=cart_action,
            product_id=product_id,
            sku_id=sku_id,
            cart_item_id=cart_item_id,
            quantity=max(quantity or 1, 1),
            business_memory=await get_business_memory(conversation_id, user_id),
        )
        tools = build_cart_tools(self.client, request_context)
        agent = create_react_agent(
            self.llm,
            tools,
            prompt=CART_AGENT_PROMPT,
            checkpointer=checkpointer,
            store=store,
            name="cart_agent",
        )
        state = await agent.ainvoke(
            {
                "messages": [
                    SystemMessage(content=self._context_message(request_context)),
                    HumanMessage(content=question or ""),
                ]
            },
            config=agent_config(conversation_id, user_id),
        )
        result = agent_state_to_result(state, default_task_type="cart")
        result["task_type"] = "cart"
        return normalize_ai_response(result, run_id=run_id, trace_id=trace_id)

    @staticmethod
    def _context_message(context: AgentRequestContext) -> str:
        return (
            "Request context for tools: "
            f"confirmed={context.confirmed}, cart_action={context.cart_action}, "
            f"product_id={context.product_id}, sku_id={context.sku_id}, "
            f"cart_item_id={context.cart_item_id}, quantity={context.quantity}. "
            f"Business memory: {context.business_memory}. "
            "Use conversation memory for previous product cards. Never reveal jwt_token. "
            f"External context: {context.context or ''}"
        )