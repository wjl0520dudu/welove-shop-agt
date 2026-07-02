from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from rag import retriever
from rag.models import RetrievalPlan


@tool(
    name="analyze_query",
    description="分析用户问题，抽取意图、类目、预算、偏好等结构化条件，输出 RetrievalPlan。"
)
def analyze_query(question: str) -> Dict[str, Any]:
    """分析用户问题，抽取意图、类目、预算、偏好等结构化条件。"""
    # TODO:
    # 1. 第一版可以先用规则匹配
    # 2. 第二版用 LLM 输出 JSON
    # 3. 注意不要让 LLM 直接生成 Milvus expr
    return {
        "intent": "knowledge_qa",
        "query": question,
        "search_targets": ["knowledge"],
        "top_k": 5,
        "search_mode": "dense",
    }


@tool(
    name="knowledge_search",
    description="根据 RetrievalPlan 检索知识库，返回文档片段、sources 和 knowledge_context。"
)
def knowledge_search(plan: Dict[str, Any]) -> Dict[str, Any]:
    """根据 RetrievalPlan 检索知识库，返回文档片段、sources 和 knowledge_context。"""
    retrieval_plan = RetrievalPlan(**plan)
    output = retriever.retrieve(retrieval_plan)
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