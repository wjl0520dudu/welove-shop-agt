"""排序器 + 卡片构造的单测（纯函数，不依赖 IO / LLM）。"""

from __future__ import annotations

from shopping.cards import build_product_card_from_detail, build_product_cards
from shopping.ranking import ProductRanker, _expand_synonyms
from shopping.schemas import ShoppingNeed


def _make_candidate(pid, title, price, brand="", tags="", desc="", sales=100, rating=4.5,
                    category="防晒", sub_category="", recall_sources=None):
    return {
        "product_id": pid,
        "title": title,
        "brand": brand,
        "price": price,
        "base_price": price,
        "tags": tags,
        "description": desc,
        "category": category,
        "sub_category": sub_category,
        "sales_count": sales,
        "rating": rating,
        "review_count": sales // 2,
        "recall_sources": list(recall_sources or []),
    }


class TestExpandSynonyms:
    def test_known_synonyms_expanded(self):
        out = _expand_synonyms(["清爽"])
        assert "轻薄" in out and "水感" in out and "不黏" in out

    def test_unknown_kept_as_is(self):
        out = _expand_synonyms(["some_random_word"])
        assert out == ["some_random_word"]

    def test_dedupe_across_terms(self):
        # "清爽" 和 "油皮" 都含 "控油"，只出现一次
        out = _expand_synonyms(["清爽", "油皮"])
        assert out.count("控油") == 1


class TestProductRanker:
    def test_empty_input_returns_empty(self):
        assert ProductRanker().rank([], ShoppingNeed()) == []

    def test_category_hit_scores_high(self):
        cands = [
            _make_candidate(1, "SPF50 防晒霜", 100, tags="防晒 清爽", category="防晒"),
            _make_candidate(2, "无关商品", 100, tags="", category="洗发水"),
        ]
        ranked = ProductRanker().rank(cands, ShoppingNeed(category="防晒"))
        assert ranked[0].product_id == 1
        assert ranked[0].score > ranked[1].score
        assert "匹配「防晒」品类" in ranked[0].rank_reason

    def test_preference_synonyms_matched(self):
        # 商品描述含"轻薄"，need.preferences 说"清爽" → 同义词应命中
        cands = [
            _make_candidate(1, "A", 100, desc="轻薄水润"),
            _make_candidate(2, "B", 100, desc="厚重滋润"),
        ]
        ranked = ProductRanker().rank(cands, ShoppingNeed(category="防晒", preferences=["清爽"]))
        assert ranked[0].product_id == 1
        assert "清爽" in ranked[0].matched_needs

    def test_avoid_downweights(self):
        # A 含避雷词，B 不含 → B 应该排前
        cands = [
            _make_candidate(1, "A 油腻款", 100, desc="油腻厚重"),
            _make_candidate(2, "B 清爽款", 100, desc="轻薄水感"),
        ]
        ranked = ProductRanker().rank(cands, ShoppingNeed(category="防晒", avoid=["油腻"]))
        assert ranked[0].product_id == 2
        # A 应带 risk_note
        a_result = [r for r in ranked if r.product_id == 1][0]
        assert any("避雷" in n for n in a_result.risk_notes)

    def test_over_budget_gets_risk_note(self):
        cands = [_make_candidate(1, "超预算", 500)]
        ranked = ProductRanker().rank(cands, ShoppingNeed(category="防晒", budget_max=200))
        assert ranked[0].risk_notes
        assert any("超出预算" in n for n in ranked[0].risk_notes)

    def test_sort_preference_price_low(self):
        cands = [
            _make_candidate(1, "贵", 300, sales=1000),
            _make_candidate(2, "便宜", 50, sales=100),
        ]
        ranked = ProductRanker().rank(
            cands,
            ShoppingNeed(category="防晒", sort_preference="price_low"),
        )
        assert ranked[0].product_id == 2   # 便宜排前

    def test_recall_source_boost(self):
        """多路都召回的商品，score 该多一点。"""
        cands = [
            _make_candidate(1, "多路命中", 100, recall_sources=["dense", "bm25", "hybrid"]),
            _make_candidate(2, "单路命中", 100, recall_sources=["dense"]),
        ]
        ranked = ProductRanker().rank(cands, ShoppingNeed(category="防晒"))
        # 完全相同其他条件下，多路应该排前
        assert ranked[0].product_id == 1


class TestBuildProductCards:
    def test_limit_respected(self):
        from shopping.schemas import RankedProduct
        rps = [
            RankedProduct(product_id=i, title=f"P{i}", price=100.0, rank_reason=[f"r{i}"])
            for i in range(5)
        ]
        cards = build_product_cards(rps, limit=3)
        assert len(cards) == 3
        assert cards[0]["product_id"] == 0

    def test_reason_from_rank_reason(self):
        from shopping.schemas import RankedProduct
        rp = RankedProduct(product_id=1, title="A", rank_reason=["匹配防晒", "适合油皮", "价格合适"])
        cards = build_product_cards([rp])
        # 只取前 2 条
        assert "匹配防晒" in cards[0]["reason"]
        assert "适合油皮" in cards[0]["reason"]
        assert "价格合适" not in cards[0]["reason"]

    def test_default_reason_when_empty(self):
        from shopping.schemas import RankedProduct
        rp = RankedProduct(product_id=1, title="A", rank_reason=[])
        cards = build_product_cards([rp])
        assert cards[0]["reason"] == "根据你的需求匹配到的商品。"


class TestBuildProductCardFromDetail:
    def test_basic_mapping(self):
        product = {
            "product_id": 42,
            "title": "SPF50 防晒",
            "brand": "Anessa",
            "price": 200.0,
            "image_url": "http://x.png",
            "rating": 4.8,
            "sales_count": 999,
        }
        card = build_product_card_from_detail(product)
        assert card["product_id"] == 42
        assert card["title"] == "SPF50 防晒"
        assert card["price"] == 200.0
        assert card["reason"] == "追问详情命中的商品。"
