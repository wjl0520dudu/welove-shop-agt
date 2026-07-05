from __future__ import annotations
from typing import Any, Dict


class KnowledgeAgent:
    """把 RAG 链包成 assistant 节点可用的 agent。

    ask_with_rag 延迟到调用时导入，避免模块加载期强依赖 pymilvus 等向量库。
    """

    async def ask(self, *, question: str, business_memory: Dict[str, Any]) -> dict:
        from chains.rag_qa_chain import ask_with_rag
        from rag.models import RetrievalPlan

        plan = RetrievalPlan(query=question, top_k=4, search_mode="hybrid")
        try:
            res = ask_with_rag(plan)  # 返回 {answer, sources, has_sources}
            return {
                "answer": res.get("answer", ""),
                "sources": res.get("sources", []),
                "task_type": "knowledge",
                "error": False,
            }
        except Exception as e:
            return {"answer": "知识检索暂时不可用。", "task_type": "knowledge",
                    "error": True, "error_code": "AI_RAG_ERROR", "message": str(e)}
