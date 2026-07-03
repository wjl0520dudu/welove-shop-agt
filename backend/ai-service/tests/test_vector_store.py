import os

import pytest

from rag.models import ChunkMetadata, DocumentChunk, SearchRequest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MILVUS_TESTS") != "1",
    reason="Milvus integration test requires RUN_MILVUS_TESTS=1, OPENAI_API_KEY, and MILVUS_URL.",
)


def test_milvus_vector_store_round_trip():
    from rag.vector_store import MilvusVectorStore

    store = MilvusVectorStore(collection_name=os.getenv("MILVUS_COLLECTION", "test_hybrid"))
    chunks = [
        DocumentChunk(
            content="Milvus 是一个高性能向量数据库",
            metadata=ChunkMetadata(
                doc_id=1,
                doc_type="guide",
                chunk_type="text",
                category_id=10,
                source="milvus_intro.md",
                title="Milvus 简介",
                chunk_index=0,
            ),
        ),
        DocumentChunk(
            content="LangChain 提供了统一的 Embedding 接口",
            metadata=ChunkMetadata(
                doc_id=2,
                doc_type="faq",
                chunk_type="text",
                category_id=20,
                source="langchain.md",
                title="LangChain Embedding",
                chunk_index=0,
            ),
        ),
    ]

    inserted = store.upsert_chunks(chunks)
    assert inserted == 2

    results = store.search(SearchRequest(query="向量数据库", top_k=3))
    assert len(results) > 0

    deleted = store.delete_by_doc_id(1)
    assert deleted >= 0

    stats = store.stats()
    assert stats["provider"] == "milvus"
