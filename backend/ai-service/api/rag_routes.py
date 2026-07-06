from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from chains.rag_qa_chain import ask_with_rag
from rag.document_pipeline import DocumentIngestionService
from rag.models import ParseRequest, RetrievalPlan
from rag.retriever import get_retriever
from rag.vector_store import create_vector_store

router = APIRouter(prefix="/api/rag", tags=["rag"])

vector_store = create_vector_store()
ingestion_service = DocumentIngestionService(vector_store)


@router.post("/parse")
async def parse_document(request: ParseRequest) -> Dict[str, Any]:
    try:
        return ingestion_service.ingest(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"文档解析失败: {exc}") from exc


@router.post("/search")
async def search(plan: RetrievalPlan) -> Dict[str, Any]:
    output = get_retriever().retrieve(plan)
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


@router.post("/ask")
async def ask(plan: RetrievalPlan) -> Dict[str, Any]:
    return ask_with_rag(plan)


@router.get("/stats")
async def stats() -> Dict[str, Any]:
    return vector_store.stats()