from __future__ import annotations

import re
from typing import Any, Dict

from langchain_core.tools import tool

from rag.models import RetrievalPlan
from rag.retriever import get_retriever


@tool(
    name="analyze_query",
    description="分析用户问题，抽取意图、类目、预算、偏好等结构化条件，输出 RetrievalPlan。"
)
def analyze_query(question: str) -> Dict[str, Any]:
    """分析用户问题，抽取意图、类目、预算、偏好等结构化条件。"""
    category_keywords = ["防晒", "面霜", "精华", "耳机", "手机", "跑鞋", "零食", "饮料"]
    skin_keywords = ["油皮", "干皮", "敏感肌", "混油", "混干"]
    season_keywords = ["春天", "夏天", "秋天", "冬天"]
    shopping_keywords = ["买", "推荐", "适合", "预算", "以内", "哪款", "哪个好"]

    budget_min = None
    budget_max = None
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|到|至)\s*(\d+(?:\.\d+)?)", question)
    if range_match:
        budget_min = float(range_match.group(1))
        budget_max = float(range_match.group(2))
    else:
        max_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?(?:以内|以下|内)", question)
        if max_match:
            budget_max = float(max_match.group(1))

    negative_requirements = re.findall(r"(?:不要|不想要|避免)([^，。,.；;]+)", question)
    positive_requirements = [
        word
        for word in ["清爽", "保湿", "便携", "大容量", "降噪", "轻便", "抗老", "控油"]
        if word in question
    ]

    plan = RetrievalPlan(
        intent="shopping" if any(word in question for word in shopping_keywords) else "knowledge_qa",
        query=question,
        search_targets=["knowledge"],
        category=next((word for word in category_keywords if word in question), None),
        budget_min=budget_min,
        budget_max=budget_max,
        skin_type=next((word for word in skin_keywords if word in question), None),
        season=next((word for word in season_keywords if word in question), None),
        positive_requirements=positive_requirements,
        negative_requirements=[item.strip() for item in negative_requirements if item.strip()],
        top_k=5,
        search_mode="dense",
    )
    if hasattr(plan, "model_dump"):
        return plan.model_dump(exclude_none=True)
    return plan.dict(exclude_none=True)


@tool(
    name="knowledge_search",
    description="根据 RetrievalPlan 检索知识库，返回文档片段、sources 和 knowledge_context。"
)
def knowledge_search(plan: Dict[str, Any]) -> Dict[str, Any]:
    """根据 RetrievalPlan 检索知识库，返回文档片段、sources 和 knowledge_context。"""
    retrieval_plan = RetrievalPlan(**plan)
    output = get_retriever().retrieve(retrieval_plan)
    return {
        "documents": [
            {
                "content": item.content,
                "score": item.score,
                "metadata": item.metadata.dict(),
            }
            for item in output.results
        ],
        "sources": [source.dict() for source in output.sources],
        "knowledge_context": output.knowledge_context,
        "count": len(output.results),
    }


RAG_TOOLS = [analyze_query, knowledge_search]
