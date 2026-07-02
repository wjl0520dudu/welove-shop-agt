from __future__ import annotations

from typing import Any, Dict

from chains.knowledge_qa_chain import build_knowledge_qa_chain
from rag.retriever import Retriever
from rag.models import RetrievalPlan


def ask_with_rag(plan: RetrievalPlan, conversation_context: str = "", user_profile: str = "") -> Dict[str, Any]:
    retriever = Retriever()
    retrieval = retriever.retrieve(plan)

    if not retrieval.results:
        return {
            "answer": "抱歉，知识库中没有找到与您问题相关的内容。",
            "sources": [],
            "has_sources": False,
        }

    chain = build_knowledge_qa_chain()
    if chain is None:
        return {
            "answer": "知识库已命中相关资料，但当前 LLM 未配置，暂时无法生成完整回答。",
            "sources": [source.dict() for source in retrieval.sources],
            "has_sources": True,
        }

    answer = chain.invoke(
        {
            "question": plan.query,
            "knowledge_context": retrieval.knowledge_context,
            "conversation_context": conversation_context,
            "user_profile": user_profile,
        }
    )

    return {
        "answer": answer,
        "sources": [source.dict() for source in retrieval.sources],
        "has_sources": True,
    }

if __name__ == '__main__':
    # 测试示例
    plan = RetrievalPlan(
        query="数据库是什么？",
        top_k=3,
        search_mode="hybrid"
    )
    result = ask_with_rag(plan)
    print(result)