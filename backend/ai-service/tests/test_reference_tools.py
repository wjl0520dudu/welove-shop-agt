"""测试 tools/reference_tools.py —— 指代消解逻辑。

纯 mock，不需要 PG/Milvus/Java。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


# ---- fixtures ---------------------------------------------------------------

def _make_runtime(conversation_id="c1", user_id=1):
    """构造模拟 ToolRuntime（复用 test_shopping_tools.py 的模式）。"""
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


_CARDS = [
    {"product_id": 1, "title": "粉底液A", "price": 199, "brand": "品牌A", "rating": 4.5, "sales_count": 100},
    {"product_id": 2, "title": "粉底液B", "price": 299, "brand": "品牌B", "rating": 4.8, "sales_count": 300},
    {"product_id": 3, "title": "粉底液C", "price": 99,  "brand": "品牌C", "rating": 4.2, "sales_count": 500},
]

_FOCUSED = {"product_id": 2, "title": "粉底液B", "price": 299}


def _mock_get_memory(*, cards=None, focused=None, prefs=None, entities=None):
    """构造 get_business_memory 的返回。"""
    memory = {}
    if cards is not None:
        memory["last_product_cards"] = cards
    if focused is not None:
        memory["last_focused_product"] = focused
    if prefs is not None:
        memory["user_preferences"] = prefs
    if entities is not None:
        memory["last_knowledge_entities"] = entities
    return AsyncMock(return_value=memory)


# ---- 序号指代 ---------------------------------------------------------------

class TestOrdinalReference:
    """测试序号指代：第一个、第二款、最后一个、倒数第一个。"""

    def test_second_matches_index_1(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "第二个多少钱",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "ordinal"
        assert result["matched_product"]["product_id"] == 2
        assert "「粉底液B」" in result["resolved_query"]

    def test_last_one_matches_end(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "最后一个怎么样",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "ordinal"
        assert result["matched_product"]["product_id"] == 3

    def test_reverse_ordinal(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "倒数第2个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["matched_product"]["product_id"] == 2  # 倒数第2 = index -2 = 粉底液B

    def test_out_of_range_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "第100个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False

    def test_no_cards_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=[])):
                return await resolve_reference.ainvoke({
                    "query": "第二个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False


# ---- 代词指代 ---------------------------------------------------------------

class TestPronominalReference:
    """测试代词指代：刚才那个、这个、它。"""

    def test_prefer_focused_product(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS, focused=_FOCUSED)):
                return await resolve_reference.ainvoke({
                    "query": "刚才那个多少钱",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "pronominal"
        # focused 优先于 cards[0]
        assert result["matched_product"]["product_id"] == 2

    def test_fallback_to_first_card_when_no_focused(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "这个多少钱",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "pronominal"
        assert result["matched_product"]["product_id"] == 1  # cards[0]

    def test_no_memory_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory()):
                return await resolve_reference.ainvoke({
                    "query": "刚才那个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False


# ---- 比较指代 ---------------------------------------------------------------

class TestComparativeReference:
    """测试比较指代：更便宜的、评分高的、销量多的。"""

    def test_cheaper_picks_min_price(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "更便宜的那个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "comparative"
        # 粉底液C 价格 99 最低
        assert result["matched_product"]["product_id"] == 3

    def test_higher_rating_picks_max_rating(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "评分更高的",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "comparative"
        # 粉底液B 评分 4.8 最高
        assert result["matched_product"]["product_id"] == 2

    def test_more_sales_picks_max_sales(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "销量最多的",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        # 粉底液C 销量 500 最高
        assert result["matched_product"]["product_id"] == 3

    def test_more_expensive_picks_max_price(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "更贵的那款",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        # 粉底液B 价格 299 最高
        assert result["matched_product"]["product_id"] == 2


# ---- 隐式指代 ---------------------------------------------------------------

class TestImplicitReference:
    """测试隐式指代：还有别的颜色吗、多少钱等，指向 last_focused_product。"""

    def test_ask_price_implicitly_matches_focused(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(focused=_FOCUSED)):
                return await resolve_reference.ainvoke({
                    "query": "多少钱啊",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "implicit"
        assert result["matched_product"]["product_id"] == 2

    def test_ask_color_matches_focused(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(focused=_FOCUSED)):
                return await resolve_reference.ainvoke({
                    "query": "还有别的颜色吗",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "implicit"

    def test_implicit_no_focused_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):  # 只有 cards，无 focused
                return await resolve_reference.ainvoke({
                    "query": "多少钱",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False


# ---- 优先级 -----------------------------------------------------------------

class TestReferenceResolutionPriority:
    """测试解析优先级：ordinal > pronominal > comparative > implicit。"""

    def test_ordinal_wins_over_pronominal(self):
        """'第二个那款' —— 应该按序号解析，不是代词。"""
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS, focused=_FOCUSED)):
                return await resolve_reference.ainvoke({
                    "query": "第二个那款",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["reference_type"] == "ordinal"
        assert result["matched_product"]["product_id"] == 2

    def test_no_reference_at_all(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS)):
                return await resolve_reference.ainvoke({
                    "query": "推荐一款保湿粉底液",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False
        assert result["resolved_query"] == "推荐一款保湿粉底液"


# ---- 兜底 -------------------------------------------------------------------

class TestGracefulDegradation:
    """测试异常处理：Store 读取失败也不该报错。"""

    def test_store_error_returns_no_reference(self):
        from tools.reference_tools import resolve_reference

        async def run():
            async def _raise(*args, **kwargs):
                raise RuntimeError("store down")

            with patch("tools.reference_tools.get_business_memory", side_effect=_raise):
                return await resolve_reference.ainvoke({
                    "query": "第二个",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False
        assert "无法读取业务记忆" in result["hint"]


# ---- 知识实体指代 ----------------------------------------------------------

_ENTITIES = ["烟酰胺", "视黄醇", "透明质酸"]


class TestEntityOrdinalReference:
    """实体域序号指代：上一轮谈过烟酰胺/视黄醇，本轮问'第二个的成分'。"""

    def test_second_entity_matches_index_1(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "第二个的成分是什么",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "entity_ordinal"
        assert result["matched_entity"] == "视黄醇"
        assert result["matched_entities"] == ["视黄醇"]
        assert result["matched_product"] is None
        assert "「视黄醇」" in result["resolved_query"]

    def test_last_entity_matches_end(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "最后一个功效",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["matched_entity"] == "透明质酸"

    def test_no_entities_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=[])):
                return await resolve_reference.ainvoke({
                    "query": "第二个的成分",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False


class TestEntityPluralReference:
    """实体域复数指代：'它们'、'这几个' → 上轮多个实体。"""

    def test_them_all_matches_all_entities(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "它们的副作用有哪些",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "entity_plural"
        assert result["matched_entities"] == _ENTITIES

    def test_three_entities_matches_first_three(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "这三个都能空腹用吗",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "entity_plural"
        assert len(result["matched_entities"]) == 3


class TestEntityImplicitReference:
    """实体域隐式指代：句里含'副作用/成分/怎么用'但无明确主语，指向 entities[0]。"""

    def test_implicit_side_effect_matches_first_entity(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "副作用严重吗",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is True
        assert result["reference_type"] == "entity_implicit"
        assert result["matched_entity"] == "烟酰胺"

    def test_implicit_no_entities_returns_no_match(self):
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=[])):
                return await resolve_reference.ainvoke({
                    "query": "副作用严重吗",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["has_reference"] is False


class TestProductWinsOverEntity:
    """商品指代优先：同时有商品和实体上下文时，优先返回商品结果。"""

    def test_product_ordinal_wins_over_entity(self):
        """两域都有 last_XX，'第二个'先按商品定位。"""
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(cards=_CARDS, entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "第二个多少钱",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["reference_type"] == "ordinal"      # 商品域
        assert result["matched_product"]["product_id"] == 2
        # 实体字段被 pad 成空
        assert result["matched_entity"] is None

    def test_entity_wins_when_no_products(self):
        """只有实体记忆时，'第二个'落到实体域。"""
        from tools.reference_tools import resolve_reference

        async def run():
            with patch("tools.reference_tools.get_business_memory",
                       _mock_get_memory(entities=_ENTITIES)):
                return await resolve_reference.ainvoke({
                    "query": "第二个的成分",
                    "runtime": _make_runtime(),
                })

        result = asyncio.run(run())
        assert result["reference_type"] == "entity_ordinal"
        assert result["matched_entity"] == "视黄醇"
