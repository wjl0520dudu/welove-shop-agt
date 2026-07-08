"""测试 rag.reranker + rag.retriever 两阶段检索路径。

不打真 DashScope，用 mock 验证：
1. DashScopeReranker.rerank 正常路径解析 output.results
2. rerank 超时/HTTP 错/JSON 缺字段 → 退回原顺序（不抛异常）
3. Retriever.retrieve 走两阶段：召回 initial_top_k → rerank → 截 top_k
4. use_rerank=False 走单阶段直返
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx


# ---- Reranker 客户端 -----------------------------------------------------------

class TestDashScopeReranker:
    """DashScopeReranker.rerank：正常 + 各种异常的兜底。"""

    def _make(self):
        from rag.reranker import DashScopeReranker
        return DashScopeReranker(
            api_key="test-key",
            model="qwen3-rerank",
            endpoint="http://test/rerank",
            timeout=1.0,
        )

    def _mock_client(self, json_data, status_code=200, raise_timeout=False):
        """构造 httpx.Client() 上下文的 mock。"""
        mock_client = MagicMock()
        if raise_timeout:
            mock_client.__enter__.return_value.post.side_effect = httpx.TimeoutException("timeout")
            return mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data
        mock_resp.text = str(json_data)
        if status_code >= 400:
            def _raise():
                raise httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            mock_resp.raise_for_status.side_effect = _raise
        else:
            mock_resp.raise_for_status.return_value = None
        mock_client.__enter__.return_value.post.return_value = mock_resp
        return mock_client

    def test_normal_response_parsed_correctly(self):
        r = self._make()
        payload = {
            "output": {
                "results": [
                    {"index": 2, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.72},
                    {"index": 1, "relevance_score": 0.31},
                ]
            }
        }
        with patch("rag.reranker.httpx.Client", return_value=self._mock_client(payload)):
            pairs = r.rerank("query", ["a", "b", "c"], top_n=3)
        assert pairs == [(2, 0.95), (0, 0.72), (1, 0.31)]

    def test_timeout_returns_original_order(self):
        r = self._make()
        with patch("rag.reranker.httpx.Client", return_value=self._mock_client(None, raise_timeout=True)):
            pairs = r.rerank("query", ["a", "b", "c"])
        assert pairs == [(0, 0.0), (1, 0.0), (2, 0.0)]

    def test_http_5xx_returns_original_order(self):
        r = self._make()
        with patch("rag.reranker.httpx.Client", return_value=self._mock_client({"error": "x"}, status_code=500)):
            pairs = r.rerank("query", ["a", "b"])
        assert pairs == [(0, 0.0), (1, 0.0)]

    def test_missing_output_field_returns_original(self):
        r = self._make()
        with patch("rag.reranker.httpx.Client", return_value=self._mock_client({"unexpected": "shape"})):
            pairs = r.rerank("query", ["a", "b"])
        assert pairs == [(0, 0.0), (1, 0.0)]

    def test_empty_documents_returns_empty(self):
        r = self._make()
        assert r.rerank("query", []) == []

    def test_empty_query_returns_original(self):
        r = self._make()
        pairs = r.rerank("", ["a", "b"])
        assert pairs == [(0, 0.0), (1, 0.0)]


# ---- Retriever 两阶段 ---------------------------------------------------------

class TestRetrieverTwoStage:
    """Retriever.retrieve 的两阶段：召回 initial_top_k → rerank → top_k。"""

    def _make_result(self, doc_id, content, score):
        from rag.models import ChunkMetadata, SearchResult
        return SearchResult(
            content=content,
            metadata=ChunkMetadata(doc_id=doc_id, title="doc-" + str(doc_id)),
            score=score,
            dense_score=score,
        )

    def test_two_stage_recall_then_rerank(self):
        """开启 rerank：应先召回 initial_top_k=20，再 rerank 到 top_k=5。"""
        from rag.models import RetrievalPlan
        from rag.retriever import Retriever

        candidates = [self._make_result(i, "content-" + str(i), 0.5 - i * 0.01) for i in range(20)]
        store = MagicMock()
        store.search.return_value = candidates

        reranker = MagicMock()
        reranker.rerank.return_value = [
            (3, 0.99), (7, 0.87), (1, 0.75), (12, 0.63), (5, 0.51),
        ]

        r = Retriever(vector_store=store, reranker=reranker)
        out = r.retrieve(RetrievalPlan(query="x", top_k=5, use_rerank=True, initial_top_k=20))

        assert store.search.call_args.args[0].top_k == 20
        reranker.rerank.assert_called_once()
        assert reranker.rerank.call_args.kwargs["top_n"] == 5
        assert len(out.results) == 5
        assert [r.metadata.doc_id for r in out.results] == [3, 7, 1, 12, 5]
        assert out.results[0].score == 0.99
        assert out.results[0].rerank_score == 0.99

    def test_rerank_off_uses_recall_directly(self):
        """关闭 rerank：不召回超量，直接返回向量分数排序。"""
        from rag.models import RetrievalPlan
        from rag.retriever import Retriever

        candidates = [self._make_result(i, "c-" + str(i), 0.5 - i * 0.01) for i in range(5)]
        store = MagicMock()
        store.search.return_value = candidates
        reranker = MagicMock()

        r = Retriever(vector_store=store, reranker=reranker)
        out = r.retrieve(RetrievalPlan(query="x", top_k=5, use_rerank=False))

        assert store.search.call_args.args[0].top_k == 5
        reranker.rerank.assert_not_called()
        assert len(out.results) == 5

    def test_rerank_all_zero_scores_fallback_to_vector_order(self):
        """rerank 返回全 0（降级信号）：应退回向量分数排序。"""
        from rag.models import RetrievalPlan
        from rag.retriever import Retriever

        candidates = [
            self._make_result(0, "a", 0.9),
            self._make_result(1, "b", 0.5),
            self._make_result(2, "c", 0.7),
        ]
        store = MagicMock()
        store.search.return_value = candidates
        reranker = MagicMock()
        reranker.rerank.return_value = [(0, 0.0), (1, 0.0), (2, 0.0)]

        r = Retriever(vector_store=store, reranker=reranker)
        out = r.retrieve(RetrievalPlan(query="x", top_k=3, use_rerank=True, initial_top_k=3))

        # 按向量分数：0.9 > 0.7 > 0.5 → doc_id 0/2/1
        assert [r.metadata.doc_id for r in out.results] == [0, 2, 1]

    def test_initial_top_k_defaults_from_config(self):
        """未指定 initial_top_k 时走 config.RAG_INITIAL_TOP_K（默认 20）。"""
        from rag.models import RetrievalPlan
        from rag.retriever import Retriever

        candidates = [self._make_result(i, "c-" + str(i), 0.5) for i in range(20)]
        store = MagicMock()
        store.search.return_value = candidates
        reranker = MagicMock()
        reranker.rerank.return_value = [(0, 0.9)]

        r = Retriever(vector_store=store, reranker=reranker)
        r.retrieve(RetrievalPlan(query="x", top_k=5, use_rerank=True))

        assert store.search.call_args.args[0].top_k == 20


# ---- search_knowledge tool 层 -------------------------------------------------

class TestSearchKnowledgeToolRerank:
    def test_tool_passes_use_rerank_false(self):
        from knowledge.agent import search_knowledge
        with patch("knowledge.agent.get_retriever") as gr:
            fake_out = MagicMock()
            fake_out.knowledge_context = "ctx"
            fake_out.sources = []
            fake_out.results = []
            gr.return_value.retrieve.return_value = fake_out
            result = search_knowledge.invoke({"query": "x", "use_rerank": False})
        assert result["use_rerank"] is False
        plan = gr.return_value.retrieve.call_args.args[0]
        assert plan.use_rerank is False

    def test_tool_default_use_rerank_true(self):
        from knowledge.agent import search_knowledge
        with patch("knowledge.agent.get_retriever") as gr:
            fake_out = MagicMock()
            fake_out.knowledge_context = "ctx"
            fake_out.sources = []
            fake_out.results = []
            gr.return_value.retrieve.return_value = fake_out
            result = search_knowledge.invoke({"query": "x"})
        assert result["use_rerank"] is True
