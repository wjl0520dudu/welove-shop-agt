"""Turn-level context resolution for the assistant graph.

This module deliberately does *not* decide business intent or execute tools.  It
turns persisted chat artifacts into a small, scoped context snapshot before the
router and child agents run.  This prevents a later recommendation from silently
overwriting the product set referred to by "这两款".
"""
from __future__ import annotations

from typing import Any, Mapping


def _as_cards(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    cards = message.get("product_cards") or message.get("productCards") or []
    return [dict(card) for card in cards if isinstance(card, Mapping)]


def _latest_product_artifact(history: list[Mapping[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Return the nearest assistant message that actually rendered cards."""
    for message in reversed(history):
        if str(message.get("role") or "") != "assistant":
            continue
        cards = _as_cards(message)
        if cards:
            return dict(message), cards
    return None, []


def resolve_turn_context(
    *,
    question: str,
    conversation_history: list[Mapping[str, Any]] | None,
    business_memory: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Prepare a bounded context snapshot for the LLM router.

    This function intentionally does no linguistic work: no regular-expression
    reference detection, product selection, intent inference, or clarification.
    Its sole job is to expose the latest rendered product set as an authoritative
    candidate set.  The structured Intent Router is responsible for deciding
    whether words such as “第一款” or “它们” refer to it.
    """
    history = list(conversation_history or [])
    memory = dict(business_memory or {})
    artifact, cards = _latest_product_artifact(history)
    result: dict[str, Any] = {
        "has_reference": False,
        "reference_source": "none",
        "reference_message_id": None,
        "resolved_product_ids": [],
        "needs_clarification": False,
        "clarification": "",
    }
    source = "message_artifact"
    if not cards:
        cards = [
            dict(card) for card in (memory.get("last_product_cards") or [])
            if isinstance(card, Mapping)
        ]
        source = "store_fallback"
    if not cards:
        return {"business_memory": memory, "context_resolution": result}

    # Persisted card artifacts are more trustworthy than the mutable Store slot.
    # Keep the complete sequence intact; selecting a subset is an LLM router
    # decision and happens only after its IDs are validated against this set.
    memory["last_product_cards"] = cards
    memory["active_product_set"] = {
        "source_message_id": artifact.get("id") if artifact else None,
        "source_type": "multimodal_retrieval" if artifact and artifact.get("image_url") else "recommendation",
        "product_ids": [card.get("product_id") or card.get("id") for card in cards],
    }
    result.update({
        "reference_source": source,
        "reference_message_id": artifact.get("id") if artifact else None,
        "candidate_product_ids": memory["active_product_set"]["product_ids"],
    })
    return {"business_memory": memory, "context_resolution": result}
