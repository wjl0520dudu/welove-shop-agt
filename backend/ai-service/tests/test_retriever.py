# Test file for rag/retriever.py
import sys
from unittest.mock import MagicMock

sys.modules["pymilvus"] = MagicMock()
from rag.vector_store import build_metadata_filter as _real_build_metadata_filter

class _FakeVectorStoreModule:
    build_metadata_filter = _real_build_metadata_filter
    create_vector_store = MagicMock()

sys.modules["rag.vector_store"] = _FakeVectorStoreModule()

from rag.retriever import build_sources, build_knowledge_context, Retriever
from rag.models import (
    ChunkMetadata, RetrievalPlan, RetrievalOutput, SearchResult, Source, MetadataFilter,
)

import pytest


class TestBuildSources:
    def test_builds_sources_from_results(self):
        results = [
            SearchResult(content="content A",
                metadata=ChunkMetadata(doc_id=1, chunk_id=10, chunk_index=0, title="Doc A", source="a.txt", page=3),
                score=0.95),
            SearchResult(content="content B",
                metadata=ChunkMetadata(doc_id=2, chunk_id=20, chunk_index=1, title="", source="b.txt", page=None),
                score=0.80),
        ]
        sources = build_sources(results)
        assert len(sources) == 2
        assert sources[0] == Source(doc_id=1, chunk_id=10, chunk_index=0, doc="Doc A", page=3, score=0.95)
        assert sources[1] == Source(doc_id=2, chunk_id=20, chunk_index=1, doc="b.txt", page=None, score=0.80)

    def test_deduplicates_by_doc_id_and_chunk_index(self):
        meta = ChunkMetadata(doc_id=1, chunk_index=0, title="T", source="s.txt")
        results = [SearchResult(content="c1", metadata=meta, score=0.9),
                   SearchResult(content="c2", metadata=meta, score=0.8)]
        assert len(build_sources(results)) == 1

    def test_empty_results(self):
        assert build_sources([]) == []


class TestBuildKnowledgeContext:
    def test_builds_formatted_context(self):
        results = [
            SearchResult(content="Hello world", metadata=ChunkMetadata(title="Doc1", source="d1.txt"), score=0.9),
            SearchResult(content="Goodbye", metadata=ChunkMetadata(title="", source="d2.txt"), score=0.7),
        ]
        ctx = build_knowledge_context(results)
        assert "[zi liao 1]" in ctx and "Doc1" in ctx and "Hello world" in ctx
        assert "[zi liao 2]" in ctx and "d2.txt" in ctx and "Goodbye" in ctx

    def test_empty_results(self):
        assert build_knowledge_context([]) == ""


class TestRetriever:
    def test_init_with_provided_store(self):
        mock_store = MagicMock()
        r = Retriever(vector_store=mock_store)
        assert r.vector_store is mock_store

    def test_init_creates_store_when_none_provided(self):
        mock_store = MagicMock()
        _FakeVectorStoreModule.create_vector_store.return_value = mock_store
        r = Retriever()
        assert r.vector_store is mock_store

    def test_retrieve_assembles_output(self):
        mock_store = MagicMock()
        mock_store.hybrid_search.return_value = [
            SearchResult(content="result content",
                metadata=ChunkMetadata(doc_id=1, chunk_index=0, title="Test Doc", source="test.txt"),
                score=0.88),
        ]
        r = Retriever(vector_store=mock_store)
        plan = RetrievalPlan(query="test query", top_k=3, category_id=5,
                             doc_types=["faq"], chunk_types=["text"], search_mode="hybrid")
        output = r.retrieve(plan)
        assert isinstance(output, RetrievalOutput)
        assert output.plan is plan
        assert len(output.results) == 1 and len(output.sources) == 1
        assert "result content" in output.knowledge_context
        mock_store.hybrid_search.assert_called_once()
        req = mock_store.hybrid_search.call_args[0][0]
        assert req.query == "test query" and req.top_k == 3 and req.search_mode == "hybrid"
        assert req.filter is not None
        assert req.filter.category_ids == [5]
        assert req.filter.doc_types == ["faq"]
        assert req.filter.chunk_types == ["text"]

    def test_retrieve_with_minimal_plan(self):
        mock_store = MagicMock()
        mock_store.hybrid_search.return_value = []
        r = Retriever(vector_store=mock_store)
        output = r.retrieve(RetrievalPlan(query="数据库"))
        assert output.results == [] and output.sources == [] and output.knowledge_context == ""
        req = mock_store.hybrid_search.call_args[0][0]
        assert req.filter.category_ids is None and req.filter.product_id is None
