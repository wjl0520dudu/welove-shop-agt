"""rag.retriever 单测。

不打真 Milvus/DashScope；vector_store 走参数注入 mock。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rag.models import (
    ChunkMetadata,
    MetadataFilter,
    RetrievalOutput,
    RetrievalPlan,
    SearchResult,
    Source,
)
from rag.retriever import Retriever, build_knowledge_context, build_sources


class TestBuildSources:
    def test_builds_sources_from_results(self):
        results = [
            SearchResult(
                content="content A",
                metadata=ChunkMetadata(
                    doc_id=1, chunk_id=10, chunk_index=0,
                    title="Doc A", source="a.txt", page=3,
                ),
                score=0.95,
            ),
            SearchResult(
                content="content B",
                metadata=ChunkMetadata(
                    doc_id=2, chunk_id=20, chunk_index=1,
                    title="", source="b.txt", page=None,
                ),
                score=0.80,
            ),
        ]
        sources = build_sources(results)
        assert len(sources) == 2
        assert sources[0] == Source(doc_id=1, chunk_id=10, chunk_index=0, doc="Doc A", page=3, score=0.95)
        assert sources[1] == Source(doc_id=2, chunk_id=20, chunk_index=1, doc="b.txt", page=None, score=0.80)

    def test_deduplicates_by_doc_id_and_chunk_index(self):
        meta = ChunkMetadata(doc_id=1, chunk_index=0, title="T", source="s.txt")
        results = [
            SearchResult(content="c1", metadata=meta, score=0.9),
            SearchResult(content="c2", metadata=meta, score=0.8),
        ]
        assert len(build_sources(results)) == 1

    def test_empty_results(self):
        assert build_sources([]) == []


class TestBuildKnowledgeContext:
    def test_builds_formatted_context(self):
        results = [
            SearchResult(
                content="Hello world",
                metadata=ChunkMetadata(title="Doc1", source="d1.txt"),
                score=0.9,
            ),
            SearchResult(
                content="Goodbye",
                metadata=ChunkMetadata(title="", source="d2.txt"),
                score=0.7,
            ),
        ]
        ctx = build_knowledge_context(results)
        assert "[资料1]" in ctx and "Doc1" in ctx and "Hello world" in ctx
        assert "[资料2]" in ctx and "d2.txt" in ctx and "Goodbye" in ctx

    def test_empty_results(self):
        assert build_knowledge_context([]) == ""


class TestRetriever:
    """核心：vector_store 走注入 mock，不真连 Milvus，不需要 patch sys.modules。"""

    def test_init_with_provided_store(self):
        mock_store = MagicMock()
        r = Retriever(vector_store=mock_store)
        assert r.vector_store is mock_store

    def test_init_creates_store_when_none_provided(self, monkeypatch):
        """未注入 vector_store 时用 create_vector_store 兜底。"""
        mock_store = MagicMock()
        monkeypatch.setattr("rag.retriever.create_vector_store", lambda: mock_store)
        r = Retriever()
        assert r.vector_store is mock_store

    def test_retrieve_assembles_output(self):
        """带 filter 的 hybrid 检索：req.filter 应带上 plan 里的 category/doc_types/chunk_types。

        rerank 默认 True，len(results)==1 时不触发 rerank（走"未开 rerank"分支），
        直接返回。
        """
        mock_store = MagicMock()
        mock_store.search.return_value = [
            SearchResult(
                content="result content",
                metadata=ChunkMetadata(
                    doc_id=1, chunk_index=0, title="Test Doc", source="test.txt",
                ),
                score=0.88,
            ),
        ]
        r = Retriever(vector_store=mock_store)
        plan = RetrievalPlan(
            query="test query", top_k=3, category_id=5,
            doc_types=["faq"], chunk_types=["text"], search_mode="hybrid",
        )
        output = r.retrieve(plan)

        assert isinstance(output, RetrievalOutput)
        assert output.plan is plan
        assert len(output.results) == 1
        assert len(output.sources) == 1
        assert "result content" in output.knowledge_context

        # Retriever 走 store.search(request)（内部分派到 hybrid/dense/bm25）
        mock_store.search.assert_called_once()
        req = mock_store.search.call_args.args[0]
        assert req.query == "test query"
        assert req.search_mode == "hybrid"
        # rerank 开启时 recall_top_k 会 >= top_k（初始召回多召回一些）
        assert req.top_k >= 3
        # filter 从 plan 里 build 出来
        assert req.filter is not None
        assert req.filter.category_ids == [5]
        assert req.filter.doc_types == ["faq"]
        assert req.filter.chunk_types == ["text"]

    def test_retrieve_with_minimal_plan(self):
        """空 plan 也能跑；filter 里 category_ids/product_id 为 None，doc_types/chunk_types 空。"""
        mock_store = MagicMock()
        mock_store.search.return_value = []
        r = Retriever(vector_store=mock_store)

        output = r.retrieve(RetrievalPlan(query="数据库"))
        assert output.results == []
        assert output.sources == []
        assert output.knowledge_context == ""

        mock_store.search.assert_called_once()
        req = mock_store.search.call_args.args[0]
        # minimal plan：category_id / product_id 都是 None
        assert req.filter.category_ids is None
        assert req.filter.product_id is None
