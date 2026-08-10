"""One LLM judge for the candidates already returned by Phase 2.

This module does not retrieve products, parse a need, rank products, inspect
conversation history, or apply keyword/category fallbacks.  It is deliberately
one small post-processing step: query plus candidate rows in, exact,
alternative, or reject decisions out.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Mapping

from app.infrastructure.config import config

logger = logging.getLogger("ai-service.shopping.relevance_judge")

_PREFERENCE_RERANK_MIN_APPLICABILITY = 0.65
_BASIC_PREFERENCE_KEYS = (
    "skin_type",
    "gender",
    "preference_tags",
    "budget_min",
    "budget_max",
)


_FILTER_PROMPT = """你是「微爱商城」推荐结果的候选审核模型。
Phase 2 已经完成商品召回和相关性排序。你只执行一次语义审核：根据用户的完整请求和
候选商品真实字段，将候选判为 exact、alternative 或 reject。

严格按以下顺序判断：
1. 先理解用户真正想买的商品类型，不要依靠关键词机械匹配。
2. 判断每个候选是否属于这个商品类型。不同商品类型一律 reject。
3. 对同商品类型候选继续判断预算、品牌、颜色、功能、使用场景、肤质和其他条件：
   - 满足主要需求和全部明确条件：exact。
   - 商品类型正确，但至少一个附加条件不满足：alternative，并在 constraint_gaps
     写明期望值与真实值。
   - 只能检查用户明确说出的条件。用户未提预算、品牌、颜色或功能时，不得自行补充
     这些条件，也不得因此判为 alternative。“推荐几款”只是数量期望，不是商品条件。
4. 汇总输出：
   - 只要存在 exact，只输出 exact，不输出 alternative 和 reject。
   - 没有 exact、但存在同商品类型候选时，必须输出这些同类型 alternative；即使预算
     差距较大，也应作为诚实的店内参考，不能因为不满足条件就返回空数组。
   - 只有候选中完全没有用户所需商品类型时，items 才能为空。

需求命中和偏好评分是两个独立任务：
- 第一阶段判断 decision 时，必须假装“基础偏好”部分不存在，只能阅读用户当前请求和
  候选字段。基础偏好不能改变 exact、alternative 或 reject，不能让原本命中的商品被
  省略、降级或拒绝。
- 完成需求命中判断后，再判断“基础偏好”是否适用于当前商品需求，输出整体的
  preference_applicability_score（0 到 1）。肤质对护肤品通常相关，对耳机通常无关；
  具体语义由你结合需求判断，不做关键词机械匹配。
- 对每个准备展示的 exact 或 alternative 候选输出 preference_relevance_score（0 到 1）
  和 matched_preferences。这个分数只表示商品与相关基础偏好的匹配程度，不表示需求命中程度。
- 没有基础偏好或偏好与当前需求无关时，preference_applicability_score 必须接近 0，
  preference_relevance_score 填 0，matched_preferences 为空。
- 你只负责评分，不得根据偏好调整 items 顺序；系统代码会在需要时稳定排序。
- preference_relevance_score 很低仍然要保留已经命中的候选；低分只影响后续代码排序。

alternative 绝不能跨商品类型。咖啡粉不能替代咖啡机，电脑不能替代耳机，衣服不能
替代跑鞋。预算、品牌、颜色、功能或场景不符可以作为同类替代；商品类型不同必须 reject。
不得创造候选、商品 ID、价格、库存或事实，只能引用输入中的 candidate_index。

示例一：用户要“500 元以内的耳机”，候选是 699 元耳机。没有低于 500 元的耳机时，
必须返回该候选：decision=alternative、same_product_type=true，并写预算差距。
示例二：用户要“咖啡机”，候选是速溶咖啡粉。必须 reject；如果没有其他咖啡机，items=[]。
示例三：用户要“耳机”，候选是提到耳机接口的电脑。必须 reject。
示例四：用户只说“推荐几款耳机”，候选是真无线耳机。没有其他明确条件需要检查，
必须判为 exact，不得因价格、品牌或推荐数量判为 alternative。
示例五：用户只说“推荐两款面霜”，基础偏好是“油皮、清爽”，候选分别是滋润面霜和
清爽面霜。两款在需求命中阶段都必须判为 exact 并返回；偏好阶段可以给滋润面霜 0.1、
清爽面霜 0.9。不得因为滋润面霜偏好分低而省略它，系统代码会把清爽面霜排在前面。

只返回 JSON，不要解释，不要 Markdown：
{{"preference_applicability_score":0.9,"items":[{{"candidate_index":1,"decision":"exact|alternative",
"same_product_type":true,"reason":"简短理由",
"preference_relevance_score":0.85,"matched_preferences":["清爽"],
"constraint_gaps":[{{"name":"budget","expected":"500 元以内",
"actual":"699 元","message":"超出预算 199 元"}}]}}]}}

用户请求：
{query}

候选商品：
{candidates}

