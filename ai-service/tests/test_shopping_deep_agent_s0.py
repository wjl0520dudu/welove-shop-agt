"""Phase S0 compatibility tests for Deep Agents before Shopping migration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import ToolRuntime
from pydantic import PrivateAttr

from app.application.assistant.state import ShoppingAgentState
from app.domain.shopping.deep_agent_runtime import (
    SHOPPING_BLOCKED_BUILTIN_TOOLS,
    SHOPPING_DEEPAGENTS_VERSION,
    SHOPPING_SKILL_SOURCE,
    ShoppingDeepAgentToolSurfaceMiddleware,
    shopping_skill_permissions,
    validate_shopping_deepagents_runtime,
)
from app.domain.shopping.tool_guard import (
    RequireInitialShoppingToolMiddleware,
    ShoppingToolGuardMiddleware,
)


class _RecordingToolBoundModel(FakeMessagesListChatModel):
    """Fake model that records final prompts and bound tool surfaces."""

    _message_calls: list[list[Any]] = PrivateAttr(default_factory=list)
    _tool_bindings: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    @property
    def message_calls(self) -> list[list[Any]]:
        return self._message_calls

    @property
    def tool_bindings(self) -> list[dict[str, Any]]:
        return self._tool_bindings

    def bind_tools(self, tools, **kwargs):
        self._tool_bindings.append({
            "names": tuple(_bound_tool_name(tool) for tool in tools),
            "tool_choice": kwargs.get("tool_choice"),
        })
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._message_calls.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def _bound_tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or (tool.get("function") or {}).get("name") or "")
    return str(getattr(tool, "name", "") or "")


def _write_test_skill(root: Path) -> None:
    skill = root / "skills" / "shopping-agent" / "s0-echo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        """---
name: s0-echo
description: Use for the Phase S0 Deep Agents compatibility echo task.
---

# S0 Echo

