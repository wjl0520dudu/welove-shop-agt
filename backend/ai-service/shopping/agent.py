from __future__ import annotations

from typing import Optional
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage

from agents.memory import remember_product_cards
from agents.prompts import SHOPPING_AGENT_PROMPT
from agents.response_parser import agent_state_to_result, error_result
from agents.runtime import agent_config, checkpointer, store
from api.response_adapter import normalize_ai_response
from shopping.product_repository import ProductRepository
from tools.shopping_tools import build_shopping_tools


class ShoppingAgent:
    """LangChain tool-calling shopping agent."""

    def __init__(self, llm=None, repository: Optional[ProductRepository] = None):
        self.llm = llm
        self.repository = repository or ProductRepository()

    async def run(
        self,
        question: str,
        context: str = "",
        user_id: Optional[int] = None,
        conversation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ):
        run_id = run_id or str(uuid4())
        trace_id = trace_id or str(uuid4())
        if self.llm is None:
            return normalize_ai_response(
                error_result("LLM 未配置，导购 Agent 暂不可用。", "AI_LLM_NOT_CONFIGURED", "shopping"),
                run_id=run_id,
                trace_id=trace_id,
            )

        agent = create_agent(
            self.llm,
            tools=build_shopping_tools(self.repository, {"conversation_id": conversation_id, "user_id": user_id}),
            system_prompt=SHOPPING_AGENT_PROMPT,
            checkpointer=checkpointer,
            store=store,
            name="shopping_agent",
        )
        state = await agent.ainvoke(
            {
                "messages": [
                    SystemMessage(content=f"External context: {context or ''}"),
                    HumanMessage(content=question or ""),
                ]
            },
            config=agent_config(conversation_id, user_id),
        )
        result = agent_state_to_result(state, default_task_type="shopping")
        result["task_type"] = "shopping"
        remember_product_cards(conversation_id, user_id, result.get("product_cards") or [])
        return normalize_ai_response(result, run_id=run_id, trace_id=trace_id)