"""No-tool conversational Agent with bounded long-context handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk

from app.infrastructure.llm.middleware import build_summarization_middleware


class ChitchatAgent:
    """Handle natural conversation and conversation review without business tools.

    The parent AssistantGraph remains the owner of persisted conversation state.
    This Agent receives that state as messages and uses LangChain's
    ``SummarizationMiddleware`` only to compact the model input for a long turn.
    It deliberately has no independent checkpointer: a child-local history would
    miss Shopping/Knowledge turns and could diverge from chat-service history.
    """

    def __init__(self, llm: Any):
        self._llm = llm

    async def run(
        self,
        *,
        messages: list,
        system_prompt: str,
        token_sink: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Generate one natural reply from the supplied conversation messages."""
        agent = create_agent(
            model=self._llm,
            tools=[],
            system_prompt=system_prompt,
            middleware=[
                # Triggers only for genuinely long inputs.  The summary is an
                # input-time compression, while the parent graph/chat-service
                # remains authoritative for durable conversation history.
                build_summarization_middleware(self._llm),
                ModelCallLimitMiddleware(run_limit=2, exit_behavior="end"),
            ],
        )
        result: dict[str, Any] = {}
        async for event in agent.astream(
            {"messages": messages},
            config={"recursion_limit": 6},
            stream_mode=["values", "messages"],
        ):
            mode, payload = event
            if mode == "values" and isinstance(payload, dict):
                result = payload
            elif mode == "messages" and token_sink is not None:
                message, _metadata = payload
                if isinstance(message, AIMessageChunk):
                    text = _text_content(message.content)
                    if text:
                        token_sink(text)
        answer = _last_ai_text(result.get("messages") or [])
        return {"answer": answer, "messages": result.get("messages") or []}


def _last_ai_text(messages: list) -> str:
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""
