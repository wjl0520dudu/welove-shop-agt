import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from app.domain.chitchat.agent import ChitchatAgent


def test_chitchat_agent_is_a_no_tool_agent_with_context_middleware(monkeypatch):
    captured = {}

    class FakeAgent:
        async def astream(self, state, config, stream_mode):
            captured["state"] = state
            captured["config"] = config
            captured["stream_mode"] = stream_mode
            yield "values", {"messages": [*state["messages"], AIMessage(content="你好呀")]}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr("app.domain.chitchat.agent.create_agent", fake_create_agent)
    monkeypatch.setattr(
        "app.domain.chitchat.agent.build_summarization_middleware",
        lambda *_args, **_kwargs: "summary-middleware",
    )

    async def run():
        result = await ChitchatAgent(object()).run(
            messages=[HumanMessage(content="你好")],
            system_prompt="你是聊天助手",
        )
        assert result["answer"] == "你好呀"

    asyncio.run(run())
    assert captured["tools"] == []
    assert captured["system_prompt"] == "你是聊天助手"
    assert captured["middleware"][0] == "summary-middleware"
    assert captured["stream_mode"] == ["values", "messages"]
