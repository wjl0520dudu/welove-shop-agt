from langchain_core.messages import AIMessage, HumanMessage

from app.application.assistant.nodes import _build_chitchat_prompt_context
from app.prompts.prompts import CHITCHAT_PROMPT


def test_chitchat_prompt_contains_bounded_history_profile_and_current_question():
    context = _build_chitchat_prompt_context({
        "question": "总结一下这次对话",
        "gender": "female",
        "preference_tags": ["简约"],
        "messages": [
            HumanMessage(content="推荐一副耳机"),
            AIMessage(content="我推荐了三款耳机。"),
        ],
    })
    prompt = CHITCHAT_PROMPT.format(**context)

    assert "用户画像" in prompt
    assert "简约" in prompt
    assert "最近对话" in prompt
    assert "推荐一副耳机" in prompt
    assert "当前用户问题" in prompt
    assert "总结一下这次对话" in prompt
