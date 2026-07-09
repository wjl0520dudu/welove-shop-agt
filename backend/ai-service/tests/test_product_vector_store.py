"""ProductMilvusStore 的 mock 单测（不打真 Milvus/DashScope）。

- schema 构建 / INSERT_FIELDS / OUTPUT_FIELDS 一致性
- build_milvus_filter_expr 各字段翻译
- _hit_to_dict 结果 shape
- _build_search_text 拼接顺序
"""

from __future__ import annotations

from unittest.mock import MagicMock

from shopping.vector_store import (
    INSERT_FIELDS,
    OUTPUT_FIELDS,
    ProductMilvusStore,
    _build_search_text,
    _build_fields,
    build_milvus_filter_expr,
)


class TestBuildFields:
    def test_schema_has_three_vector_fields(self):
        fields = _build_fields(text_dim=1024, multimodal_dim=1024)
        names = [f.name for f in fields]
        assert "text_dense_vector" in names
        assert "text_sparse_vector" in names
        assert "multimodal_vector" in names

    def test_primary_is_product_id(self):
        fields = _build_fields(text_dim=1024, multimodal_dim=1024)
        pk = next(f for f in fields if f.is_primary)
        assert pk.name == "product_id"

    def test_display_fields_present(self):
        """展示 + 过滤字段都应该有，避免推荐时回 PG。"""
        fields = _build_fields(text_dim=1024, multimodal_dim=1024)
        names = {f.name for f in fields}
        for expected in ("title", "brand", "image_url", "description", "base_price",
                         "category", "sub_category", "tags", "rating", "sales_count",
                         "review_count", "status"):
            assert expected in names, f"missing field {expected}"


class TestInsertAndOutputFieldsConsistent:
    def test_insert_fields_no_sparse(self):
        """text_sparse_vector 由 BM25 Function 生成，不能在 INSERT_FIELDS 里。"""
        assert "text_sparse_vector" not in INSERT_FIELDS

    def test_insert_includes_multimodal(self):
        """multimodal_vector MVP 灌零向量占位，必须在 INSERT_FIELDS 里。"""
        assert "multimodal_vector" in INSERT_FIELDS

    def test_output_fields_no_vectors(self):
        """检索 output 不需要向量本身，节省网络。"""
        assert "text_dense_vector" not in OUTPUT_FIELDS
        assert "text_sparse_vector" not in OUTPUT_FIELDS
        assert "multimodal_vector" not in OUTPUT_FIELDS


class TestBuildMilvusFilterExpr:
    def test_none_returns_status_default(self):
        """空 filters 默认加 status==1。"""
        assert build_milvus_filter_expr(None) == "status == 1"

    def test_category_and_price(self):
        expr = build_milvus_filter_expr({"category": "防晒", "budget_max": 200})
        # category 走两级 OR 匹配（顶级或子类都算命中）
        assert '(category == "防晒" || sub_category == "防晒")' in expr
        assert "base_price <= 200.0" in expr
        assert "status == 1" in expr

    def test_product_id_single(self):
        expr = build_milvus_filter_expr({"product_id": 42})
        assert "product_id == 42" in expr

    def test_product_ids_list(self):
        expr = build_milvus_filter_expr({"product_ids": [1, 2, 3]})
        assert "product_id in [1, 2, 3]" in expr

    def test_min_rating(self):
        expr = build_milvus_filter_expr({"min_rating": 4.5})
        assert "rating >= 4.5" in expr

    def test_status_explicit_overrides_default(self):
        """显式传 status=None 时不加默认。"""
        expr = build_milvus_filter_expr({"status": None})
        # 只剩空
        assert expr is None or "status" not in expr

    def test_brand_string_escape(self):
        """品牌名带引号时应转义，避免语法错误。"""
        expr = build_milvus_filter_expr({"brand": 'a"b'})
        assert '\\"' in expr

    def test_sub_category_precise_match(self):
        """只传 sub_category 时走精确匹配（不带 category 的 OR 括号形式）。"""
        expr = build_milvus_filter_expr({"sub_category": "防晒"})
        assert 'sub_category == "防晒"' in expr
        # 只传 sub_category 时，不会出现顶级 category 的 OR 括号（那是 filter["category"] 触发的）
        assert '(category == ' not in expr

    def test_category_or_matches_both_levels(self):
        """category filter 覆盖顶级和子类目两个字段。"""
        expr = build_milvus_filter_expr({"category": "美妆护肤"})
        # 顶级类目"美妆护肤"存在 → 命中 category == "美妆护肤"
        # 子类目"美妆护肤"不存在 → OR 里另一路空转
        # 但表达式必须两个都写，才能兼容"防晒"这种子类目 case
        assert '(category == "美妆护肤" || sub_category == "美妆护肤")' in expr

    def test_budget_range(self):
        expr = build_milvus_filter_expr({"budget_min": 100, "budget_max": 300})
        assert "base_price >= 100.0" in expr
        assert "base_price <= 300.0" in expr


class TestBuildSearchText:
    def test_concat_with_title_repeated(self):
        text = _build_search_text({
            "title": "SPF50 防晒",
            "brand": "Anessa",
            "category": "防晒",
            "sub_category": "面部防晒",
            "tags": "清爽 不黏",
            "description": "适合油皮夏季使用",
        })
        # title 出现两次（BM25 权重）
        assert text.count("SPF50 防晒") == 2
        assert "Anessa" in text
        assert "面部防晒" in text
        assert "适合油皮夏季使用" in text

    def test_missing_fields_skipped(self):
        text = _build_search_text({"title": "A"})
        assert text == "A A"

    def test_all_empty(self):
        assert _build_search_text({}) == ""


# ---- _hit_to_dict shape --------------------------------------------------

class TestHitToDict:
    def _make_hit(self, entity_dict, distance=0.8):
        hit = MagicMock()
        entity = MagicMock()
        entity.get = lambda k, default=None: entity_dict.get(k, default)
        hit.entity = entity
        hit.distance = distance
        return hit

    def test_dense_hit_shape(self):
        entity = {
            "product_id": 100001,
            "title": "面霜 A",
            "brand": "X",
            "base_price": 199.0,
            "image_url": "http://x/a.png",
            "rating": 4.6,
            "review_count": 30,
            "sales_count": 500,
            "category": "护肤",
            "sub_category": "面霜",
            "tags": "保湿",
            "description": "长文本 " * 20,
            "status": 1,
        }
        hit = self._make_hit(entity, distance=0.75)
        item = ProductMilvusStore._hit_to_dict(hit, "dense")

        # 字段类型和值
        assert item["product_id"] == 100001
        assert item["title"] == "面霜 A"
        assert item["price"] == 199.0
        assert item["base_price"] == 199.0
        assert item["rating"] == 4.6
        assert item["sales_count"] == 500
        assert item["score"] == 0.75
        assert item["dense_score"] == 0.75
        # recall_sources 初始化为空
        assert item["recall_sources"] == []

    def test_hybrid_hit_uses_hybrid_score(self):
        entity = {"product_id": 1, "title": "A", "base_price": 100}
        hit = self._make_hit(entity, distance=0.42)
        item = ProductMilvusStore._hit_to_dict(hit, "hybrid")
        assert item["hybrid_score"] == 0.42

    def test_sparse_hit_uses_sparse_score(self):
        entity = {"product_id": 1, "title": "A", "base_price": 100}
        hit = self._make_hit(entity, distance=15.3)   # BM25 分数可以 > 1
        item = ProductMilvusStore._hit_to_dict(hit, "sparse")
        assert item["sparse_score"] == 15.3
