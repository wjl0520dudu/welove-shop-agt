"""测试 rag.retriever / rag.vector_store 的三种检索模式路由。

**核心**：不连真 Milvus、不调 DashScope，用 mock 验证：
1. Retriever 拿到 plan.search_mode 后走到 vector_store.search
2. vector_store.search 按 mode 分派到 dense_search / bm25_search / hybrid_search
3. search_knowledge tool 的 search_mode 参数校验（防脏值）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---- Retriever 路径 -----------------------------------------------------------

class TestRetrieverRouting:
    """Retriever.retrieve 应把 plan.search_mode 透传到 vector_store.search，
    不再手工判断 hybrid_search 走哪个方法。"""

    def _make_retriever_with_mock_store(self):
        from rag.retriever import Retriever
        mock_store = MagicMock()
        mock_store.search.return_value = []  # 不关心结果，看它是否被调用
        return Retriever(vector_store=mock_store), mock_store

    def test_dense_mode_calls_search_with_dense(self):
        from rag.models import RetrievalPlan
        retriever, store = self._make_retriever_with_mock_store()
        retriever.retrieve(RetrievalPlan(query="补水精华", search_mode="dense"))
        store.search.assert_called_once()
        req = store.search.call_args.args[0]
        assert req.search_mode == "dense"
        assert req.query == "补水精华"

    def test_bm25_mode_calls_search_with_bm25(self):
        from rag.models import RetrievalPlan
        retriever, store = self._make_retriever_with_mock_store()
        retriever.retrieve(RetrievalPlan(query="视黄醇", search_mode="bm25"))
        store.search.assert_called_once()
        assert store.search.call_args.args[0].search_mode == "bm25"

    def test_hybrid_default(self):
        from rag.models import RetrievalPlan
        retriever, store = self._make_retriever_with_mock_store()
        retriever.retrieve(RetrievalPlan(query="烟酰胺功效"))  # 不指定 search_mode
        store.search.assert_called_once()
        # RetrievalPlan 默认 hybrid
        assert store.search.call_args.args[0].search_mode == "hybrid"


# ---- MilvusVectorStore.search 分派 -------------------------------------------

class TestVectorStoreSearchDispatch:
    """vector_store.search(request) 按 request.search_mode 分派到
    dense_search / bm25_search / hybrid_search。"""

    def _make_store_skipping_connect(self):
        """构造 MilvusVectorStore 但跳过真实的 _connect（不需要真 Milvus）。"""
        from rag.vector_store import MilvusVectorStore
        with patch.object(MilvusVectorStore, "_connect", lambda self: None), \
             patch("rag.vector_store.get_embeddings", return_value=MagicMock()):
            store = MilvusVectorStore(collection_name="__test__")
        return store

    def test_dense_dispatch(self):
        from rag.models import SearchRequest
        store = self._make_store_skipping_connect()
        store.dense_search = MagicMock(return_value=[])
        store.bm25_search = MagicMock(return_value=[])
        store.hybrid_search = MagicMock(return_value=[])

        store.search(SearchRequest(query="x", search_mode="dense"))
        store.dense_search.assert_called_once()
        store.bm25_search.assert_not_called()
        store.hybrid_search.assert_not_called()

    def test_bm25_dispatch(self):
        from rag.models import SearchRequest
        store = self._make_store_skipping_connect()
        store.dense_search = MagicMock(return_value=[])
        store.bm25_search = MagicMock(return_value=[])
        store.hybrid_search = MagicMock(return_value=[])

        store.search(SearchRequest(query="x", search_mode="bm25"))
        store.bm25_search.assert_called_once()
        store.dense_search.assert_not_called()
        store.hybrid_search.assert_not_called()

    def test_sparse_alias_dispatch_to_bm25(self):
        """search_mode='sparse' 也应走 bm25_search（历史别名兼容）。"""
        from rag.models import SearchRequest
        store = self._make_store_skipping_connect()
        store.dense_search = MagicMock(return_value=[])
        store.bm25_search = MagicMock(return_value=[])
        store.hybrid_search = MagicMock(return_value=[])

        store.search(SearchRequest(query="x", search_mode="sparse"))
        store.bm25_search.assert_called_once()

    def test_hybrid_dispatch(self):
        from rag.models import SearchRequest
        store = self._make_store_skipping_connect()
        store.dense_search = MagicMock(return_value=[])
        store.bm25_search = MagicMock(return_value=[])
        store.hybrid_search = MagicMock(return_value=[])

        store.search(SearchRequest(query="x", search_mode="hybrid"))
        store.hybrid_search.assert_called_once()

    def test_unknown_mode_falls_back_to_hybrid(self):
        """脏值（如 None、""、"foo"）都应兜底到 hybrid，绝不抛异常。"""
        from rag.models import SearchRequest
        store = self._make_store_skipping_connect()
        store.dense_search = MagicMock(return_value=[])
        store.bm25_search = MagicMock(return_value=[])
        store.hybrid_search = MagicMock(return_value=[])

        # Pydantic 校验会强制 str，所以传 "unknown"
        store.search(SearchRequest(query="x", search_mode="unknown"))
        store.hybrid_search.assert_called_once()


# ---- search_knowledge tool 校验 ----------------------------------------------

class TestSearchKnowledgeToolValidation:
    """search_knowledge 的 search_mode 参数应该：
    - 合法值原样透传
    - 非法值兜底 hybrid
    - 返回值带 search_mode 字段方便观测
    """

    def test_valid_mode_passthrough(self):
        from knowledge.agent import search_knowledge
        fake_output = MagicMock()
        fake_output.knowledge_context = "ctx"
        fake_output.sources = []
        fake_output.results = []
        with patch("knowledge.agent.get_retriever") as gr:
            gr.return_value.retrieve.return_value = fake_output
            result = search_knowledge.invoke({"query": "烟酰胺", "search_mode": "dense"})
        assert result["search_mode"] == "dense"

    def test_invalid_mode_falls_back_to_hybrid(self):
        from knowledge.agent import search_knowledge
        fake_output = MagicMock()
        fake_output.knowledge_context = "ctx"
        fake_output.sources = []
        fake_output.results = []
        with patch("knowledge.agent.get_retriever") as gr:
            gr.return_value.retrieve.return_value = fake_output
            result = search_knowledge.invoke({"query": "烟酰胺", "search_mode": "garbage-value"})
        assert result["search_mode"] == "hybrid"

    def test_default_mode_is_hybrid(self):
        from knowledge.agent import search_knowledge
        fake_output = MagicMock()
        fake_output.knowledge_context = "ctx"
        fake_output.sources = []
        fake_output.results = []
        with patch("knowledge.agent.get_retriever") as gr:
            gr.return_value.retrieve.return_value = fake_output
            result = search_knowledge.invoke({"query": "烟酰胺"})
        assert result["search_mode"] == "hybrid"
