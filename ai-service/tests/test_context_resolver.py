from app.application.assistant import resolve_turn_context
from app.application.assistant.context_resolver import build_shared_conversation_messages


TEXT_CARDS = [
    {"product_id": 11, "title": "旧的文字推荐 A"},
    {"product_id": 12, "title": "旧的文字推荐 B"},
]
IMAGE_CARDS = [
    {"product_id": 21, "title": "图片命中 A"},
    {"product_id": 22, "title": "图片命中 B"},
]


def test_preparation_prefers_latest_multimodal_message_artifact():
    result = resolve_turn_context(
        question="这两款对比一下",
        business_memory={"last_product_cards": TEXT_CARDS},
        conversation_history=[
            {"id": 1, "role": "assistant", "product_cards": TEXT_CARDS},
            {"id": 2, "role": "user", "content": "帮我找图里的同款", "image_url": "https://img.example/q.jpg"},
            {"id": 3, "role": "assistant", "image_url": "https://img.example/q.jpg", "product_cards": IMAGE_CARDS},
            {"id": 4, "role": "user", "content": "这两款对比一下"},
        ],
    )

    assert result["context_resolution"]["reference_message_id"] == 3
    assert result["business_memory"]["last_product_cards"] == IMAGE_CARDS
    assert result["business_memory"]["active_product_set"]["source_type"] == "multimodal_retrieval"
    assert result["context_resolution"]["candidate_product_ids"] == [21, 22]


def test_preparation_never_interprets_reference_or_clarifies():
    result = resolve_turn_context(
        question="那两款哪个好？",
        business_memory={},
        conversation_history=[
            {"id": 3, "role": "assistant", "product_cards": IMAGE_CARDS + [{"product_id": 23, "title": "图片命中 C"}]},
        ],
    )

    assert result["context_resolution"]["needs_clarification"] is False
    assert result["context_resolution"]["has_reference"] is False
    assert result["business_memory"]["last_product_cards"] == IMAGE_CARDS + [{"product_id": 23, "title": "图片命中 C"}]


def test_preparation_uses_latest_rendered_cards_without_semantic_detection():
    result = resolve_turn_context(
        question="敏感肌要注意什么？",
        business_memory={"last_product_cards": TEXT_CARDS},
        conversation_history=[{"id": 3, "role": "assistant", "product_cards": IMAGE_CARDS}],
    )

    assert result["business_memory"]["last_product_cards"] == IMAGE_CARDS
    assert result["context_resolution"]["has_reference"] is False


def test_ordinal_text_only_exposes_candidate_set_to_router():
    """“第二个多少钱”由 Router LLM 解析，Preparation 只暴露候选集合。"""
    result = resolve_turn_context(
        question="第二个多少钱",
        business_memory={"last_product_cards": TEXT_CARDS},
        conversation_history=[
            {"id": 1, "role": "assistant", "product_cards": TEXT_CARDS},
        ],
    )

    assert result["context_resolution"]["has_reference"] is False
    assert result["context_resolution"]["reference_source"] == "message_artifact"
    assert result["context_resolution"]["reference_message_id"] == 1
    assert result["context_resolution"]["needs_clarification"] is False
    # "第二个" 不是 "这两款"，所以 asks_for_two=False → selected = cards（全部）
    assert result["business_memory"]["last_product_cards"] == TEXT_CARDS
    assert result["business_memory"]["active_product_set"]["source_type"] == "recommendation"


def test_ordinal_text_does_not_change_prepared_set():
    result = resolve_turn_context(
        question="第一个适合什么肤质",
        business_memory={"last_product_cards": TEXT_CARDS},
        conversation_history=[
            {"id": 1, "role": "assistant", "product_cards": TEXT_CARDS + [{"product_id": 13, "title": "旧推荐 C"}]},
        ],
    )

    assert result["context_resolution"]["has_reference"] is False
    assert result["context_resolution"]["needs_clarification"] is False


def test_preparation_does_not_depend_on_question_wording():
    result = resolve_turn_context(
        question="适合什么肤质",
        business_memory={"last_product_cards": IMAGE_CARDS},
        conversation_history=[{"id": 1, "role": "assistant", "product_cards": TEXT_CARDS}],
    )

    assert result["context_resolution"]["has_reference"] is False
    assert result["business_memory"]["last_product_cards"] == TEXT_CARDS


def test_preparation_uses_store_cards_when_history_has_no_rendered_cards():
    result = resolve_turn_context(
        question="first and third items",
        business_memory={"last_product_cards": TEXT_CARDS},
        conversation_history=[],
    )

    assert result["context_resolution"]["reference_source"] == "store_fallback"
    assert result["context_resolution"]["reference_message_id"] is None
    assert result["context_resolution"]["candidate_product_ids"] == [11, 12]
    assert result["business_memory"]["active_product_set"] == {
        "source_message_id": None,
        "source_type": "recommendation",
        "product_ids": [11, 12],
    }


def test_preparation_injects_persisted_summary_once_before_recent_visible_messages():
    result = resolve_turn_context(
        question="我刚刚问了什么？",
        business_memory={},
        conversation_summary="用户此前询问果酸和视黄醇能否同用。",
        conversation_history=[
            {"id": 41, "role": "user", "content": "我刚刚问了什么？"},
        ],
    )

    messages = result["messages"]
    assert messages[0].type == "system"
    assert "果酸和视黄醇" in messages[0].content
    assert messages[1].type == "human"
    assert messages[1].content == "我刚刚问了什么？"
