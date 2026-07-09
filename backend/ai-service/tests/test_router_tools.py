"""测试 tools/router_tools.py —— 复合意图检测 + business_memory 格式化。

纯规则/纯格式化，不依赖任何外部服务。
"""
from __future__ import annotations

import pytest

from tools.router_tools import (
    detect_compound_intent,
    format_business_memory_for_router,
)


# ---- detect_compound_intent -------------------------------------------------

class TestDetectCompoundIntent:
    """测试复合意图检测。"""

    def test_single_shopping_intent(self):
        result = detect_compound_intent("帮我推荐几款粉底液")
        assert result["is_compound"] is False
        assert result["primary_intent"] == "shopping"
        assert result["secondary_intents"] == []

    def test_single_knowledge_intent(self):
        result = detect_compound_intent("烟酰胺有什么功效")
        assert result["is_compound"] is False
        assert result["primary_intent"] == "knowledge"

    def test_single_chitchat_intent(self):
        result = detect_compound_intent("你好")
        assert result["is_compound"] is False
        assert result["primary_intent"] == "chitchat"

    def test_meta_question_classified_as_chitchat(self):
        result = detect_compound_intent("我刚才问了什么")
        assert result["primary_intent"] == "chitchat"

    def test_compound_shopping_then_knowledge(self):
        result = detect_compound_intent("帮我推荐面霜，顺便说烟酰胺的功效")
        assert result["is_compound"] is True
        assert result["primary_intent"] == "shopping"
        assert result["primary_part"].strip().startswith("帮我推荐面霜")
        assert len(result["secondary_intents"]) == 1
        assert result["secondary_intents"][0]["intent"] == "knowledge"

    def test_compound_with_another_marker(self):
        result = detect_compound_intent("对比一下这两个粉底液，另外问一下什么是保湿因子")
        assert result["is_compound"] is True
        assert result["primary_intent"] == "shopping"

    def test_compound_with_ranhou(self):
        result = detect_compound_intent("先推荐一个防晒霜，然后告诉我怎么用")
        assert result["is_compound"] is True
        assert result["primary_intent"] == "shopping"
        assert result["secondary_intents"][0]["intent"] == "knowledge"

    def test_empty_query(self):
        result = detect_compound_intent("")
        assert result["is_compound"] is False
        assert result["primary_intent"] == "unknown"

    def test_unknown_when_no_pattern_matches(self):
        result = detect_compound_intent("嗯嗯嗯")
        assert result["is_compound"] is False
        assert result["primary_intent"] == "unknown"


# ---- format_business_memory_for_router --------------------------------------

class TestFormatBusinessMemoryForRouter:
    """测试 business_memory → Router prompt context 的格式化。"""

    def test_empty_memory_returns_empty(self):
        assert format_business_memory_for_router(None) == ""
        assert format_business_memory_for_router({}) == ""

    def test_last_product_cards_rendered(self):
        memory = {
            "last_product_cards": [
                {"product_id": 1, "title": "粉底液A", "price": 199},
                {"product_id": 2, "title": "粉底液B", "price": 299},
            ]
        }
        text = format_business_memory_for_router(memory)
        assert "上轮推荐商品" in text
        assert "粉底液A" in text
        assert "¥199" in text
        assert "粉底液B" in text

    def test_last_product_cards_truncated_at_5(self):
        cards = [{"product_id": i, "title": f"商品{i}", "price": i * 100} for i in range(1, 8)]
        memory = {"last_product_cards": cards}
        text = format_business_memory_for_router(memory)
        # 前 5 个应该在
        for i in range(1, 6):
            assert f"商品{i}" in text
        # 后 2 个不应该在具体列表里
        assert "商品6" not in text
        assert "商品7" not in text
        # 但要有汇总信息
        assert "另有 2 个未列出" in text

    def test_last_focused_product_rendered(self):
        memory = {
            "last_focused_product": {"product_id": 5, "title": "重点关注商品"}
        }
        text = format_business_memory_for_router(memory)
        assert "当前关注商品" in text
        assert "重点关注商品" in text

    def test_user_preferences_kept_selective_fields(self):
        memory = {
            "user_preferences": {
                "skin_type": "干皮",
                "gender": "女",
                "preference_tags": ["平价", "敏感肌"],
                "internal_debug": "should_be_stripped",  # 不在白名单里
            }
        }
        text = format_business_memory_for_router(memory)
        assert "用户偏好" in text
        assert "干皮" in text
        assert "敏感肌" in text
        assert "internal_debug" not in text
        assert "should_be_stripped" not in text

    def test_missing_title_falls_back_to_product_id(self):
        memory = {
            "last_product_cards": [{"product_id": 42}]
        }
        text = format_business_memory_for_router(memory)
        assert "商品42" in text

    def test_none_price_shows_placeholder(self):
        memory = {
            "last_product_cards": [{"product_id": 1, "title": "无价商品", "price": None}]
        }
        text = format_business_memory_for_router(memory)
        assert "价格未知" in text

    def test_all_fields_combined(self):
        memory = {
            "last_product_cards": [{"product_id": 1, "title": "A", "price": 100}],
            "last_focused_product": {"product_id": 1, "title": "A"},
            "user_preferences": {"skin_type": "油皮"},
        }
        text = format_business_memory_for_router(memory)
        assert "上轮推荐商品" in text
        assert "当前关注商品" in text
        assert "用户偏好" in text

    def test_empty_user_preferences_omitted(self):
        # 只有非白名单字段时不产出 [用户偏好] 部分
        memory = {
            "user_preferences": {"internal_only": "x"},
            "last_product_cards": [{"product_id": 1, "title": "A", "price": 100}],
        }
        text = format_business_memory_for_router(memory)
        assert "用户偏好" not in text
        # 但 last_product_cards 应该还在
        assert "上轮推荐商品" in text

    def test_result_starts_with_header(self):
        memory = {"last_product_cards": [{"product_id": 1, "title": "A", "price": 100}]}
        text = format_business_memory_for_router(memory)
        assert text.startswith("## 会话上下文")
