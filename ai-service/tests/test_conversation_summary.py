import pytest
from langchain_core.messages import AIMessage

from app.application.assistant.context_resolver import build_shared_conversation_messages
from app.application.assistant.conversation_summary import (
    build_rolling_summary,
    normalize_visible_summary_messages,
)


class _SummaryLlm:
    def __init__(self, answer: str):
        self.answer = answer
        self.calls = []

    async def ainvoke(self, messages, config=None):
        self.calls.append((messages, config))
        return AIMessage(content=self.answer)


def test_summary_input_keeps_only_visible_message_facts():
    messages = normalize_visible_summary_messages([
        {
            "role": "assistant",
            "content": "我推荐了两款耳机。",
            "product_cards": [{
                "product_id": 99,
                "title": "开放式耳机 A",
                "price": 399,
                "internal_score": 0.98,
            }],
            "agent_meta": {"tool": "recommend_products"},
        },
        {"role": "tool", "content": "must not enter summary"},
        {"role": "user", "content": "第一款适合通勤吗？"},
    ])

    assert messages == [
        {
            "role": "assistant",
            "content": "我推荐了两款耳机。",
            "product_cards": [{"title": "开放式耳机 A", "price": 399}],
        },
        {"role": "user", "content": "第一款适合通勤吗？"},
    ]


@pytest.mark.asyncio
async def test_rolling_summary_merges_old_summary_and_bounds_response():
    llm = _SummaryLlm("新的摘要内容超过最大长度")
    result = await build_rolling_summary(
        llm,
        previous_summary="旧摘要：用户想买耳机。",
        messages=[{"role": "user", "content": "预算 500 元以内"}],
        max_chars=8,
    )

    assert result == "新的摘要内容超过"
    sent_messages, config = llm.calls[0]
    assert "旧摘要" in sent_messages[1].content
    assert "预算 500 元以内" in sent_messages[1].content
    assert config["run_name"] == "assistant.rolling-summary"


def test_router_and_chitchat_share_one_summary_plus_recent_history():
    messages = build_shared_conversation_messages(
        [
            {"id": 11, "role": "user", "content": "推荐两款耳机"},
            {"id": 12, "role": "assistant", "content": "已推荐 A 和 B。"},
            {"id": 13, "role": "user", "content": "第一款适合通勤吗？"},
        ],
        conversation_summary="用户此前关注开放式耳机，预算 500 元以内。",
    )

    assert len(messages) == 4
    assert messages[0].type == "system"
    assert "预算 500 元以内" in messages[0].content
    assert [message.type for message in messages[1:]] == ["human", "ai", "human"]
    assert messages[-1].content == "第一款适合通勤吗？"
