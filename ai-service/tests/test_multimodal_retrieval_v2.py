"""product_mm_v2 多模态检索的纯单元测试。

不连接真 Milvus，不调用真 DashScope；只验证 schema、融合排序和降级行为。
"""

from __future__ import annotations

import sys
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.infrastructure.retrieval.embeddings import _build_search_text_v2
from app.infrastructure.retrieval.multimodal_embeddings import DashScopeMultimodalEmbeddings
from app.domain.shopping.multimodal_search import recall_three_path_candidates, rrf_fusion, weighted_rerank
from app.infrastructure.vectorstores.product.vector_store_v2 import INSERT_FIELDS_V2, OUTPUT_FIELDS_V2, _build_fields_v2


class TestBuildSearchTextV2:
    def test_structured_labels_and_no_repeated_title(self):
        text = _build_search_text_v2({
            "title": "安热沙小金瓶防晒",
            "brand": "安热沙",
            "category": "美妆护肤",
            "sub_category": "防晒",
            "tags": "清爽, 防水",
            "description": "适合夏季通勤",
        })

        assert text.count("安热沙小金瓶防晒") == 1
        assert "[标题] 安热沙小金瓶防晒" in text
        assert "[品牌] 安热沙" in text
        assert "[子品类] 防晒" in text
        assert "\n" in text

    def test_missing_fields_skipped(self):
        assert _build_search_text_v2({"title": "A", "brand": ""}) == "[标题] A"
        assert _build_search_text_v2({}) == ""


class TestVectorStoreV2Schema:
    def test_schema_has_four_vector_fields(self):
        fields = _build_fields_v2(text_dim=1024, image_dim=2560, multimodal_dim=2560)
        names = [f.name for f in fields]
        assert "text_dense_vector" in names
        assert "text_sparse_vector" in names
        assert "image_vector" in names
        assert "multimodal_vector" in names

    def test_insert_and_output_fields(self):
        assert "text_sparse_vector" not in INSERT_FIELDS_V2
        assert "image_vector" in INSERT_FIELDS_V2
        assert "multimodal_vector" in INSERT_FIELDS_V2
        assert "image_vector" not in OUTPUT_FIELDS_V2
        assert "multimodal_vector" not in OUTPUT_FIELDS_V2


class TestFusionRanking:
    def test_rrf_fusion_dedupes_and_merges_scores(self):
        groups = [
            [
                {"product_id": 1, "score": 0.9, "dense_score": 0.9, "recall_sources": ["text_dense"]},
                {"product_id": 2, "score": 0.8, "dense_score": 0.8, "recall_sources": ["text_dense"]},
            ],
            [
                {"product_id": 2, "score": 12.0, "bm25_score": 12.0, "recall_sources": ["bm25"]},
                {"product_id": 1, "score": 0.7, "image_score": 0.7, "recall_sources": ["image"]},
            ],
        ]

        fused = rrf_fusion(groups, k=60)
        by_id = {item["product_id"]: item for item in fused}

        assert len(fused) == 2
        assert by_id[1]["dense_score"] == 0.9
        assert by_id[1]["image_score"] == 0.7
        assert set(by_id[1]["recall_sources"]) == {"text_dense", "image"}
        assert by_id[2]["bm25_score"] == 12.0
        assert "rrf_score" in by_id[1]
        assert fused[0]["score"] == fused[0]["rrf_score"]

    def test_weighted_rerank_uses_four_route_scores(self):
        candidates = [
            {"product_id": 1, "dense_score": 0.1, "bm25_score": 0.2, "image_score": 0.3, "multimodal_score": 0.4},
            {"product_id": 2, "dense_score": 1.0, "bm25_score": 0.0, "image_score": 0.0, "multimodal_score": 0.0},
        ]

        ranked = weighted_rerank(candidates, weights=(0.3, 0.2, 0.3, 0.2))

        assert ranked[0]["product_id"] == 2
        assert ranked[0]["weighted_score"] == 0.3
        assert "weighted_ranker" in ranked[0]["recall_sources"]

    def test_three_path_recall_selects_only_text_fields_without_image(self):
        store = MagicMock()
        store.dense_search.return_value = [
            {"product_id": 1, "score": 0.9, "recall_sources": ["text_dense"]},
        ]
        store.bm25_search.return_value = [
            {"product_id": 1, "score": 10.0, "recall_sources": ["bm25"]},
        ]

        out = recall_three_path_candidates(
            query_text="小棕瓶精华",
            top_k=5,
            store=store,
        )

        assert [item["product_id"] for item in out] == [1]
        assert set(out[0]["recall_sources"]) == {"text_dense", "bm25"}
        store.dense_search.assert_called_once()
        store.bm25_search.assert_called_once()
        assert not store.image_vector_search.called


