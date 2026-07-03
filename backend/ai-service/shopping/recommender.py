from __future__ import annotations

import json
import logging
import re
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

from shopping.models import ProductCard, ShoppingIntent, ShoppingState
from shopping.product_repository import ProductRepository

logger = logging.getLogger("ai-service.shopping")


def _dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    if hasattr(model, "dict"):
        return model.dict(exclude_none=True)
    return dict(model)


INTENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是一个电商导购需求理解助手。
你的任务是把用户自然语言解析成结构化导购意图。

要求：
1. 只提取用户明确表达或强烈暗示的信息。
2. 不要编造品牌、预算、品类。
3. 如果信息不足但仍可推荐，need_followup=false。
4. 只有完全不知道用户想买什么时，need_followup=true。
5. 只输出 JSON，不要输出 Markdown，不要输出解释文字。

JSON 字段：
{{
  "is_shopping_request": true,
  "category": null,
  "brand": null,
  "budget_min": null,
  "budget_max": null,
  "target_user": null,
  "scenario": null,
  "preferences": [],
  "avoid": [],
  "compare_mode": false,
  "need_followup": false,
  "followup_question": null
}}
""".strip(),
        ),
        (
            "human",
            """
用户问题：
{question}

对话上下文：
{context}

用户画像：
{profile}
""".strip(),
        ),
    ]
)


ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是一个专业、克制、可信的电商导购助手。
你只能基于给定候选商品进行推荐，不允许编造商品、价格、销量、评分。

输出要求：
1. 先用一句话概括推荐思路。
2. 推荐 2-3 个商品，并说明各自适合谁。
3. 如果候选商品信息不足，要明确说“从当前商品信息看”。
4. 不要输出不存在的商品 ID。
""".strip(),
        ),
        (
            "human",
            """
用户问题：
{question}

结构化需求：
{intent}

候选商品：
{candidates}

请生成导购推荐话术。
""".strip(),
        ),
    ]
)


FALLBACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是电商导购助手。当前没有查到合适商品，请给出自然的追问或兜底建议，不要编造商品。",
        ),
        ("human", "{question}"),
    ]
)


