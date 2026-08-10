"""CompareCapability + DetailCapability 单测。

不打真库/真 LLM：
- _load_products_by_ids / _load_product_detail_raw 全 mock
- _extract_product_features 全 mock（避免真调 LLM）
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.domain.shopping.capabilities.compare import CompareCapability
from app.domain.shopping.capabilities.detail import DetailCapability
from app.domain.shopping.schemas import ShoppingContext
from app.domain.shopping.tools.shopping_tools import ProductFeatures


def _ctx(**kwargs):
    kw = {"conversation_id": "c1", "user_id": "u1"}
    kw.update(kwargs)
    return ShoppingContext(**kw)


# ---- Compare 主流程 -------------------------------------------------------

class TestCompareCapability:
    def test_clarify_when_router_binds_only_one_product(self):
        cap = CompareCapability()
        ctx = _ctx(selected_product_ids=[1])

        with patch(
            "app.domain.shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(query="哪个好", context=ctx))
        assert result.action == "clarify"

    def test_compare_uses_router_bound_ids_not_history(self):
        cards = [
            {"product_id": 1, "title": "A", "price": 100, "rating": 4.5, "sales_count": 500},
            {"product_id": 2, "title": "B", "price": 200, "rating": 4.8, "sales_count": 300},
        ]
        ctx = _ctx(last_product_cards=cards, selected_product_ids=[1, 2])
        cap = CompareCapability()

        features = {
            1: ProductFeatures(core_ingredients=["A 成分"], suitable_skin=["油皮"]),
            2: ProductFeatures(core_ingredients=["B 成分"], suitable_skin=["干皮"]),
        }
        rows = [
            {"product_id": 1, "title": "A", "price": 100, "rating": 4.5, "sales_count": 500},
            {"product_id": 2, "title": "B", "price": 200, "rating": 4.8, "sales_count": 300},
        ]
        with patch(
            "app.domain.shopping.capabilities.compare._load_products_by_ids",
            new=AsyncMock(return_value=rows),
        ), patch(
            "app.domain.shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value=features),
        ):
            result = asyncio.run(cap.run(query="这两个对比一下", context=ctx))

        assert result.action == "compare"
        assert len(result.comparison_rows) == 2
        assert result.dimensions and "价格" in result.dimensions
        # 旧回滚 Tool 只给事实矩阵，不再通过关键词 focus 替 Agent 选赢家。
        assert result.suggestion == {}

    def test_compare_uses_router_selected_product_ids(self):
        ctx = _ctx(
            last_product_cards=[
                {"product_id": 1, "title": "A"},
                {"product_id": 2, "title": "B"},
                {"product_id": 3, "title": "C"},
            ],
            selected_product_ids=[1, 3],
        )
        rows = [
            {"product_id": 1, "title": "A", "price": 100, "rating": 4.5, "sales_count": 100},
            {"product_id": 3, "title": "C", "price": 200, "rating": 4.7, "sales_count": 200},
        ]
        cap = CompareCapability()
        with patch(
            "app.domain.shopping.capabilities.compare._load_products_by_ids",
            new=AsyncMock(return_value=rows),
        ) as load, patch(
            "app.domain.shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run("比较这两款", ctx))

        assert result.action == "compare"
        load.assert_awaited_once_with([1, 3])

    def test_compare_open_question_does_not_require_a_focus_keyword_branch(self):
        cards = [
            {"product_id": 1, "title": "贵", "price": 500, "rating": 4.9, "sales_count": 100},
            {"product_id": 2, "title": "便宜", "price": 50, "rating": 4.0, "sales_count": 100},
        ]
        ctx = _ctx(last_product_cards=cards, selected_product_ids=[1, 2])
        cap = CompareCapability()

        with patch(
            "app.domain.shopping.capabilities.compare._load_products_by_ids",
            new=AsyncMock(return_value=cards),
        ), patch(
            "app.domain.shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(query="哪个便宜", context=ctx))
        assert result.action == "compare"
        assert result.suggestion == {}
        assert [row["product_id"] for row in result.comparison_rows] == [1, 2]

    def test_compare_with_product_ids_hits_db(self):
        """显式传 product_ids → 从 PG 加载。"""
        cap = CompareCapability()

        # mock _load_products_by_ids 返回两个 dict
        rows = [
            {"product_id": 10, "title": "P10", "price": 100, "rating": 4.5, "sales_count": 100},
            {"product_id": 11, "title": "P11", "price": 200, "rating": 4.7, "sales_count": 200},
        ]
        with patch(
            "app.domain.shopping.capabilities.compare._load_products_by_ids",
            new=AsyncMock(return_value=rows),
        ), patch(
            "app.domain.shopping.capabilities.compare._extract_product_features",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(cap.run(
                query="对比一下",
                context=_ctx(selected_product_ids=[10, 11]),
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

    def test_does_not_resolve_ordinal_from_history(self):
        cards = [
            {"product_id": 1, "title": "A"},
            {"product_id": 2, "title": "B"},
            {"product_id": 3, "title": "C"},
        ]
        ctx = _ctx(last_product_cards=cards)

        with patch(
            "app.domain.shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(),
        ) as load:
            result = asyncio.run(DetailCapability().run(query="第二个多少钱", context=ctx))
        assert result.action == "clarify"
        load.assert_not_awaited()

    def test_focus_sku_returns_sku_list(self):
        cards = [{"product_id": 1, "title": "A"}]
        skus = [
            {"id": 1, "price": 100, "stock": 5, "properties": {"color": "red"}},
            {"id": 2, "price": 120, "stock": 0, "properties": {"color": "blue"}},
        ]
        product = {"product_id": 1, "title": "A", "price": 100, "skus": skus}
        with patch(
            "app.domain.shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value=product),
        ):
            result = asyncio.run(DetailCapability().run(
                query="有其他色号吗", context=_ctx(last_product_cards=cards, selected_product_ids=[1]),
            ))
        assert result.focus is None
        assert result.facts["sku_count"] == 2
        assert result.facts["total_stock"] == 5
        assert result.facts["in_stock"] is True

    def test_open_ingredient_question_uses_returned_product_facts_without_focus_rules(self):
        product = {"product_id": 5, "title": "A", "description": "含烟酰胺 5%"}
        with patch(
            "app.domain.shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value=product),
        ):
            result = asyncio.run(DetailCapability().run(
                query="含什么成分", context=_ctx(selected_product_ids=[5]),
                product_id=5,
            ))
        assert result.focus is None
        assert result.facts["description"] == "含烟酰胺 5%"
        assert result.facts["in_stock"] is None

    def test_empty_when_product_missing(self):
        with patch(
            "app.domain.shopping.capabilities.detail._load_product_detail_raw",
            new=AsyncMock(return_value={}),
        ):
            result = asyncio.run(DetailCapability().run(
                query="多少钱", context=_ctx(selected_product_ids=[999]),
                product_id=999,
            ))
        assert result.action == "empty"
        assert "不存在" in (result.empty_reason or "")
