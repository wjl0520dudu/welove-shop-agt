"""商品排序 —— 从召回结果到 RankedProduct 的确定性打分。

## 设计原则
1. **打分函数纯函数、可测试**：ProductRanker.rank(candidates, need) → List[RankedProduct]，
   没有 IO，没有 LLM。
2. **每一分都可解释**：算完总分同时产出 rank_reason / matched_needs / risk_notes，
   让 LLM 拿到"为什么排前"的现成材料。
3. **权重集中管理**：改分数分布只改 `_WEIGHTS` 一处。

## 分数构成
```
score =
  category_score   * 0.25   商品类目 vs need.category
+ preference_score * 0.25   preferences / must_have / nice_to_have 命中占比
+ budget_score     * 0.15   在预算内加分，越接近预算中位越高
+ avoid_score      * 0.15   avoid 关键词命中 → 扣分
+ popularity_score * 0.10   sales/rating 归一化
+ recall_score     * 0.10   多路召回 boost（在多路都出现的项加分）
```
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from shopping.schemas import RankedProduct, ShoppingNeed


# 权重集中一处，改分布只改这里
_WEIGHTS = {
    "category": 0.25,
    "preference": 0.25,
    "budget": 0.15,
    "avoid": 0.15,
    "popularity": 0.10,
    "recall": 0.10,
}


# preferences 同义词词典 —— 用户说"清爽"应该也匹配"轻薄/水感/不黏"
# MVP 手工枚举足够，后续可以换成 LLM 抽取的 tag。
_SYNONYMS: Dict[str, List[str]] = {
    "清爽": ["清爽", "轻薄", "水感", "不黏", "不黏腻", "控油", "哑光"],
    "不黏": ["不黏", "不黏腻", "清爽", "水感"],
    "保湿": ["保湿", "补水", "滋润", "锁水", "水润"],
    "敏感肌": ["敏感肌", "温和", "舒缓", "修护", "低刺激", "无香"],
    "油皮": ["油皮", "控油", "清爽", "哑光", "不油腻"],
    "干皮": ["干皮", "滋润", "保湿", "水润"],
    "便携": ["便携", "小巧", "旅行装", "迷你"],
    "平价": ["平价", "性价比", "亲民", "实惠"],
}


def _expand_synonyms(terms: List[str]) -> List[str]:
    """把偏好词展开成同义词列表（去重保序）。"""
    out: List[str] = []
    seen: set[str] = set()
    for t in terms or []:
        t = (t or "").strip()
        if not t or t in seen:
            continue
        for syn in _SYNONYMS.get(t, [t]):
            if syn not in seen:
                seen.add(syn)
                out.append(syn)
    return out


class ProductRanker:
    """规则加权排序器。

    完全无状态，Capability 直接 `ProductRanker().rank(candidates, need)`。
    """

    def rank(
        self,
        candidates: List[Dict[str, Any]],
        need: ShoppingNeed,
    ) -> List[RankedProduct]:
        """把召回来的 dict 列表打分排序，返回 RankedProduct 列表。

        candidates 里每项应至少有 product_id/title 字段，其余尽量携带 —— 缺失字段 0/空处理。
        """
        if not candidates:
            return []

        pref_terms = _expand_synonyms(need.preferences + need.must_have + need.nice_to_have)
        avoid_terms = _expand_synonyms(need.avoid)

        # 归一化用的极值
        max_sales = max((int(c.get("sales_count") or 0) for c in candidates), default=1) or 1
        max_recall_sources = max((len(c.get("recall_sources") or []) for c in candidates), default=1) or 1

        ranked: List[RankedProduct] = []
        for c in candidates:
            text = _candidate_text(c)

            # ── 各维度分数 ──
            cat_s = _score_category(text, need.category)
            pref_s, matched, unmatched = _score_preferences(text, pref_terms, need.preferences)
            budget_s, over_budget = _score_budget(_price(c), need.budget_min, need.budget_max)
            avoid_s, avoid_hits = _score_avoid(text, avoid_terms)
            pop_s = _score_popularity(c, max_sales)
            recall_s = len(c.get("recall_sources") or []) / max_recall_sources

            # ── 组装总分 ──
            score = (
                cat_s * _WEIGHTS["category"]
                + pref_s * _WEIGHTS["preference"]
                + budget_s * _WEIGHTS["budget"]
                + avoid_s * _WEIGHTS["avoid"]
                + pop_s * _WEIGHTS["popularity"]
                + recall_s * _WEIGHTS["recall"]
            )

            # ── 匹配理由 / 风险提示 ──
            reasons = _build_reasons(need, matched, over_budget=False, budget_max=need.budget_max)
            risks: List[str] = []
            if over_budget:
                risks.append(f"价格超出预算 {need.budget_max}")
            if avoid_hits:
                risks.append(f"含避雷词：{', '.join(avoid_hits[:3])}")

            ranked.append(
                RankedProduct(
                    product_id=int(c.get("product_id") or c.get("id") or 0),
                    title=str(c.get("title") or ""),
                    brand=str(c.get("brand") or ""),
                    price=_to_float(c.get("price") or c.get("base_price")),
                    base_price=_to_float(c.get("base_price") or c.get("price")),
                    image_url=str(c.get("image_url") or ""),
                    rating=_to_float(c.get("rating")),
                    review_count=int(c.get("review_count") or 0),
                    sales_count=int(c.get("sales_count") or 0),
                    category=str(c.get("category") or ""),
                    sub_category=str(c.get("sub_category") or ""),
                    tags=str(c.get("tags") or ""),
                    description=str(c.get("description") or ""),
                    score=round(float(score), 4),
                    recall_sources=list(c.get("recall_sources") or []),
                    matched_needs=matched,
                    unmatched_needs=unmatched,
                    rank_reason=reasons,
                    risk_notes=risks,
                )
            )

        # 用户指定的排序偏好优先，其次总分
        ranked = _apply_sort_preference(ranked, need.sort_preference)
        return ranked


# ---- helper functions -----------------------------------------------------


def _candidate_text(c: Dict[str, Any]) -> str:
    return " ".join(
        str(c.get(k) or "")
        for k in ("title", "brand", "category", "sub_category", "tags", "description")
    )


def _score_category(text: str, category: Optional[str]) -> float:
    if not category:
        return 0.5   # 用户没指定品类，中性分
    return 1.0 if category in text else 0.0


def _score_preferences(
    text: str, expanded_terms: List[str], original_terms: List[str]
) -> tuple[float, List[str], List[str]]:
    """返回 (score, matched_original_terms, unmatched_original_terms)。

    matched/unmatched 是"原始偏好词"，同义词是内部展开细节，不给上游看。
    """
    if not original_terms:
        return 0.5, [], []
    matched: List[str] = []
    unmatched: List[str] = []
    for original in original_terms:
        syns = _SYNONYMS.get(original, [original])
        if any(s in text for s in syns):
            matched.append(original)
        else:
            unmatched.append(original)
    return (len(matched) / len(original_terms)), matched, unmatched


def _score_budget(
    price: Optional[float],
    lo: Optional[float],
    hi: Optional[float],
) -> tuple[float, bool]:
    """在预算内 = 1.0；超出上限 = 0（且标记 over_budget）；无预算 = 0.5 中性。"""
    if price is None:
        return 0.5, False
    if lo is None and hi is None:
        return 0.5, False
    if lo is not None and price < lo:
        return 0.3, False
    if hi is not None and price > hi:
        return 0.0, True
    return 1.0, False


def _score_avoid(text: str, avoid_terms: List[str]) -> tuple[float, List[str]]:
    """avoid 命中越多分越低。全没命中 = 1.0；一半命中 = 0.5；全命中 = 0。"""
    if not avoid_terms:
        return 1.0, []
    hits = [t for t in avoid_terms if t in text]
    return (1.0 - len(hits) / len(avoid_terms)), hits


def _score_popularity(c: Dict[str, Any], max_sales: int) -> float:
    """销量归一 * 0.7 + 评分归一 * 0.3。"""
    sales = int(c.get("sales_count") or 0)
    rating = float(c.get("rating") or 0)
    sales_norm = sales / max_sales if max_sales else 0
    rating_norm = rating / 5.0
    return 0.7 * sales_norm + 0.3 * rating_norm


def _build_reasons(
    need: ShoppingNeed,
    matched: List[str],
    over_budget: bool,
    budget_max: Optional[float],
) -> List[str]:
    reasons: List[str] = []
    if need.category:
        reasons.append(f"匹配「{need.category}」品类")
    if need.skin_type:
        reasons.append(f"适合「{need.skin_type}」")
    if matched:
        reasons.append(f"命中偏好：{', '.join(matched[:3])}")
    if need.target_user:
        reasons.append(f"面向「{need.target_user}」")
    if not over_budget and budget_max is not None:
        reasons.append(f"在 {int(budget_max)} 元预算内")
    return reasons or ["综合匹配当前需求"]


def _apply_sort_preference(
    ranked: List[RankedProduct], sort_pref: str
) -> List[RankedProduct]:
    """用户明确要求"按价格/评分"排时，覆盖 score 排序。"""
    if sort_pref == "price_low":
        return sorted(ranked, key=lambda p: (p.price or 1e12, -p.score))
    if sort_pref == "price_high":
        return sorted(ranked, key=lambda p: (-(p.price or 0), -p.score))
    if sort_pref == "rating":
        return sorted(ranked, key=lambda p: (-(p.rating or 0), -p.score))
    if sort_pref == "sales":
        return sorted(ranked, key=lambda p: (-p.sales_count, -p.score))
    # match / value → 按 score
    return sorted(ranked, key=lambda p: -p.score)


def _price(c: Dict[str, Any]) -> Optional[float]:
    return _to_float(c.get("price") or c.get("base_price"))


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