class ShoppingRecommender:
    """LangGraph 版导购推荐主链路。"""

    def __init__(self, llm, repository: ProductRepository):
        self.llm = llm
        self.repository = repository
        self.intent_chain: Runnable = INTENT_PROMPT | llm | StrOutputParser()
        self.answer_chain: Runnable = ANSWER_PROMPT | llm
        self.fallback_chain: Runnable = FALLBACK_PROMPT | llm
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(ShoppingState)

        graph.add_node("analyze_query", self._analyze_query)
        graph.add_node("search_products", self._search_products)
        graph.add_node("generate_answer", self._generate_answer)
        graph.add_node("generate_fallback", self._generate_fallback)
        graph.add_node("build_response", self._build_response)

        graph.add_edge(START, "analyze_query")
        graph.add_conditional_edges(
            "analyze_query",
            self._route_after_analyze,
            {
                "search": "search_products",
                "fallback": "generate_fallback",
            },
        )
        graph.add_conditional_edges(
            "search_products",
            self._route_after_search,
            {
                "answer": "generate_answer",
                "fallback": "generate_fallback",
            },
        )
        graph.add_edge("generate_answer", "build_response")
        graph.add_edge("generate_fallback", "build_response")
        graph.add_edge("build_response", END)

        return graph.compile()

    async def recommend(
        self,
        question: str,
        user_id: int | None = None,
        session_id: str | None = None,
        context: str | None = None,
        profile: dict | None = None,
    ) -> ShoppingState:
        """对外入口：输入用户问题，返回导购状态。"""

        initial_state: ShoppingState = {
            "question": question,
            "context": context or "",
            "user_id": user_id,
            "session_id": session_id,
            "profile": profile or {},
        }
        return await self.graph.ainvoke(initial_state)

    async def _analyze_query(self, state: ShoppingState) -> ShoppingState:
        """LLM 结构化解析用户需求。"""

        raw_intent = await self.intent_chain.ainvoke(
            {
                "question": state["question"],
                "context": state.get("context", ""),
                "profile": state.get("profile", {}),
            }
        )
        intent = self._parse_intent(raw_intent, state["question"])
        return {**state, "intent": intent}

    def _parse_intent(self, raw_intent: str, question: str) -> ShoppingIntent:
        """Parse model JSON output locally instead of using OpenAI parse API."""

        try:
            data = json.loads(raw_intent)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", raw_intent)
            if not match:
                logger.warning("Intent JSON parse failed, falling back to rule intent: %s", raw_intent)
                return self._fallback_intent(question)
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("Intent JSON block parse failed, falling back to rule intent: %s", raw_intent)
                return self._fallback_intent(question)

        try:
            return ShoppingIntent(**data)
        except Exception:
            logger.exception("Intent schema validation failed, falling back to rule intent")
            return self._fallback_intent(question)

    @staticmethod
    def _fallback_intent(question: str) -> ShoppingIntent:
        shopping_words = ("买", "推荐", "适合", "预算", "以内", "哪款", "哪个好", "导购")
        categories = ("防晒", "面霜", "精华", "耳机", "手机", "跑鞋", "零食", "饮料")
        preferences = [word for word in ("清爽", "保湿", "便携", "大容量", "降噪", "轻便", "控油") if word in question]

        budget_max = None
        max_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?(?:以内|以下|内)", question)
        if max_match:
            budget_max = float(max_match.group(1))

        avoid = []
        avoid_match = re.search(r"(?:不要|不想要|避免)([^，。,.；;]+)", question)
        if avoid_match:
            avoid.append(avoid_match.group(1).strip())

        category = next((word for word in categories if word in question), None)
        is_shopping = bool(category or any(word in question for word in shopping_words))
        return ShoppingIntent(
            is_shopping_request=is_shopping,
            category=category,
            budget_max=budget_max,
            preferences=preferences,
            avoid=avoid,
            need_followup=not is_shopping,
            followup_question="你想看哪一类商品？可以告诉我品类、预算或使用场景。",
        )

    def _route_after_analyze(self, state: ShoppingState) -> Literal["search", "fallback"]:
        """根据结构化意图决定是否进入商品搜索。"""

        intent = state["intent"]

        if not intent.is_shopping_request:
            return "fallback"

        if intent.need_followup and not intent.category:
            return "fallback"

        return "search"

    async def _search_products(self, state: ShoppingState) -> ShoppingState:
        """查询真实商品候选。"""

        candidates = await self.repository.search_products(state["intent"])
        return {**state, "candidates": candidates}

    def _route_after_search(self, state: ShoppingState) -> Literal["answer", "fallback"]:
        """有商品则生成推荐话术，没有商品则兜底。"""

        if state.get("candidates"):
            return "answer"
        return "fallback"

    async def _generate_answer(self, state: ShoppingState) -> ShoppingState:
        """LLM 基于真实商品生成推荐话术。"""

        response = await self.answer_chain.ainvoke(
            {
                "question": state["question"],
                "intent": _dump_model(state["intent"]),
                "candidates": [_dump_model(item) for item in state.get("candidates", [])],
            }
        )

        answer = getattr(response, "content", str(response))
        return {**state, "answer": answer}

    async def _generate_fallback(self, state: ShoppingState) -> ShoppingState:
        """没有足够信息或没有商品时的兜底回复。"""

        intent = state.get("intent")
        if intent and intent.followup_question:
            return {**state, "answer": intent.followup_question}

        response = await self.fallback_chain.ainvoke({"question": state["question"]})
        answer = getattr(response, "content", str(response))
        return {**state, "answer": answer}

    async def _build_response(self, state: ShoppingState) -> ShoppingState:
        """构造前端可用的商品卡片，并记录日志。"""

        product_cards = [
            ProductCard(
                product_id=item.product_id,
                title=item.title,
                brand=item.brand or "",
                price=item.price or 0,
                image_url=item.image_url or "",
                rating=item.rating or 0,
                review_count=item.review_count or 0,
                sales_count=item.sales_count or 0,
                sub_category=item.sub_category or "",
                reason=item.reason or "",
            )
            for item in state.get("candidates", [])[:3]
        ]

        try:
            intent = state.get("intent")
            await self.repository.log_recommendation(
                user_id=state.get("user_id"),
                session_id=state.get("session_id"),
                question=state["question"],
                product_ids=[card.product_id for card in product_cards],
                intent="shopping" if intent and intent.is_shopping_request else "unknown",
                recommend_reason=state.get("answer"),
            )
        except Exception:
            logger.exception("Recommendation log failed; continuing response flow")

        return {**state, "product_cards": product_cards}


def shopping_state_to_result(state: ShoppingState) -> dict:
    """Convert internal LangGraph state to the stable API response adapter input."""

    product_cards = []
    for card in state.get("product_cards", []):
        product_cards.append(_dump_model(card))

    return {
        "answer": state.get("answer", ""),
        "sources": [],
        "task_type": "shopping" if product_cards else "unknown",
        "product_cards": product_cards,
        "has_sources": False,
        "error": False,
    }
