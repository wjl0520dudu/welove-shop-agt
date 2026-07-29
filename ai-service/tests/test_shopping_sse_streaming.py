import asyncio
from types import SimpleNamespace

from app.domain.shopping.agent import _compose_capability_answer


class _StreamingLLM:
    def __init__(self, chunks):
        self.chunks = chunks
        self.ainvoke_called = False

    async def astream(self, _messages):
        for chunk in self.chunks:
            yield SimpleNamespace(content=chunk)

    async def ainvoke(self, _messages):  # pragma: no cover - must not be used
        self.ainvoke_called = True
        raise AssertionError("SSE path must use astream instead of ainvoke")


def test_dispatched_recommendation_streams_real_llm_chunks_to_sink():
    received = []
    llm = _StreamingLLM(["第一", "款适合", "通勤。"])
    payload = {
        "product_cards": [
            {"title": "通勤耳机", "price": 299, "reason": "佩戴轻便"},
        ],
    }

    answer = asyncio.run(
        _compose_capability_answer(
            llm,
            "recommend",
            "推荐一款通勤耳机",
            payload,
            token_sink=received.append,
        )
    )

    assert received == ["第一", "款适合", "通勤。"]
    assert answer == "第一款适合通勤。"
    assert llm.ainvoke_called is False


def test_non_stream_run_keeps_ainvoke_compatibility():
    class _NonStreamingLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="完整回答")

    answer = asyncio.run(
        _compose_capability_answer(
            _NonStreamingLLM(),
            "recommend",
            "推荐耳机",
            {"product_cards": [{"title": "耳机", "price": 199}]},
        )
    )

    assert answer == "完整回答"
