"""测试 tools/shopping_tools.py —— Java API 工具 + 降级回退。

不需要外部服务（Java/PG/Milvus），全部用 mock 覆盖。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.shopping_tools import (
    _java_product_to_dict,
    ProductFeatures,
)


# ---- _java_product_to_dict --------------------------------------------------

class TestJavaProductToDict:
    """测试 Java 驼峰 → Python 下划线字段映射。"""

    def test_full_product_mapping(self):
        java = {
            "id": 42,
            "title": "测试粉底液",
            "brand": "测试品牌",
            "basePrice": 299.00,
            "imageUrl": "http://img/test.jpg",
            "rating": 4.5,
            "reviewCount": 88,
            "salesCount": 1500,
            "subCategory": "粉底液",
            "tags": "保湿,滋润",
            "description": "一款测试粉底液",
        }
        result = _java_product_to_dict(java)
        assert result["product_id"] == 42
        assert result["title"] == "测试粉底液"
        assert result["brand"] == "测试品牌"
        assert result["price"] == 299.0
        assert result["base_price"] == 299.0
        assert result["image_url"] == "http://img/test.jpg"
        assert result["rating"] == 4.5
        assert result["review_count"] == 88
        assert result["sales_count"] == 1500
        assert result["sub_category"] == "粉底液"
        assert result["tags"] == "保湿,滋润"
        assert result["description"] == "一款测试粉底液"

    def test_minimal_product(self):
        java = {"id": 1}
        result = _java_product_to_dict(java)
        assert result["product_id"] == 1
        assert result["title"] == ""
        assert result["brand"] == ""
        assert result["price"] is None
        assert result["base_price"] is None
        assert result["image_url"] == ""
        assert result["rating"] is None
        assert result["review_count"] == 0
        assert result["sales_count"] == 0
        assert result["sub_category"] == ""
        assert result["tags"] == ""
        assert result["description"] == ""

    def test_none_price(self):
        java = {"id": 1, "basePrice": None}
        result = _java_product_to_dict(java)
        assert result["price"] is None
        assert result["base_price"] is None

    def test_zero_price(self):
        java = {"id": 1, "basePrice": 0}
        result = _java_product_to_dict(java)
        assert result["price"] == 0.0
        assert result["base_price"] == 0.0

    def test_empty_string_fields(self):
        java = {"id": 1, "title": None, "brand": None}
        result = _java_product_to_dict(java)
        assert result["title"] == ""
        assert result["brand"] == ""

    def test_missing_fields(self):
        java = {"id": 1, "title": "test"}
        result = _java_product_to_dict(java)
        assert result["product_id"] == 1
        assert result["title"] == "test"
        assert result["brand"] == ""
        assert result["price"] is None


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


# ---- search_products_by_name (Java API path) --------------------------------

class FakeJavaApiResult:
    """模拟 JavaApiResult。"""
    def __init__(self, success=True, data=None, error_code=None, message=None):
        self.success = success
        self.data = data
        self.error_code = error_code
        self.message = message


class FakeJavaApiClient:
    """模拟 JavaApiClient，记录调用参数并返回预设结果。"""
    def __init__(self, get_result=None):
        self.get_result = get_result or FakeJavaApiResult(success=True, data=[])
        self.get_calls = []

    async def get(self, path, jwt_token=None, params=None):
        self.get_calls.append({"path": path, "jwt_token": jwt_token, "params": params})
        return self.get_result


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


class TestSearchProductsByNameJavaApi:
    """测试 search_products_by_name 的 Java API 路径。"""

    def test_java_api_success_returns_products(self):
        java_products = [
            {"id": 1, "title": "粉底液A", "basePrice": 199, "brand": "品牌A"},
            {"id": 2, "title": "粉底液B", "basePrice": 299, "brand": "品牌B"},
        ]
        fake_client = FakeJavaApiClient(
            get_result=FakeJavaApiResult(success=True, data=java_products)
        )

        from tools.shopping_tools import search_products_by_name

        async def run():
            with patch("tools.shopping_tools.get_java_api_client", return_value=fake_client):
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
        # 验证调用了正确的 Java API
        assert fake_client.get_calls[0]["path"] == "/api/product/search"
        assert fake_client.get_calls[0]["params"] == {"keyword": "粉底液", "limit": 5}

    def test_java_api_empty_result(self):
        fake_client = FakeJavaApiClient(
            get_result=FakeJavaApiResult(success=True, data=[])
        )

        from tools.shopping_tools import search_products_by_name

        async def run():
            with patch("tools.shopping_tools.get_java_api_client", return_value=fake_client):
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
    """测试 list_product_skus 工具。"""

    def test_java_api_success(self):
        skus = [
            {"id": 1, "skuCode": "SKU001", "price": 199},
            {"id": 2, "skuCode": "SKU002", "price": 229},
        ]
        fake_client = FakeJavaApiClient(
            get_result=FakeJavaApiResult(success=True, data=skus)
        )

        from tools.shopping_tools import list_product_skus

        async def run():
            with patch("tools.shopping_tools.get_java_api_client", return_value=fake_client):
                result = await list_product_skus.ainvoke({"product_id": 1})
            return result

        result = asyncio.run(run())
        assert result["product_id"] == 1
        assert len(result["skus"]) == 2
        assert result["skus"][0]["skuCode"] == "SKU001"
        assert result["message"] == "OK"

    def test_java_api_failure_fallback(self):
        fake_client = FakeJavaApiClient(
            get_result=FakeJavaApiResult(success=False, error_code="JAVA_API_ERROR")
        )

        from tools.shopping_tools import list_product_skus

        async def run():
            with patch("tools.shopping_tools.get_java_api_client", return_value=fake_client):
                result = await list_product_skus.ainvoke({"product_id": 99})
            return result

        result = asyncio.run(run())
        assert result["product_id"] == 99
        assert result["skus"] == []
        assert "not available" in result["message"]
