"""No-tool conversational Agent with bounded long-context handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware.model_call_limit import ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableConfig

from app.infrastructure.observability.langsmith import child_run_config


class ChitchatAgent:
    """Handle natural conversation and conversation review without business tools.

    The parent AssistantGraph remains the owner of persisted conversation state.
    This Agent receives the same already-compressed visible messages as Router.
    It deliberately has no independent checkpointer or summarization middleware:
    a child-local summary could diverge from chat-service's persisted summary.
    """

    def __init__(self, llm: Any):
        self._llm = llm

    async def run(
        self,
        *,
        messages: list,
        system_prompt: str,
        token_sink: Callable[[str], None] | None = None,
        run_config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        """Generate one natural reply from the supplied conversation messages."""
        agent = create_agent(
            model=self._llm,
            tools=[],
            system_prompt=system_prompt,
            middleware=[
                ModelCallLimitMiddleware(run_limit=2, exit_behavior="end"),
            ],
        )
        result: dict[str, Any] = {}
        async for event in agent.astream(
            {"messages": messages},
            config=child_run_config(
                run_config,
                run_name="chitchat-agent.tool-loop",
                tags=["runtime:langchain-agent"],
                recursion_limit=6,
            ),
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
