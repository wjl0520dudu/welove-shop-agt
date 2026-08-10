from langchain_core.messages import AIMessage, HumanMessage

from app.application.assistant.nodes import _build_chitchat_prompt_context
from app.prompts.prompts import CHITCHAT_PROMPT


def test_chitchat_prompt_delegates_history_to_agent_messages_and_includes_profile():
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
    assert "对话消息" in prompt
    assert "完整的会话消息会作为本次 Agent 的 messages 单独提供" in prompt
    assert "当前用户问题" in prompt
    assert "总结一下这次对话" in prompt
