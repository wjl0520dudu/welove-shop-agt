"""Low-cost, auditable intent-routing helpers.

The main graph uses a conservative three-stage policy:

1. high-certainty deterministic rules;
2. structured LLM routing for unresolved requests;
3. an ``unknown`` clarification fallback for low-confidence output.

Rules intentionally cover only clear cases. Ambiguous, contextual, or mixed
expressions are left to the LLM instead of being forced into a business agent.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.application.assistant.schemas import IntentDecision

VALID_ROUTES = {"shopping", "knowledge", "chitchat", "unknown"}

_META_PATTERNS = (
    "刚才问", "刚才说", "刚才聊", "还记得", "回顾一下", "总结一下",
    "总结我们的对话", "我叫什么", "你是谁", "你能做什么",
)
_GREETING_RE = re.compile(
    r"^(你好|您好|哈喽|嗨|hello|hi|在吗|谢谢|多谢|辛苦了|再见|拜拜)[！!。.，,\s]*$",
    re.IGNORECASE,
)
_SHOPPING_PATTERNS = (
    "推荐", "帮我找", "帮我选", "搜一下", "搜索", "找商品", "找一款", "找几款",
    "找同款", "找相似", "对比", "比较", "哪个好", "哪款好", "性价比",
    "排行榜", "销量", "评分", "多少钱", "价格", "库存", "有货", "缺货",
    "加入购物车", "加购物车", "加购", "下单", "购买", "想买", "买一", "怎么买",
)
_KNOWLEDGE_PATTERNS = (
    "成分", "功效", "作用", "原理", "副作用", "禁忌", "注意事项",
    "怎么用", "如何使用", "用法", "区别", "为什么", "是什么", "什么意思",
    "能不能", "可以吗", "是否可以", "是否适合", "适合什么", "适合哪种", "怎么选",
    "搭配", "浓度", "机制", "科普",
)
_PRODUCT_REFERENCE_PATTERNS = (
    "它多少钱", "更便宜", "评分更高", "销量更高", "还有别的",
    "其他颜色", "什么价格", "什么规格", "有库存",
)
_NEUTRAL_REFERENCE_PATTERNS = (
    "第一个", "第二个", "第三个", "最后一个", "这个", "那个", "这款", "那款",
    "刚才那个", "刚刚那个", "上一个", "它怎么样", "它们怎么样",
)
_KNOWLEDGE_REFERENCE_PATTERNS = (
    "它的成分", "它们的成分", "它的功效", "它们的功效", "它的副作用",
    "它们的副作用", "怎么搭配", "怎么使用", "浓度多少", "原理是什么",
)
_COMPOUND_MARKERS = (
    "然后", "顺便", "另外", "同时", "并且", "以及", "还要", "再帮我",
    "再问", "除此之外", "一并", "分别", "并告诉", "并介绍", "并说明", "并分析",
    "并解释", "并回答",
)
_MULTI_TARGET_PATTERNS = (
    re.compile(r"各\s*[一1]\s*(?:款|个|台|双|杯|盒|件)"),
    re.compile(r"[一1]\s*(?:款|个|台|双|杯|盒|件).{0,30}[、，,和].{0,30}[一1]\s*(?:款|个|台|双|杯|盒|件)"),
)
# Pattern: "{product_name}的{attribute}" — explicit product + detail aspect.
# e.g. "小棕瓶的成分是什么", "雅诗兰黛小棕瓶的功效".
# Though the attribute word ("成分"/"功效") lives in _KNOWLEDGE_PATTERNS,
# the "的" binding makes this a product-specific inquiry → shopping/detail.
_PRODUCT_ATTRIBUTE_QUERY = re.compile(
    r".{2,6}的(成分|功效|作用|原理|用法|浓度|副作用|禁忌)"
)


@dataclass(frozen=True)
class RuleRouteDecision:
    route: str = "unknown"
    confidence: float = 0.0
    reason: str = "rule: no high-certainty match"
    matched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_high_confidence_rule(
    question: str,
    business_memory: Mapping[str, Any] | None = None,
    *,
    has_image: bool = False,
) -> RuleRouteDecision:
    """Classify only deterministic cases; return unmatched for ambiguity."""
    text = (question or "").strip()
    lowered = text.lower()
    memory = business_memory or {}

    if has_image:
        return RuleRouteDecision(
            route="shopping",
            confidence=1.0,
            reason="rule:image present -> shopping multimodal branch",
            matched=True,
        )
    if not text:
        return RuleRouteDecision(
            route="unknown",
            confidence=1.0,
            reason="rule:empty question",
            matched=True,
        )
    if any(pattern in lowered for pattern in _META_PATTERNS):
        return RuleRouteDecision(
            route="chitchat",
            confidence=0.98,
            reason="rule:conversation meta question",
            matched=True,
        )
    if _GREETING_RE.fullmatch(text):
        return RuleRouteDecision(
            route="chitchat",
            confidence=0.99,
            reason="rule:standalone greeting or courtesy",
            matched=True,
        )

    has_cards = bool(memory.get("last_product_cards") or memory.get("last_focused_product"))
    has_entities = bool(memory.get("last_knowledge_entities"))
    product_reference = any(pattern in lowered for pattern in _PRODUCT_REFERENCE_PATTERNS)
    knowledge_reference = any(pattern in lowered for pattern in _KNOWLEDGE_REFERENCE_PATTERNS)
    neutral_reference = any(pattern in lowered for pattern in _NEUTRAL_REFERENCE_PATTERNS)
    shopping_hits = [p for p in _SHOPPING_PATTERNS if p in lowered]
    knowledge_hits = [p for p in _KNOWLEDGE_PATTERNS if p in lowered]

    # Domain-specific reference words are stronger than generic keyword matches.
    if has_cards and product_reference and not knowledge_reference and not knowledge_hits:
        return RuleRouteDecision(
            route="shopping",
            confidence=0.96,
            reason="rule:reference to previous product cards",
            matched=True,
        )
    if has_entities and (knowledge_reference or knowledge_hits) and not shopping_hits:
        return RuleRouteDecision(
            route="knowledge",
            confidence=0.96,
            reason="rule:reference to previous knowledge entities",
            matched=True,
        )
    if neutral_reference and has_cards and not has_entities and not knowledge_hits:
        return RuleRouteDecision(
            route="shopping",
            confidence=0.93,
            reason="rule:neutral reference with product-only memory",
            matched=True,
        )
    if neutral_reference and has_entities and not has_cards and not shopping_hits:
        return RuleRouteDecision(
            route="knowledge",
            confidence=0.93,
            reason="rule:neutral reference with knowledge-only memory",
            matched=True,
        )

    # A query like "小棕瓶的成分是什么" explicitly names a product + its
    # attribute via "的".  Route to shopping (detail) even though the
    # attribute word appears in _KNOWLEDGE_PATTERNS.
    if _PRODUCT_ATTRIBUTE_QUERY.search(lowered):
        return RuleRouteDecision(
            route="shopping",
            confidence=0.95,
            reason="rule:product attribute inquiry with explicit product reference",
            matched=True,
        )

    # Mixed signals require context/semantic reasoning. Do not guess with rules.
    if shopping_hits and knowledge_hits:
        return RuleRouteDecision(
            reason=(
                "rule:mixed shopping and knowledge signals; defer to structured router "
                f"(shopping={shopping_hits[:2]}, knowledge={knowledge_hits[:2]})"
            ),
        )
    if shopping_hits:
        return RuleRouteDecision(
            route="shopping",
            confidence=0.94,
            reason=f"rule:high-certainty shopping signal {shopping_hits[0]}",
            matched=True,
        )
    if knowledge_hits:
        return RuleRouteDecision(
            route="knowledge",
            confidence=0.94,
            reason=f"rule:high-certainty knowledge signal {knowledge_hits[0]}",
            matched=True,
        )

    return RuleRouteDecision()


def can_short_circuit_orchestrator(question: str, *, has_image: bool = False) -> bool:
    """Whether an obviously single-intent request can skip the planner LLM."""
    text = (question or "").strip()
    if any(marker in text for marker in _COMPOUND_MARKERS) or any(pattern.search(text) for pattern in _MULTI_TARGET_PATTERNS):
        return False
    if has_image:
        # A plain image lookup is deterministic. Image + explicit knowledge wording
        # may contain multiple tasks and must still be inspected by Orchestrator.
        lowered = text.lower()
        return not text or not any(pattern in lowered for pattern in _KNOWLEDGE_PATTERNS)
    return classify_high_confidence_rule(text).matched


def normalize_llm_decision(decision: Any) -> IntentDecision:
    """Normalize dict/Pydantic router output and keep it inside graph routes."""
    if isinstance(decision, IntentDecision):
        normalized = decision
    elif isinstance(decision, Mapping):
        normalized = IntentDecision.model_validate(dict(decision))
    else:
        normalized = IntentDecision(
            task_type=str(getattr(decision, "task_type", "unknown") or "unknown"),
            confidence=getattr(decision, "confidence", 0.0) or 0.0,
            reason=str(getattr(decision, "reason", "") or ""),
        )

    route = str(normalized.task_type).lower().strip()
    # ``cart`` is a historical schema value. The main graph owns cart behavior
    # under ShoppingAgent and has no independent cart node.
    if route == "cart":
        route = "shopping"
    if route not in VALID_ROUTES:
        route = "unknown"
    confidence = max(0.0, min(1.0, float(normalized.confidence or 0.0)))
    canonical_question = str(normalized.canonical_question or "").strip()
    return IntentDecision(
        task_type=route,
        confidence=confidence,
        reason=normalized.reason,
        canonical_question=canonical_question,
        resolved_product_ids=list(normalized.resolved_product_ids or []),
        resolved_knowledge_entities=list(normalized.resolved_knowledge_entities or []),
        needs_clarification=bool(normalized.needs_clarification),
        clarification=str(normalized.clarification or "").strip(),
    )


def clarification_for_low_confidence(question: str) -> str:
    """Return a stable, actionable clarification without another model call."""
    if not (question or "").strip():
        return "请告诉我你想找什么商品，或想了解哪方面的商品知识。"
    return (
        "我还不能确定你是想查找/比较具体商品，还是想了解成分、功效或用法。"
        "请补充一下你的目标，我再继续帮你。"
    )
