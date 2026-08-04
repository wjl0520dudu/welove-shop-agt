"""LangSmith run configuration for the multi-agent assistant.

LangSmith automatically traces LangChain/LangGraph runnables when tracing is
enabled through environment variables.  This module adds the application
context that automatic tracing cannot infer: a stable request name, useful
agent tags, and metadata that is safe to upload to an observability service.

Do not put prompts, chat history, API keys, JWTs, phone numbers, or raw user
identifiers in ``metadata``.  Runnable inputs are governed separately by the
``LANGSMITH_HIDE_INPUTS`` / ``LANGSMITH_HIDE_OUTPUTS`` configuration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


def build_assistant_run_config(
    *,
    conversation_id: str | None,
    user_id: int | str | None,
    trace_id: str | None,
    stream: bool,
    has_image: bool,
    environment: str | None = None,
    evaluation_context: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the root config for exactly one assistant request.

    ``thread_id`` remains the real conversation ID because LangGraph's
    checkpointer needs it for state isolation.  The metadata contains only a
    one-way compact fingerprint so it remains useful without exposing the
    original business identifier in the LangSmith UI.
    """

    tags = [
        "welove-shop-ai",
        "multi-agent",
        "entry:assistant-api",
        "transport:sse" if stream else "transport:sync",
        "input:image" if has_image else "input:text",
    ]
    if str(environment or "").strip():
        tags.append(f"env:{str(environment).strip()}")
    evaluation_metadata = {
        f"evaluation_{key}": str(value).strip()
        for key, value in dict(evaluation_context or {}).items()
        if str(key).strip() and str(value).strip()
    }
    if evaluation_metadata:
        tags.append("evaluation:golden-dataset")
    metadata = {
        "request_ref": _fingerprint(trace_id),
        "conversation_ref": _fingerprint(conversation_id),
        "user_ref": _fingerprint(user_id),
        "stream": stream,
        "has_image": has_image,
        "environment": str(environment).strip() if environment else None,
        **evaluation_metadata,
    }
    return {
        "run_name": "assistant.request",
        "tags": tags,
        "metadata": {key: value for key, value in metadata.items() if value is not None},
        "configurable": {"thread_id": str(conversation_id or "anonymous")},
    }


def child_run_config(
    parent: Mapping[str, Any] | None,
    *,
    run_name: str,
    tags: list[str] | tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
    thread_id: str | None = None,
    recursion_limit: int | None = None,
) -> dict[str, Any]:
    """Derive a child RunnableConfig without dropping callbacks or tags.

    Inner DeepAgent graphs use isolated checkpointer threads, but inherit the
    root callbacks through this config.  That is what makes an Agent/tool run
    appear beneath the originating assistant request in LangSmith rather than
    as a detached trace.
    """

    inherited = dict(parent or {})
    inherited_tags = list(inherited.get("tags") or [])
    for tag in tags:
        if tag and tag not in inherited_tags:
            inherited_tags.append(tag)

    inherited_metadata = dict(inherited.get("metadata") or {})
    inherited_metadata.update({
        key: value
        for key, value in dict(metadata or {}).items()
        if value is not None
    })
    configurable = dict(inherited.get("configurable") or {})
    if thread_id is not None:
        configurable["thread_id"] = thread_id

    inherited.update({
        "run_name": run_name,
        "tags": inherited_tags,
        "metadata": inherited_metadata,
        "configurable": configurable,
    })
    if recursion_limit is not None:
        inherited["recursion_limit"] = recursion_limit
    return inherited


def _fingerprint(value: object | None) -> str | None:
    """Return a short stable reference suitable for tracing metadata."""

    text = str(value or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