class TestMultimodalRerank:
    def test_rerank_exception_falls_back_to_original_order(self):
        client = DashScopeMultimodalEmbeddings(
            api_key="test-key",
            rerank_model="qwen3-vl-rerank",
            base_url="",
        )
        docs = [
            {"product_id": 1, "title": "A", "image_url": "http://example.com/a.jpg"},
            {"product_id": 2, "title": "B", "image_url": "http://example.com/b.jpg"},
        ]

        with patch("app.infrastructure.retrieval.multimodal_embeddings.TextReRank.call", side_effect=RuntimeError("boom")):
            out = client.multimodal_rerank("query", "http://example.com/q.jpg", docs, top_n=1)

        assert out == [docs[0]]

    def test_rerank_success_maps_indices_back_to_documents(self):
        client = DashScopeMultimodalEmbeddings(api_key="test-key", base_url="")
        resp = MagicMock()
        resp.status_code = HTTPStatus.OK
        resp.output = {"results": [
            {"index": 1, "relevance_score": 0.99},
            {"index": 0, "relevance_score": 0.5},
        ]}
        docs = [
            {"product_id": 1, "title": "A", "recall_sources": ["bm25"]},
            {"product_id": 2, "title": "B", "recall_sources": ["image"]},
        ]

        with patch("app.infrastructure.retrieval.multimodal_embeddings.TextReRank.call", return_value=resp):
            out = client.multimodal_rerank("query", None, docs, top_n=2)

        assert [item["product_id"] for item in out] == [2, 1]
        assert out[0]["rerank_score"] == 0.99
        assert out[0]["score"] == 0.99
        assert "multimodal_rerank" in out[0]["recall_sources"]

    def test_image_embedding_service_error_returns_zero_vector(self):
        """服务性错误（网络异常、超时等）→ 降级零向量，不抛异常。"""
        client = DashScopeMultimodalEmbeddings(api_key="test-key", image_dim=3, base_url="")

        with patch("app.infrastructure.retrieval.multimodal_embeddings.MultiModalEmbedding.call", side_effect=RuntimeError("boom")):
            assert client.embed_image("http://example.com/a.jpg") == [0.0, 0.0, 0.0]

    def test_image_embedding_image_error_raises(self):
        """DashScope 返回 InvalidParameter 等图片错误 → 抛 MultimodalImageError。"""
        from app.infrastructure.retrieval.multimodal_embeddings import MultimodalImageError

        client = DashScopeMultimodalEmbeddings(api_key="test-key", image_dim=3, base_url="")

        # 模拟 DashScope 返回 InvalidParameter
        fake_resp = MagicMock()
        fake_resp.status_code = 400
        fake_resp.code = "InvalidParameter"
        fake_resp.message = "Image URL or Base64 is invalid"

        with patch("app.infrastructure.retrieval.multimodal_embeddings.MultiModalEmbedding.call", return_value=fake_resp):
            import pytest
            with pytest.raises(MultimodalImageError) as exc:
                client.embed_image("http://example.com/broken.jpg")
            assert exc.value.image_url == "http://example.com/broken.jpg"
            assert "InvalidParameter" in exc.value.reason

    def test_fusion_embedding_image_error_raises(self):
        """embed_fusion 同样对图片错误抛异常。"""
        from app.infrastructure.retrieval.multimodal_embeddings import MultimodalImageError

        client = DashScopeMultimodalEmbeddings(
            api_key="test-key", multimodal_dim=3, base_url="",
        )

        fake_resp = MagicMock()
        fake_resp.status_code = 400
        fake_resp.code = "InvalidURL"
        fake_resp.message = "invalid image url"

        with patch("app.infrastructure.retrieval.multimodal_embeddings.MultiModalEmbedding.call", return_value=fake_resp):
            import pytest
            with pytest.raises(MultimodalImageError):
                client.embed_fusion("text", "http://example.com/broken.jpg")


