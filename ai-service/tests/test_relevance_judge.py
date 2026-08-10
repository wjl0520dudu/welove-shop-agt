from unittest.mock import AsyncMock

import pytest

from app.domain.shopping.relevance_judge import filter_recommendation_candidates


def _item(product_id, sub_category):
    return {
        "product_id": product_id,
        "title": str(product_id),
        "sub_category": sub_category,
    }


@pytest.mark.asyncio
async def test_filter_candidates_uses_exact_and_alternative_decisions(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"items": [{"candidate_index": 1, "decision": "exact", '
        '"same_product_type": true, "reason": "命中"}, '
        '{"candidate_index": 2, "decision": "reject", "reason": "无关"}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="方便面",
        candidates=[_item(1, "方便面"), _item(2, "咖啡")],
    )

    assert [item["product_id"] for item in result] == [1]
    assert result[0]["match_status"] == "exact"


@pytest.mark.asyncio
async def test_filter_candidates_returns_empty_when_judge_fails(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.side_effect = RuntimeError("vision model unavailable")

    result = await filter_recommendation_candidates(
        llm=llm,
        query="",
        candidates=[_item(1, "方便面"), _item(2, "方便面"), _item(3, "咖啡")],
    )

    assert result == []


@pytest.mark.asyncio
async def test_filter_candidates_accepts_partial_display_decisions(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"items": [{"candidate_index": 2, "decision": "exact", '
        '"same_product_type": true, "reason": "命中"}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="咖啡机",
        candidates=[_item(1, "手机"), _item(2, "咖啡机"), _item(3, "平板")],
    )

    assert [item["product_id"] for item in result] == [2]


@pytest.mark.asyncio
async def test_filter_candidates_returns_alternatives_only_when_no_exact(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"items": [{"candidate_index": 1, "decision": "alternative", '
        '"same_product_type": true, "reason": "超出预算", '
        '"constraint_gaps": [{"name": "budget"}]}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="500元以内的耳机",
        candidates=[_item(1, "耳机")],
    )

    assert [item["product_id"] for item in result] == [1]
    assert result[0]["match_status"] == "alternative"
    assert result[0]["constraint_gaps"] == [{"name": "budget"}]


@pytest.mark.asyncio
async def test_filter_candidates_rejects_cross_type_alternative(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"items": [{"candidate_index": 1, "decision": "alternative", '
        '"same_product_type": false, "reason": "是相关咖啡商品", '
        '"constraint_gaps": [{"name": "product_type"}]}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="推荐一台咖啡机",
        candidates=[_item(1, "速溶咖啡")],
    )

    assert result == []


def test_judge_prompt_forbids_inventing_unspecified_constraints():
    from app.domain.shopping.relevance_judge import _judge_prompt

    prompt = _judge_prompt(
        "推荐几款耳机",
        [{"title": "真无线耳机", "price": 1699, "sub_category": "真无线耳机"}],
    )

    assert "用户未提预算" in prompt
    assert "必须判为 exact" in prompt
    assert "低分只影响后续代码排序" in prompt
    assert "两款在需求命中阶段都必须判为 exact" in prompt


@pytest.mark.asyncio
async def test_high_preference_applicability_uses_model_scores_for_code_sort(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"preference_applicability_score": 0.95, "items": ['
        '{"candidate_index": 1, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.2, "matched_preferences": []},'
        '{"candidate_index": 2, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.9, "matched_preferences": ["清爽"]}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="推荐夏天使用的护肤品",
        candidates=[_item(1, "面霜"), _item(2, "面霜")],
        preferences={"skin_type": "油皮", "preference_tags": ["清爽"]},
    )

    assert [item["product_id"] for item in result] == [2, 1]
    assert result[0]["personalization_score"] == 0.9
    assert result[0]["matched_preferences"] == ["清爽"]
    llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_low_preference_applicability_keeps_rerank_order(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"preference_applicability_score": 0.05, "items": ['
        '{"candidate_index": 1, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.1},'
        '{"candidate_index": 2, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.9}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="推荐几款耳机",
        candidates=[_item(1, "真无线耳机"), _item(2, "真无线耳机")],
        preferences={"skin_type": "油皮", "preference_tags": ["清爽"]},
    )

    assert [item["product_id"] for item in result] == [1, 2]


@pytest.mark.asyncio
async def test_all_low_candidate_preference_scores_keep_rerank_order(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"preference_applicability_score": 0.95, "items": ['
        '{"candidate_index": 1, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.1},'
        '{"candidate_index": 2, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.2}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="推荐两款面霜",
        candidates=[_item(1, "面霜"), _item(2, "面霜")],
        preferences={"skin_type": "油皮", "preference_tags": ["清爽"]},
    )

    assert [item["product_id"] for item in result] == [1, 2]


@pytest.mark.asyncio
async def test_no_basic_preferences_never_applies_preference_rerank(monkeypatch):
    monkeypatch.setattr("app.domain.shopping.relevance_judge.config.SHOPPING_LLM_JUDGE_ENABLED", True)
    llm = AsyncMock()
    llm.ainvoke.return_value.content = (
        '{"preference_applicability_score": 1, "items": ['
        '{"candidate_index": 1, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 0.1},'
        '{"candidate_index": 2, "decision": "exact", "same_product_type": true, '
        '"preference_relevance_score": 1}]}'
    )

    result = await filter_recommendation_candidates(
        llm=llm,
        query="推荐几款耳机",
        candidates=[_item(1, "真无线耳机"), _item(2, "真无线耳机")],
    )

    assert [item["product_id"] for item in result] == [1, 2]
    llm.ainvoke.assert_awaited_once()


def test_judge_prompt_only_includes_basic_preferences():
    from app.domain.shopping.relevance_judge import _judge_prompt

    prompt = _judge_prompt(
        "推荐护肤品",
        [_item(1, "面霜")],
        {
            "skin_type": "油皮",
            "preference_tags": ["清爽"],
            "preference_facts": [{"aspect": "brand", "value": "某品牌"}],
        },
    )

    assert '"skin_type": "油皮"' in prompt
    assert '"preference_tags": ["清爽"]' in prompt
    assert "preference_facts" not in prompt
