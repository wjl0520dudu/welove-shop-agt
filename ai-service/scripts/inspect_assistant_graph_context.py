"""Run or inspect the current AssistantGraph and export its context as JSON.

This is a diagnostic tool for conversation-memory design.  It does not alter
the graph implementation.  A normal run uses a freshly generated
``conversation_id`` unless ``--conversation-id`` is explicitly supplied.

The exported JSON makes three layers comparable:

1. ``conversation_history`` supplied by chat-service / the caller;
2. the initial ``AssistantState[\"messages\"]`` before graph execution;
3. the final Checkpointer ``messages`` after graph execution.

Run from ``ai-service``:

    python scripts/inspect_assistant_graph_context.py \
      --question "推荐几款适合通勤的耳机"

To inspect a second turn in the same runtime conversation:

    python scripts/inspect_assistant_graph_context.py \
      --conversation-id ctx-inspect-demo \
      --question "第一款和第三款呢？"

Passing an existing production-like conversation id will append a diagnostic
turn to that LangGraph thread.  Use a dedicated id for diagnosis.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


SCRIPT_DIR = Path(__file__).resolve().parent
AI_SERVICE_ROOT = SCRIPT_DIR.parent
if str(AI_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行或读取 AssistantGraph，并导出上下文消息诊断 JSON。",
    )
    parser.add_argument("--question", default="", help="本轮问题；非 --inspect-only 时必填")
    parser.add_argument(
        "--conversation-id",
        default="",
        help="LangGraph thread_id；未指定时自动生成隔离的诊断会话 ID",
    )
    parser.add_argument("--user-id", default="", help="可选用户 ID")
    parser.add_argument(
        "--history-file",
        type=Path,
        help="可选 JSON 文件，内容必须是 conversation_history 数组",
    )
    parser.add_argument("--image-url", default="", help="可选图片 URL")
    parser.add_argument(
        "--run-timeout-seconds",
        type=float,
        default=60.0,
        help="真实运行图的总超时秒数；超时仍会写出 JSON（默认 60）",
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="不运行新问题，只读取该 conversation_id 当前 Checkpointer 状态",
    )
    parser.add_argument(
        "--content-limit",
        type=int,
        default=600,
        help="每条消息写入 JSON 的最大字符数；设为 0 输出完整内容（默认 600）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出 JSON 文件路径；默认写到 ai-service/tmp_debug/",
    )
    return parser.parse_args()


def _load_history(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"无法读取 history 文件：{path}：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"history 文件不是有效 JSON：{path}：{exc}") from exc
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise SystemExit("history 文件必须是由消息对象组成的 JSON 数组")
    return [dict(item) for item in value]


def _jsonable(value: Any) -> Any:
    """Keep diagnostic output serializable without dropping useful shape."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except Exception:  # noqa: BLE001 - diagnostics must never fail on one field
            pass
    return str(value)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(_jsonable(content), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(content)


def _preview(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


def _message_category(message: Any) -> str:
    """Classify message shape; it intentionally does not guess semantics."""
    type_name = type(message).__name__
    if type_name == "HumanMessage":
        return "visible_user"
    if type_name == "ToolMessage":
        return "internal_tool_result"
    if type_name == "SystemMessage":
        return "system_instruction"
    if type_name == "AIMessage":
        if getattr(message, "tool_calls", None):
            return "internal_ai_tool_call"
        return "assistant_or_internal_ai"
    return "other"


def _message_record(index: int, message: Any, content_limit: int) -> dict[str, Any]:
    content, truncated = _preview(_content_text(getattr(message, "content", "")), content_limit)
    tool_calls = _jsonable(getattr(message, "tool_calls", None) or [])
    return {
        "index": index,
        "message_type": type(message).__name__,
        "category": _message_category(message),
        "id": getattr(message, "id", None),
        "name": getattr(message, "name", None),
        "tool_call_id": getattr(message, "tool_call_id", None),
        "has_tool_calls": bool(tool_calls),
        "tool_calls": tool_calls,
        "content": content,
        "content_truncated": truncated,
        "content_chars": len(_content_text(getattr(message, "content", ""))),
    }


def _messages_report(messages: Any, content_limit: int) -> dict[str, Any]:
    records = [
        _message_record(index, message, content_limit)
        for index, message in enumerate(messages or [])
    ]
    return {
        "count": len(records),
        "by_category": dict(Counter(item["category"] for item in records)),
        "by_message_type": dict(Counter(item["message_type"] for item in records)),
        "items": records,
    }


def _history_record(index: int, message: Mapping[str, Any], content_limit: int) -> dict[str, Any]:
    content, truncated = _preview(_content_text(message.get("content") or ""), content_limit)
    cards = message.get("product_cards") or message.get("productCards") or []
    return {
        "index": index,
        "id": message.get("id"),
        "role": message.get("role"),
        "content": content,
        "content_truncated": truncated,
        "content_chars": len(_content_text(message.get("content") or "")),
        "image_url": message.get("image_url") or message.get("imageUrl") or "",
        "product_card_count": len(cards) if isinstance(cards, list) else 0,
        "task_type": message.get("task_type") or message.get("taskType") or "",
    }


def _history_report(history: list[Mapping[str, Any]], content_limit: int) -> dict[str, Any]:
    records = [_history_record(index, message, content_limit) for index, message in enumerate(history)]
    return {
        "count": len(records),
        "by_role": dict(Counter(str(item["role"] or "unknown") for item in records)),
        "items": records,
    }


def _business_memory_summary(memory: Any) -> dict[str, Any]:
    if not isinstance(memory, Mapping):
        return {}
    cards = memory.get("last_product_cards") or []
    active_set = memory.get("active_product_set") or {}
    return {
        "keys": sorted(str(key) for key in memory.keys()),
        "last_product_card_count": len(cards) if isinstance(cards, list) else 0,
        "selected_product_ids": _jsonable(memory.get("selected_product_ids") or []),
        "active_product_set": _jsonable(active_set),
        "resolved_knowledge_entities": _jsonable(memory.get("resolved_knowledge_entities") or []),
    }


def _state_overview(state: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "question",
        "canonical_question",
        "route",
        "route_source",
        "route_confidence",
        "route_reason",
        "task_type",
        "orchestrator_mode",
        "orchestrator_reason",
        "input_mode",
        "error",
        "error_code",
    )
    overview = {key: _jsonable(state.get(key)) for key in keys if key in state}
    overview["context_resolution"] = _jsonable(state.get("context_resolution") or {})
    overview["business_memory"] = _business_memory_summary(state.get("business_memory"))
    return overview


async def _inspect(args: argparse.Namespace) -> dict[str, Any]:
    from app.application.assistant.graph import AssistantGraph
    from app.infrastructure.llm.llm import get_llm
    from app.infrastructure.observability.langsmith import build_assistant_run_config
    from app.infrastructure.persistence.runtime import close_runtime, init_runtime, is_persistent

    conversation_id = args.conversation_id.strip() or f"context-inspect-{uuid4().hex[:12]}"
    user_id: int | str | None = args.user_id.strip() or None
    history = _load_history(args.history_file)
    trace_id = str(uuid4())

    try:
        print("[1/3] 初始化 LangGraph Runtime…", flush=True)
        initialized = await init_runtime()
        llm = get_llm()
        if llm is None and not args.inspect_only:
            raise SystemExit("LLM 未配置，无法运行图；可使用 --inspect-only 仅读取 Checkpointer。")

        assistant = AssistantGraph(llm)
        run_config = build_assistant_run_config(
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            stream=False,
            has_image=bool(args.image_url.strip()),
        )

        initial_state: Mapping[str, Any] = {}
        final_state: Mapping[str, Any] = {}
        run_error: str | None = None

        if not args.inspect_only:
            print(
                f"[2/3] 运行图：conversation_id={conversation_id}，"
                f"timeout={args.run_timeout_seconds:g}s…",
                flush=True,
            )
            initial_state, _, _ = assistant._make_initial_state(
                question=args.question,
                conversation_id=conversation_id,
                user_id=user_id,
                conversation_history=history,
                image_url=args.image_url.strip() or None,
                trace_id=trace_id,
            )
            await assistant._sync_request_profile(initial_state)
            await assistant._refresh_runtime_messages(initial_state, run_config)
            try:
                final_state = await asyncio.wait_for(
                    assistant.graph.ainvoke(initial_state, config=run_config),
                    timeout=max(1.0, args.run_timeout_seconds),
                )
            except TimeoutError:
                run_error = (
                    "TimeoutError: graph execution exceeded "
                    f"{args.run_timeout_seconds:g} seconds"
                )
            except Exception as exc:  # noqa: BLE001 - report graph failures in the JSON
                run_error = f"{type(exc).__name__}: {exc}"

        print("[3/3] 读取该会话的 Checkpointer 状态…", flush=True)
        checkpoint = await assistant.graph.aget_state(run_config)
        checkpoint_values = dict(getattr(checkpoint, "values", {}) or {})
        checkpoint_metadata = dict(getattr(checkpoint, "metadata", {}) or {})

        return {
            "generated_at": datetime.now().astimezone().isoformat(),
            "purpose": "AssistantGraph context inspection; no graph implementation was changed.",
            "request": {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "question": args.question,
                "image_url": args.image_url.strip(),
                "inspect_only": args.inspect_only,
                "run_timeout_seconds": args.run_timeout_seconds,
                "history_file": str(args.history_file) if args.history_file else None,
            },
            "runtime": {
                "init_runtime_returned": initialized,
                "persistent_checkpointer": is_persistent(),
                "thread_id": str((run_config.get("configurable") or {}).get("thread_id") or ""),
            },
            "supplied_conversation_history": _history_report(history, args.content_limit),
            "initial_state": {
                "overview": _state_overview(initial_state),
                "messages": _messages_report(initial_state.get("messages") or [], args.content_limit),
            },
            "final_graph_state": {
                "run_error": run_error,
                "overview": _state_overview(final_state),
                "messages": _messages_report(final_state.get("messages") or [], args.content_limit),
            },
            "checkpoint_after_run": {
                "available": bool(checkpoint_values),
                "created_at": str(getattr(checkpoint, "created_at", "") or ""),
                "next": _jsonable(getattr(checkpoint, "next", ()) or ()),
                "metadata": _jsonable(checkpoint_metadata),
                "overview": _state_overview(checkpoint_values),
                "messages": _messages_report(checkpoint_values.get("messages") or [], args.content_limit),
            },
        }
    finally:
        await close_runtime()


async def _main() -> int:
    args = _parse_args()
    if not args.inspect_only and not args.question.strip():
        print(
            "运行模式需要提供 --question。示例：\n"
            "  python inspect_assistant_graph_context.py "
            "--conversation-id context-check-01 --question \"你好\"\n"
            "如只读取已有 Checkpointer，请使用：\n"
            "  python inspect_assistant_graph_context.py "
            "--inspect-only --conversation-id <conversation_id>",
            file=sys.stderr,
        )
        return 2
    if args.inspect_only and not args.conversation_id.strip():
        print("--inspect-only 必须同时提供 --conversation-id。", file=sys.stderr)
        return 2
    report = await _inspect(args)
    conversation_id = str(report["request"]["conversation_id"])
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or (AI_SERVICE_ROOT / "tmp_debug" / f"context-inspection-{conversation_id}-{timestamp}.json")
    output = output if output.is_absolute() else (AI_SERVICE_ROOT / output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_jsonable), encoding="utf-8")

    checkpoint_messages = report["checkpoint_after_run"]["messages"]
    print(f"JSON 报告已写入：{output}")
    print("Checkpointer messages："
          f"{checkpoint_messages['count']} 条，"
          f"分类={json.dumps(checkpoint_messages['by_category'], ensure_ascii=False)}")
    if report["final_graph_state"]["run_error"]:
        print(f"图运行失败（详情已写入 JSON）：{report['final_graph_state']['run_error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