基础偏好（仅用于独立评分，不是当前需求条件）：
{preferences}
"""


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                value = part.get("text") or part.get("content")
            else:
                value = getattr(part, "text", None) or getattr(part, "content", None)
            if value:
                parts.append(str(value))
        return "".join(parts).strip()
    return str(content or "").strip()


def _parse_json_payload(text: str) -> Any:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S).strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        for start, end in (("{", "}"), ("[", "]")):
            left, right = value.find(start), value.rfind(end)
            if left >= 0 and right > left:
                try:
                    return json.loads(value[left : right + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _decision_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _judge_prompt(
    query: str,
    candidates: list[dict[str, Any]],
    preferences: Mapping[str, Any] | None = None,
) -> str:
    rows = []
    for index, candidate in enumerate(candidates, start=1):
        rows.append({
            "candidate_index": index,
            "title": candidate.get("title", ""),
            "brand": candidate.get("brand", ""),
            "price": candidate.get("price") or candidate.get("base_price"),
            "category": candidate.get("category", ""),
            "sub_category": candidate.get("sub_category", ""),
            "tags": candidate.get("tags", ""),
            "description": str(candidate.get("description", ""))[:400],
        })
    return _FILTER_PROMPT.format(
        query=query or "(image retrieval request; use the retrieved candidate fields)",
        candidates=json.dumps(rows, ensure_ascii=False),
        preferences=json.dumps(_basic_preferences(preferences), ensure_ascii=False),
    )


async def filter_recommendation_candidates(
    llm: Any,
    query: str,
    candidates: Iterable[dict[str, Any]],
    preferences: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the single Phase 3 LLM judge over Phase 2 candidates.

    Empty input stays empty. Disabling the feature preserves Phase 2 output.
    A failed or invalid enabled Judge returns no cards instead of leaking an
    unrelated candidate; no second retrieval or semantic rule fallback runs.
    """
    items = [dict(item) for item in candidates][
        : max(1, int(config.SHOPPING_LLM_JUDGE_MAX_CANDIDATES))
    ]
    if not items:
        return []
    if not config.SHOPPING_LLM_JUDGE_ENABLED or llm is None:
        return items

    basic_preferences = _basic_preferences(preferences)
    try:
        from langchain_core.messages import HumanMessage

        response = await llm.ainvoke(
            [HumanMessage(content=_judge_prompt(query, items, basic_preferences))],
            config={"tags": ["ai_internal", "shopping_candidate_filter"]},
        )
        payload = _parse_json_payload(_response_text(response))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shopping candidate judge failed; returning no semantic cards: %s", exc)
        return []

    applicability_score = (
        _unit_score(
            payload.get("preference_applicability_score")
            if isinstance(payload, dict) else None
        )
        if basic_preferences else 0.0
    )
    decisions: dict[int, dict[str, Any]] = {}
    for raw in _decision_items(payload):
        try:
            index = int(raw.get("candidate_index"))
        except (TypeError, ValueError):
            continue
        decision = str(raw.get("decision") or "").strip().lower()
        same_product_type = raw.get("same_product_type") is True
        if (
            1 <= index <= len(items)
            and decision in {"exact", "alternative"}
            and same_product_type
        ):
            gaps = raw.get("constraint_gaps")
            decisions[index] = {
                "decision": decision,
                "reason": str(raw.get("reason") or "").strip(),
                "constraint_gaps": gaps if isinstance(gaps, list) else [],
                "preference_score": _unit_score(raw.get("preference_relevance_score")),
                "matched_preferences": _string_list(raw.get("matched_preferences")),
            }

    if not decisions:
        logger.warning("shopping candidate judge returned no displayable candidates")
        return []

    exact: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        verdict = decisions.get(index)
        if verdict is None:
            continue
        item["match_status"] = verdict["decision"]
        item["constraint_gaps"] = verdict["constraint_gaps"]
        item["judge_reason"] = verdict["reason"]
        item["personalization_score"] = verdict["preference_score"]
        item["matched_preferences"] = verdict["matched_preferences"]
        if verdict["decision"] == "exact":
            exact.append(item)
        elif verdict["decision"] == "alternative":
            alternatives.append(item)

    selected = exact or alternatives
    highest_preference_score = max(
        (float(item.get("personalization_score") or 0.0) for item in selected),
        default=0.0,
    )
    if (
        applicability_score >= _PREFERENCE_RERANK_MIN_APPLICABILITY
        and highest_preference_score >= _PREFERENCE_RERANK_MIN_APPLICABILITY
        and len(selected) > 1
    ):
        # Python's sort is stable: equal preference scores retain qwen3-rerank order.
        selected.sort(
            key=lambda item: float(item.get("personalization_score") or 0.0),
            reverse=True,
        )
    return selected


def _basic_preferences(preferences: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(preferences, Mapping):
        return {}
    return {
        key: preferences[key]
        for key in _BASIC_PREFERENCE_KEYS
        if key in preferences and preferences[key] not in (None, "", [], {})
    }


def _unit_score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
