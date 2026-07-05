from __future__ import annotations

import logging
import re
from typing import Literal

from langchain.agents import create_agent
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
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
5. 如果当前模型不支持结构化输出，只输出 JSON，不要输出 Markdown，不要输出解释文字。

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

SEARCH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是一个电商导购助手。
你需要根据用户的结构化导购意图，从商品库中搜索候选商品。
要求：
1. 只返回真实存在的商品，不要编造商品。
2. 如果没有找到合适商品，返回空列表。
""".strip(),
        ),
        (
            "human",
            """
用户问题：
{question}  
"""
        )]
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
        intent = self._normalize_intent(raw_intent, state["question"])
        return {**state, "intent": intent}

    def _normalize_intent(self, raw_intent, question: str) -> ShoppingIntent:
        """把 structured output、dict 或旧 JSON 文本统一成 ShoppingIntent。"""

        if isinstance(raw_intent, ShoppingIntent):
            return raw_intent

        if isinstance(raw_intent, dict):
            try:
                return ShoppingIntent(**raw_intent)
            except Exception:
                logger.exception("Intent dict validation failed, falling back to rule intent")
                return self._fallback_intent(question)

        return self._parse_intent_text(str(raw_intent), question)

    def _parse_intent_text(self, raw_intent: str, question: str) -> ShoppingIntent:
        """兼容旧模型输出 JSON 字符串的路径。"""

        if hasattr(ShoppingIntent, "model_validate_json"):
            try:
                return ShoppingIntent.model_validate_json(raw_intent)
            except Exception:
                pass

        try:
            import json

            data = json.loads(raw_intent)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", raw_intent)
            if not match:
                logger.warning("Intent JSON parse failed, falling back to rule intent: %s", raw_intent)
                return self._fallback_intent(question)
            try:
                import json

                data = json.loads(match.group(0))
            except Exception:
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
        checkpoint = state.get("memory_saver")

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

        intent = state.get("intent")
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
                reason=item.reason or self._fallback_reason(item, intent),
            )
            for item in state.get("candidates", [])[:3]
        ]

        try:
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

    @staticmethod
    def _fallback_reason(item, intent) -> str:
        if not intent:
            return "来自当前商品库的候选商品"

        reasons = []
        searchable_text = " ".join(
            [item.title or "", item.category or "", item.sub_category or "", item.tags or "", item.description or ""]
        )
        if intent.category and intent.category in searchable_text:
            reasons.append(f"匹配{intent.category}")
        if intent.budget_max is not None and item.price is not None and item.price <= intent.budget_max:
            reasons.append(f"符合{intent.budget_max:g}元以内预算")
        for preference in intent.preferences[:2]:
            if preference and preference in searchable_text:
                reasons.append(f"包含{preference}偏好")
        return "，".join(reasons) or "来自当前商品库的候选商品"


def shopping_state_to_result(state: ShoppingState) -> dict:
    """Convert internal LangGraph state to the stable API response adapter input."""

    product_cards = []
    for card in state.get("product_cards", []):
        product_cards.append(_dump_model(card))

    intent = state.get("intent")
    is_shopping_request = bool(intent and intent.is_shopping_request)

    return {
        "answer": state.get("answer", ""),
        "sources": [],
        "task_type": "shopping" if is_shopping_request or product_cards else "unknown",
        "product_cards": product_cards,
        "has_sources": False,
        "error": False,
    }
