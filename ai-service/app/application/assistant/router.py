"""Structured Router result normalization.

Semantic understanding lives in the Router LLM.  This module deliberately
does not contain keyword routing, regular-expression intent matching, or
heuristic complex-task detection.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.application.assistant.schemas import IntentDecision


VALID_ROUTES = {"shopping", "knowledge", "chitchat", "unknown"}
VALID_MODES = {"simple", "complex"}


def normalize_llm_decision(decision: Any) -> IntentDecision:
    """Normalize a provider result into the Router's internal contract."""
    if isinstance(decision, IntentDecision):
        normalized = decision
    elif isinstance(decision, Mapping):
        normalized = IntentDecision.model_validate(dict(decision))
    else:
        normalized = IntentDecision(
            mode=str(getattr(decision, "mode", "simple") or "simple"),
            task_type=str(getattr(decision, "task_type", "unknown") or "unknown"),
            confidence=getattr(decision, "confidence", 0.0) or 0.0,
            reason=str(getattr(decision, "reason", "") or ""),
            canonical_question=str(getattr(decision, "canonical_question", "") or ""),
            resolved_product_ids=list(getattr(decision, "resolved_product_ids", []) or []),
            resolved_knowledge_entities=list(getattr(decision, "resolved_knowledge_entities", []) or []),
        )

    route = str(normalized.task_type).lower().strip()
    # ``cart`` is a historical schema value.  The main graph owns cart behavior
    # under ShoppingAgent and has no independent cart node.
    if route == "cart":
        route = "shopping"
    if route not in VALID_ROUTES:
        route = "unknown"

    mode = str(normalized.mode or "simple").lower().strip()
    if mode not in VALID_MODES:
        mode = "simple"
    if mode == "complex":
        route = "unknown"

    confidence = max(0.0, min(1.0, float(normalized.confidence or 0.0)))
    return IntentDecision(
        mode=mode,
        task_type=route,
        confidence=confidence,
        reason=str(normalized.reason or ""),
        canonical_question=str(normalized.canonical_question or "").strip(),
        resolved_product_ids=list(normalized.resolved_product_ids or []),
        resolved_knowledge_entities=list(normalized.resolved_knowledge_entities or []),
    )