class TestSyncRows:
    def test_build_product_mm_v2_rows_uses_structured_text_and_vectors(self):
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import sync_products_to_milvus_v2 as sync_v2  # noqa: E402

        product = {
            "product_id": 42,
            "title": "跑鞋",
            "brand": "Nike",
            "category": "运动户外",
            "sub_category": "跑鞋",
            "image_url": "http://example.com/shoe.jpg",
            "description": "缓震",
            "tags": "透气",
            "base_price": 499,
            "status": 1,
        }
        emb = MagicMock()
        emb.embed_documents.return_value = [[0.1, 0.2]]
        mm = MagicMock()
        mm.embed_image.return_value = [0.3, 0.4, 0.5]
        mm.embed_fusion.return_value = [0.6, 0.7, 0.8]

        with patch.object(sync_v2, "get_embeddings", return_value=emb), \
             patch.object(sync_v2, "get_multimodal_embeddings", return_value=mm):
            rows = sync_v2.build_product_mm_v2_rows([product], sleep_seconds=0)

        row = rows[0]
        assert row["product_id"] == 42
        assert row["text"].startswith("[标题] 跑鞋")
        assert row["text_dense_vector"] == [0.1, 0.2]
        assert row["image_vector"] == [0.3, 0.4, 0.5]
        assert row["multimodal_vector"] == [0.6, 0.7, 0.8]

    def test_build_rows_downgrades_on_image_error(self):
        """同步脚本对 MultimodalImageError 降级零向量，不阻断批处理。"""
        from app.infrastructure.retrieval.multimodal_embeddings import MultimodalImageError

        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import sync_products_to_milvus_v2 as sync_v2  # noqa: E402

        products = [
            {
                "product_id": 1, "title": "A", "image_url": "http://ok.jpg",
                "description": "", "brand": "", "category": "", "sub_category": "",
                "tags": "", "base_price": 0, "status": 1,
            },
            {
                "product_id": 2, "title": "B", "image_url": "http://broken.jpg",
                "description": "", "brand": "", "category": "", "sub_category": "",
                "tags": "", "base_price": 0, "status": 1,
            },
        ]
        emb = MagicMock()
        emb.embed_documents.return_value = [[0.1], [0.2]]

        # 第二个商品 embed_image 抛异常，验证降级
        mm = MagicMock()
        mm.embed_image.side_effect = [
            [1.0, 1.0, 1.0],
            MultimodalImageError("http://broken.jpg", "InvalidParameter: 404"),
        ]
        mm.embed_fusion.side_effect = [
            [2.0, 2.0, 2.0],
            MultimodalImageError("http://broken.jpg", "InvalidParameter: 404"),
        ]

        with patch.object(sync_v2, "get_embeddings", return_value=emb), \
             patch.object(sync_v2, "get_multimodal_embeddings", return_value=mm), \
             patch.object(sync_v2, "zero_image_vector", return_value=[0.0, 0.0, 0.0]), \
             patch.object(sync_v2, "zero_multimodal_vector", return_value=[0.0, 0.0, 0.0]):
            rows = sync_v2.build_product_mm_v2_rows(products, sleep_seconds=0)

        # 第一个正常，第二个降级零向量，两条 row 都写出了
        assert len(rows) == 2
        assert rows[0]["image_vector"] == [1.0, 1.0, 1.0]
        assert rows[0]["multimodal_vector"] == [2.0, 2.0, 2.0]
        assert rows[1]["image_vector"] == [0.0, 0.0, 0.0]
        assert rows[1]["multimodal_vector"] == [0.0, 0.0, 0.0]
