from datetime import datetime, timedelta, timezone
import asyncio
from unittest.mock import AsyncMock

from app.domain.shopping.preferences import (
    active_preference_facts,
    build_preference_questions,
    make_preference_fact,
    merge_preference_facts,
)
from app.domain.shopping.personalization import (
    apply_user_preferences,
    facts_from_shopping_need,
    personalized_rerank_candidates,
)
from app.domain.shopping.ranking import ProductRanker
from app.domain.shopping.schemas import ShoppingNeed
from evals.preference_metrics import ndcg_at_k, preference_compliance_at_k
from app.application.assistant import AssistantGraph


def _prefs(*facts, **legacy):
    return {**legacy, "preference_facts": list(facts)}


def _candidate(pid, title, description, *, category="防晒", sales=100):
    return {
        "product_id": pid,
        "title": title,
        "description": description,
        "category": category,
        "sub_category": category,
        "price": 100,
        "sales_count": sales,
        "rating": 4.5,
        "recall_sources": ["dense"],
    }


def test_new_conflicting_fact_replaces_old_fact():
    old = make_preference_fact("preference", "香味重", polarity="like")
    new = make_preference_fact("preference", "香味重", polarity="dislike")
    merged = merge_preference_facts([old], [new])
    assert len(merged) == 1
    assert merged[0]["polarity"] == "dislike"


def test_expired_fact_is_ignored():
    expired = make_preference_fact(
        "preference",
        "清爽",
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    assert active_preference_facts(_prefs(expired)) == []


def test_current_request_overrides_long_term_conflict():
    preferences = _prefs(make_preference_fact("preference", "清爽"))
    need, trace = apply_user_preferences(
        ShoppingNeed(category="防晒", avoid=["清爽"]),
        preferences,
    )
    assert need.avoid == ["清爽"]
    assert "清爽" not in need.personalization_preferences
    assert trace["positive"] == []


def test_category_scoped_fact_only_applies_to_same_category():
    fact = make_preference_fact(
        "preference", "清爽", scope={"category": "防晒"},
    )
    sunscreen, _ = apply_user_preferences(ShoppingNeed(category="防晒"), _prefs(fact))
    headphones, _ = apply_user_preferences(ShoppingNeed(category="耳机"), _prefs(fact))
    assert sunscreen.personalization_preferences == ["清爽"]
    assert headphones.personalization_preferences == []


def test_legacy_profile_is_backward_compatible():
    need, trace = apply_user_preferences(
        ShoppingNeed(category="面霜"),
        {"skin_type": "油性", "preference_tags": ["高性价比"]},
    )
    assert need.skin_type == "油皮"
    assert "油皮" in need.personalization_preferences
    assert "高性价比" in need.personalization_preferences
    assert trace["skin_type_applied"] is True


def test_long_term_budget_stays_soft_and_current_budget_wins():
    preferences = _prefs(make_preference_fact(
        "budget_max", 200, scope={"category": "耳机"},
    ))
    soft_need, _ = apply_user_preferences(ShoppingNeed(category="耳机"), preferences)
    explicit_need, _ = apply_user_preferences(
        ShoppingNeed(category="耳机", budget_max=500), preferences,
    )
    assert soft_need.budget_max is None
    assert soft_need.personalization_budget_max == 200
    assert explicit_need.budget_max == 500
    assert explicit_need.personalization_budget_max is None


def test_explicit_need_parser_output_becomes_scoped_facts_without_extra_llm():
    facts = facts_from_shopping_need(
        ShoppingNeed(
            category="防晒",
            skin_type="油皮",
            preferences=["清爽"],
            avoid=["香味重"],
            budget_max=200,
        ),
        query="预算 200 以内，想要清爽且不要香味重的防晒",
        category="防晒",
    )
    aspects = [fact["aspect"] for fact in facts]
    assert "skin_type" in aspects
    assert "preference" in aspects
    assert "budget_max" in aspects
    assert all(
        fact.get("scope", {}).get("category") == "防晒"
        for fact in facts
        if fact["aspect"] != "skin_type"
    )


def test_product_ranker_soft_boosts_long_term_match():
    candidates = [
        _candidate(1, "普通防晒", "基础防晒配方"),
        _candidate(2, "轻薄防晒", "轻薄水感不黏腻"),
    ]
    need = ShoppingNeed(
        category="防晒",
        personalization_preferences=["清爽"],
    )
    ranked = ProductRanker().rank(candidates, need)
    assert ranked[0].product_id == 2
    assert ranked[0].personalization_score > 0
    assert "清爽" in ranked[0].matched_preferences
    assert any("长期偏好" in reason for reason in ranked[0].rank_reason)


def test_product_ranker_penalizes_long_term_avoid_match():
    candidates = [
        _candidate(1, "浓香款", "香味重，留香明显"),
        _candidate(2, "无香款", "无香轻薄"),
    ]
    need = ShoppingNeed(category="防晒", personalization_avoid=["香味重"])
    ranked = ProductRanker().rank(candidates, need)
    assert ranked[0].product_id == 2
    risky = next(item for item in ranked if item.product_id == 1)
    assert "香味重" in risky.preference_conflicts


def test_multimodal_candidates_are_reranked_from_structured_text_only():
    candidates = [
        _candidate(1, "滋润防晒", "滋润厚重"),
        _candidate(2, "清爽防晒", "轻薄水感不黏腻"),
        _candidate(3, "基础防晒", "日常防护"),
    ]
    preferences = _prefs(make_preference_fact(
        "preference", "清爽", scope={"category": "防晒"},
    ))
    ranked = personalized_rerank_candidates(candidates, preferences)
    assert ranked[0]["product_id"] == 2
    assert ranked[0]["_personalization_matches"] == ["清爽"]


def test_preference_questions_are_deterministic_and_deduped():
    preferences = _prefs(
        make_preference_fact("skin_type", "油皮"),
        make_preference_fact("preference_tag", "高性价比"),
        make_preference_fact("category_interest", "防晒"),
    )
    questions = build_preference_questions(preferences, limit=4)
    assert any("油皮" in question for question in questions)
    assert any("高性价比" in question and "防晒" in question for question in questions)
    assert len(questions) == len(set(questions))


def test_preference_eval_metrics_reward_better_ordering():
    grades = {"1": 0, "2": 3, "3": 1}
    assert preference_compliance_at_k([2, 3], grades, k=2) == 1.0
    assert ndcg_at_k([2, 3, 1], grades, k=3) > ndcg_at_k([1, 3, 2], grades, k=3)


def test_request_profile_is_synced_without_user_service_roundtrip(monkeypatch):
    remember = AsyncMock()
    monkeypatch.setattr("app.application.assistant.graph.remember_user_preferences", remember)
    asyncio.run(AssistantGraph._sync_request_profile({
        "conversation_id": "c1",
        "user_id": 7,
        "gender": "2",
        "skin_type": "油性",
        "preference_tags": ["高性价比"],
    }))
    remember.assert_awaited_once_with(
        "c1",
        7,
        {"gender": "2", "skin_type": "油性", "preference_tags": ["高性价比"]},
    )
