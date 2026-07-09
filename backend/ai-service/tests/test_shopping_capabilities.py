"""CompareCapability + DetailCapability 单测。

不打真库/真 LLM：
- _load_products_by_ids / _load_product_detail_raw 全 mock
- _extract_product_features 全 mock（避免真调 LLM）
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from shopping.capabilities.compare import CompareCapability, _extract_focus as extract_compare_focus
from shopping.capabilities.detail import DetailCapability, _extract_focus as extract_detail_focus
from shopping.schemas import ShoppingContext
from tools.shopping_tools import ProductFeatures


def _ctx(**kwargs):
    kw = {"conversation_id": "c1", "user_id": "u1"}
    kw.update(kwargs)
    return ShoppingContext(**kw)


# ---- Compare focus/detail focus ------------------------------------------

class TestExtractFocus:
    def test_compare_price(self):
        assert extract_compare_focus("哪个便宜") == "price"

    def test_compare_rating(self):
        assert extract_compare_focus("哪个评分高") == "rating"

    def test_compare_skin_type(self):
        assert extract_compare_focus("哪个适合敏感肌") == "skin_type"

    def test_compare_default(self):
        assert extract_compare_focus("对比一下") == "match"

    def test_detail_price(self):
        assert extract_detail_focus("多少钱") == "price"

    def test_detail_stock(self):
        assert extract_detail_focus("还有货吗") == "stock"

    def test_detail_sku(self):
        assert extract_detail_focus("有其他色号吗") == "sku"

    def test_detail_ingredients(self):
        assert extract_detail_focus("含什么成分") == "ingredients"

    def test_detail_overview_default(self):
        assert extract_detail_focus("讲讲这个") == "overview"


# ---- Compare 主流程 -------------------------------------------------------

class TestCompareCapability:
    def test_clarify_when_only_one_product(self):
        cap = CompareCapability()
        ctx = _ctx(last_product_cards=[{"product_id": 1, "title": "只有一个"}])

        with patch(
            "shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(query="哪个好", context=ctx))
        assert result.action == "clarify"

    def test_compare_two_from_last_cards(self):
        """last_product_cards 有 2 个 + query 无指代 → 直接用它们对比。"""
        cards = [
            {"product_id": 1, "title": "A", "price": 100, "rating": 4.5, "sales_count": 500},
            {"product_id": 2, "title": "B", "price": 200, "rating": 4.8, "sales_count": 300},
        ]
        ctx = _ctx(last_product_cards=cards)
        cap = CompareCapability()

        features = {
            1: ProductFeatures(core_ingredients=["A 成分"], suitable_skin=["油皮"]),
            2: ProductFeatures(core_ingredients=["B 成分"], suitable_skin=["干皮"]),
        }
        with patch(
            "shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value=features),
        ):
            result = asyncio.run(cap.run(query="这两个对比一下", context=ctx))

        assert result.action == "compare"
        assert len(result.comparison_rows) == 2
        assert result.dimensions and "价格" in result.dimensions
        # focus=match, 按 rating*0.6 + sales_norm*0.4 → B (rating 4.8, sales 300) vs A (4.5, 500)
        # A: 0.6*(4.5/5)+0.4*(500/500)=0.54+0.4=0.94
        # B: 0.6*(4.8/5)+0.4*(300/500)=0.576+0.24=0.816
        # A 应该被选中
        assert result.suggestion["recommended_product_id"] == 1

    def test_compare_focus_price_picks_cheapest(self):
        cards = [
            {"product_id": 1, "title": "贵", "price": 500, "rating": 4.9, "sales_count": 100},
            {"product_id": 2, "title": "便宜", "price": 50, "rating": 4.0, "sales_count": 100},
        ]
        ctx = _ctx(last_product_cards=cards)
        cap = CompareCapability()

        with patch(
            "shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(query="哪个便宜", context=ctx))
        assert result.suggestion["recommended_product_id"] == 2

    def test_compare_with_product_ids_hits_db(self):
        """显式传 product_ids → 从 PG 加载。"""
        cap = CompareCapability()

        # mock _load_products_by_ids 返回两个 dict
        rows = [
            {"product_id": 10, "title": "P10", "price": 100, "rating": 4.5, "sales_count": 100},
            {"product_id": 11, "title": "P11", "price": 200, "rating": 4.7, "sales_count": 200},
        ]
        with patch(
            "shopping.capabilities.compare._load_products_by_ids",
            new=AsyncMock(return_value=rows),
        ), patch(
            "shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(
                query="对比一下",
                context=_ctx(),
                product_ids=[10, 11],
            ))
        assert result.action == "compare"
        assert len(result.comparison_rows) == 2


# ---- Detail 主流程 --------------------------------------------------------

class TestDetailCapability:
    def test_clarify_when_no_pid(self):
        cap = DetailCapability()
        result = asyncio.run(cap.run(query="多少钱", context=_ctx()))
        assert result.action == "clarify"

    def test_resolve_ordinal_from_history(self):
        """query 有'第二个' + last_product_cards 有 → 定位到第 2 个。"""
        cards = [
            {"product_id": 1, "title": "A"},
            {"product_id": 2, "title": "B"},
            {"product_id": 3, "title": "C"},
        ]
        ctx = _ctx(last_product_cards=cards)

        product_detail = {
            "product_id": 2, "title": "B", "price": 100,
            "brand": "Y", "rating": 4.5, "sales_count": 300,
            "description": "aaa", "tags": "tagB", "skus": [],
        }
        with patch(
            "shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value=product_detail),
        ), patch(
            "shopping.capabilities.detail.remember_focused_product",
            new=AsyncMock(),
        ):
            result = asyncio.run(DetailCapability().run(query="第二个多少钱", context=ctx))
        assert result.action == "detail"
        assert result.product["product_id"] == 2
        assert result.focus == "price"
        # facts.price 应该来自主档
        assert result.facts["price"] == 100

    def test_focus_sku_returns_sku_list(self):
        cards = [{"product_id": 1, "title": "A"}]
        skus = [
            {"id": 1, "price": 100, "stock": 5, "properties": {"color": "red"}},
            {"id": 2, "price": 120, "stock": 0, "properties": {"color": "blue"}},
        ]
        product = {"product_id": 1, "title": "A", "price": 100, "skus": skus}
        with patch(
            "shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value=product),
        ), patch(
            "shopping.capabilities.detail.remember_focused_product",
            new=AsyncMock(),
        ):
            result = asyncio.run(DetailCapability().run(
                query="有其他色号吗", context=_ctx(last_product_cards=cards),
            ))
        assert result.focus == "sku"
        assert result.facts["sku_count"] == 2
        assert result.facts["total_stock"] == 5
        assert result.facts["in_stock"] is True

    def test_focus_ingredients_uses_llm_features(self):
        product = {"product_id": 5, "title": "A", "description": "含烟酰胺 5%"}
        features = {5: ProductFeatures(core_ingredients=["烟酰胺"], concentration="5%")}
        with patch(
            "shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value=product),
        ), patch(
            "shopping.capabilities.detail._extract_product_features",
            new=AsyncMock(return_value=features),
        ), patch(
            "shopping.capabilities.detail.remember_focused_product",
            new=AsyncMock(),
        ):
            result = asyncio.run(DetailCapability().run(
                query="含什么成分", context=_ctx(),
                product_id=5,
            ))
        assert result.focus == "ingredients"
        assert result.facts["core_ingredients"] == ["烟酰胺"]
        assert result.facts["concentration"] == "5%"

    def test_empty_when_product_missing(self):
        with patch(
            "shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(DetailCapability().run(
                query="多少钱", context=_ctx(),
                product_id=999,
            ))
        assert result.action == "empty"
        assert "不存在" in (result.empty_reason or "")
