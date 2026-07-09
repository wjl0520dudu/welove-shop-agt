"""测试 tools/shopping_tools.py —— PG ORM 工具。

不需要外部服务（PG/Milvus），全部用 mock 覆盖。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.shopping_tools import ProductFeatures


# ---- ProductFeatures field_validator ----------------------------------------

class TestProductFeaturesValidation:
    """测试 ProductFeatures 对 LLM 返回空字符串的容错。"""

    def test_cautions_empty_string_coerced_to_list(self):
        f = ProductFeatures.model_validate({
            "core_ingredients": [],
            "suitable_skin": [],
            "key_benefits": [],
            "cautions": "",  # LLM 返回空字符串而非空列表
        })
        assert f.cautions == []

    def test_cautions_single_string_coerced_to_list(self):
        f = ProductFeatures.model_validate({
            "core_ingredients": [],
            "suitable_skin": [],
            "key_benefits": [],
            "cautions": "敏感肌先测试",
        })
        assert f.cautions == ["敏感肌先测试"]

    def test_cautions_normal_list(self):
        f = ProductFeatures.model_validate({
            "core_ingredients": [],
            "suitable_skin": [],
            "key_benefits": [],
            "cautions": ["含酒精", "孕妇慎用"],
        })
        assert f.cautions == ["含酒精", "孕妇慎用"]

    def test_all_list_fields_coerced(self):
        f = ProductFeatures.model_validate({
            "core_ingredients": "",
            "suitable_skin": "",
            "key_benefits": "",
            "cautions": "",
        })
        assert f.core_ingredients == []
        assert f.suitable_skin == []
        assert f.key_benefits == []
        assert f.cautions == []

    def test_all_list_fields_single_value(self):
        f = ProductFeatures.model_validate({
            "core_ingredients": "烟酰胺",
            "suitable_skin": "油皮",
            "key_benefits": "控油",
            "cautions": "含酒精",
        })
        assert f.core_ingredients == ["烟酰胺"]
        assert f.suitable_skin == ["油皮"]
        assert f.key_benefits == ["控油"]
        assert f.cautions == ["含酒精"]


# ---- helpers ----------------------------------------------------------------

def _make_runtime(conversation_id="c1", user_id=1):
    """构造模拟 ToolRuntime。"""
    from langgraph.prebuilt import ToolRuntime
    from langchain_core.runnables import RunnableConfig
    return ToolRuntime(
        state={"conversation_id": conversation_id, "user_id": user_id},
        context=None,
        config=RunnableConfig(),
        stream_writer=None,
        tool_call_id="test-call-id",
        store=None,
    )


def _make_mock_product(product_id, title="测试商品", brand="测试品牌", base_price=199.0,
                        rating=4.5, sales_count=100, sub_category="粉底液",
                        tags="保湿,滋润", description="一款测试商品"):
    """构造模拟 ProductORM 对象。"""
    p = MagicMock()
    p.id = product_id
    p.title = title
    p.brand = brand
    p.base_price = base_price
    p.image_url = "http://img/test.jpg"
    p.rating = rating
    p.review_count = 50
    p.sales_count = sales_count
    p.sub_category = sub_category
    p.tags = tags
    p.description = description
    return p


def _mock_session_factory(rows):
    """构造 mock 的 get_session_factory：返回含 rows 的 async session。"""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows

    mock_session = MagicMock()
    # session.execute 需要是 async → 用 AsyncMock
    mock_execute = AsyncMock(return_value=mock_result)
    mock_session.execute = mock_execute

    mock_sf = MagicMock()
    # session_factory() 返回一个 async context manager
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_sf.return_value = mock_ctx

    return mock_sf


# ---- search_products_by_name (PG ORM path) ----------------------------------

class TestSearchProductsByName:
    """测试 search_products_by_name 的 PG ORM 路径。"""

    def test_pg_orm_returns_products(self):
        mock_products = [
            _make_mock_product(1, "粉底液A", base_price=199.0),
            _make_mock_product(2, "粉底液B", base_price=299.0),
        ]
        mock_sf = _mock_session_factory(mock_products)

        from tools.shopping_tools import search_products_by_name

        async def run():
            with patch("tools.shopping_tools.get_session_factory", return_value=mock_sf):
                with patch("tools.shopping_tools.remember_product_cards", new_callable=AsyncMock):
                    with patch("tools.shopping_tools.remember_focused_product", new_callable=AsyncMock):
                        runtime = _make_runtime()
                        result = await search_products_by_name.ainvoke({
                            "query": "粉底液",
                            "limit": 5,
                            "runtime": runtime,
                        })
            return result

        result = asyncio.run(run())
        assert len(result) == 2
        assert result[0]["product_id"] == 1
        assert result[0]["title"] == "粉底液A"
        assert result[0]["price"] == 199.0
        assert result[1]["product_id"] == 2

    def test_no_results_returns_empty(self):
        mock_sf = _mock_session_factory([])

        from tools.shopping_tools import search_products_by_name

        async def run():
            with patch("tools.shopping_tools.get_session_factory", return_value=mock_sf):
                runtime = _make_runtime()
                result = await search_products_by_name.ainvoke({
                    "query": "不存在的商品",
                    "limit": 5,
                    "runtime": runtime,
                })
            return result

        result = asyncio.run(run())
        assert result == []

    def test_empty_query_returns_empty(self):
        from tools.shopping_tools import search_products_by_name

        async def run():
            runtime = _make_runtime()
            result = await search_products_by_name.ainvoke({
                "query": "",
                "limit": 5,
                "runtime": runtime,
            })
            return result

        result = asyncio.run(run())
        assert result == []


# ---- list_product_skus ------------------------------------------------------

class TestListProductSkus:
    """测试 list_product_skus 工具（PG ORM 路径）。"""

    def test_pg_orm_returns_skus(self):
        mock_sku1 = MagicMock()
        mock_sku1.id = 1
        mock_sku1.sku_code = "SKU001"
        mock_sku1.properties = {"容量": "30ml"}
        mock_sku1.price = 199.0
        mock_sku1.stock = 50
        mock_sku1.is_default = True

        mock_sku2 = MagicMock()
        mock_sku2.id = 2
        mock_sku2.sku_code = "SKU002"
        mock_sku2.properties = {"容量": "50ml"}
        mock_sku2.price = 299.0
        mock_sku2.stock = 30
        mock_sku2.is_default = False

        mock_sf = _mock_session_factory([mock_sku1, mock_sku2])

        from tools.shopping_tools import list_product_skus

        async def run():
            with patch("tools.shopping_tools.get_session_factory", return_value=mock_sf):
                result = await list_product_skus.ainvoke({"product_id": 1})
            return result

        result = asyncio.run(run())
        assert result["product_id"] == 1
        assert len(result["skus"]) == 2
        assert result["skus"][0]["skuCode"] == "SKU001"
        assert result["skus"][0]["price"] == 199.0
        assert result["message"] == "OK"

    def test_no_skus_returns_empty(self):
        mock_sf = _mock_session_factory([])

        from tools.shopping_tools import list_product_skus

        async def run():
            with patch("tools.shopping_tools.get_session_factory", return_value=mock_sf):
                result = await list_product_skus.ainvoke({"product_id": 99})
            return result

        result = asyncio.run(run())
        assert result["product_id"] == 99
        assert result["skus"] == []
        assert "暂无" in result["message"]