Call `s0_echo_tool` once and return its grounded result.
""",
        encoding="utf-8",
    )


@tool("s0_echo_tool", description="Return request-scoped state for Phase S0.")
async def _s0_echo_tool(query: str, runtime: ToolRuntime) -> dict:
    return {
        "query": query,
        "conversation_id": runtime.state.get("conversation_id"),
        "selected_product_ids": runtime.state.get("selected_product_ids") or [],
    }


_RECOMMEND_EXECUTIONS: list[str] = []


@tool("recommend_products", description="Return one grounded S0 recommendation.")
async def _s0_recommend_products(query: str) -> dict:
    _RECOMMEND_EXECUTIONS.append(query)
    return {
        "action": "recommend",
        "product_cards": [{"product_id": 7, "title": "S0 测试耳机"}],
    }


def _tool_call(name: str, call_id: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": name, "args": args}],
    )


def test_deepagents_version_is_the_phase_s0_pin():
    assert validate_shopping_deepagents_runtime() == SHOPPING_DEEPAGENTS_VERSION


def test_deep_agent_reads_skill_calls_tool_streams_and_preserves_state():
    async def run(test_root: Path):
        _write_test_skill(test_root)
        model = _RecordingToolBoundModel(responses=[
            _tool_call(
                "read_file",
                "read-skill",
                {"file_path": "/skills/shopping-agent/s0-echo/SKILL.md"},
            ),
            _tool_call("s0_echo_tool", "echo", {"query": "验证 S0"}),
            AIMessage(content="S0 最小链路完成。"),
        ])
        surface = ShoppingDeepAgentToolSurfaceMiddleware({"s0_echo_tool"})
        checkpointer = InMemorySaver()
        agent = create_deep_agent(
            model=model,
            tools=[_s0_echo_tool],
            system_prompt="Read the matching Shopping Skill before using a business tool.",
            skills=[SHOPPING_SKILL_SOURCE],
            backend=FilesystemBackend(root_dir=test_root, virtual_mode=True),
            permissions=shopping_skill_permissions(),
            middleware=[surface],
            subagents=[],
            state_schema=ShoppingAgentState,
            checkpointer=checkpointer,
            name="shopping-s0-test",
        )
        config = {"configurable": {"thread_id": "shopping-s0-stream"}}
        latest: dict[str, Any] = {}
        streamed_text: list[str] = []
        async for mode, payload in agent.astream(
            {
                "messages": [HumanMessage(content="执行 S0 echo")],
                "conversation_id": "conversation-s0",
                "selected_product_ids": [11, 13],
            },
            config=config,
            stream_mode=["values", "messages"],
        ):
            if mode == "values":
                latest = payload
            elif mode == "messages":
                message, _metadata = payload
                # Real providers emit AIMessageChunk; LangChain's deterministic
                # fake model emits a complete AIMessage on the same stream.
                if isinstance(message, (AIMessageChunk, AIMessage)) and message.content:
                    streamed_text.append(str(message.content))

        tool_messages = [
            message for message in latest["messages"] if isinstance(message, ToolMessage)
        ]
        skill_result = next(message for message in tool_messages if message.name == "read_file")
        echo_result = next(message for message in tool_messages if message.name == "s0_echo_tool")
        echo_payload = json.loads(str(echo_result.content))

        assert "name: s0-echo" in str(skill_result.content)
        assert echo_payload == {
            "query": "验证 S0",
            "conversation_id": "conversation-s0",
            "selected_product_ids": [11, 13],
        }
        assert "S0 最小链路完成。" in "".join(streamed_text)
        assert await checkpointer.aget(config) is not None

        visible_names = {name for snapshot in surface.visible_tool_snapshots for name in snapshot}
        assert visible_names == {"read_file", "s0_echo_tool"}
        assert not (visible_names & SHOPPING_BLOCKED_BUILTIN_TOOLS)

        available_names = {
            name for snapshot in surface.available_tool_snapshots for name in snapshot
        }
        assert {
            "ls",
            "read_file",
            "write_file",
            "edit_file",
            "delete",
            "glob",
            "grep",
            "task",
            "s0_echo_tool",
        }.issubset(available_names)

        system_text = "\n".join(
            str(message.content)
            for call in model.message_calls
            for message in call
            if getattr(message, "type", "") == "system"
        )
        assert "s0-echo" in system_text
        assert "Phase S0 Deep Agents compatibility echo task" in system_text

    with TemporaryDirectory(prefix=".shopping-s0-", dir=Path.cwd()) as temp_dir:
        asyncio.run(run(Path(temp_dir)))


def test_existing_shopping_guard_reuses_identical_business_tool_after_skill_read():
    async def run(test_root: Path):
        _write_test_skill(test_root)
        _RECOMMEND_EXECUTIONS.clear()
        model = _RecordingToolBoundModel(responses=[
            _tool_call(
                "read_file",
                "read-skill",
                {"file_path": "/skills/shopping-agent/s0-echo/SKILL.md"},
            ),
            _tool_call("recommend_products", "recommend-1", {"query": "推荐通勤耳机"}),
            _tool_call("recommend_products", "recommend-2", {"query": "推荐通勤耳机"}),
            AIMessage(content="已根据真实工具结果完成推荐。"),
        ])
        surface = ShoppingDeepAgentToolSurfaceMiddleware({"recommend_products"})
        guard = ShoppingToolGuardMiddleware()
        agent = create_deep_agent(
            model=model,
            tools=[_s0_recommend_products],
            skills=[SHOPPING_SKILL_SOURCE],
            backend=FilesystemBackend(root_dir=test_root, virtual_mode=True),
            permissions=shopping_skill_permissions(),
            middleware=[
                RequireInitialShoppingToolMiddleware(),
                guard,
                surface,
            ],
            subagents=[],
            state_schema=ShoppingAgentState,
            checkpointer=InMemorySaver(),
            name="shopping-s0-guard-test",
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="推荐通勤耳机")]},
            config={"configurable": {"thread_id": "shopping-s0-guard"}},
        )

        assert _RECOMMEND_EXECUTIONS == ["推荐通勤耳机"]
        assert any(record["status"] == "deduplicated" for record in guard.records)
        assert isinstance(result["messages"][-1], AIMessage)
        assert result["messages"][-1].content == "已根据真实工具结果完成推荐。"

        # Reading a Skill is not a product fact result.  The middleware must
        # continue requiring a real Shopping business tool until the first
        # recommendation result has returned.
        tool_choices = [binding["tool_choice"] for binding in model.tool_bindings]
        assert tool_choices[:3] == ["required", "required", None]

    with TemporaryDirectory(prefix=".shopping-s0-", dir=Path.cwd()) as temp_dir:
        asyncio.run(run(Path(temp_dir)))
