"""RecommendCapability —— 商品推荐主流程。

## Pipeline
```
load pending_shopping_need
  ↓
parse_need(query)         (LLM structured_output)
  ↓
merge(pending, current)   (规则代码)
  ↓
clarify_gate(need)        (缺 category 就追问)
  ↓ pending 保存 / 清除
build_retrieval_plan(need)
  ↓
Retriever.retrieve(plan)
  ↓
ProductRanker.rank(candidates, need)
  ↓
build_product_cards(ranked, limit)
  ↓
persist last_product_cards
  ↓
RecommendToolResult(action=recommend|clarify|empty)
```

跨轮指代和 Shopping capability 选择由 Router / ShoppingAgent 完成。
RecommendCapability 只负责执行已选择的推荐任务。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.infrastructure.persistence.memory import (
    clear_pending_shopping_need,
    get_pending_shopping_need,
    remember_pending_shopping_need,
    remember_product_cards,
)
from app.infrastructure.llm.llm import get_llm
from app.domain.shopping.cards import build_product_cards
from app.domain.shopping.ranking import ProductRanker
from app.domain.shopping.retrieval import ShoppingRetriever, build_retrieval_plan
from app.domain.shopping.schemas import (
    CandidateSet,
    PendingShoppingNeed,
    RankedProduct,
    RecommendToolResult,
    ShoppingContext,
    ShoppingNeed,
)

logger = logging.getLogger("ai-service.shopping.recommend")


# ---- parse_need（LLM structured_output）--------------------------------

_PARSE_NEED_SYSTEM = """你是电商导购需求解析器。请把用户自然语言解析为 ShoppingNeed。

规则：
- category 是用户想买的商品品类，如"防晒/面霜/耳机/粉底液"。如果用户没说品类，留空。
- budget_min / budget_max 只有用户明确提到时填写（"200 以内" → budget_max=200）。
- skin_type 提取："油皮/干皮/敏感肌/混油/混干"，其余留空。
- target_user 是"送人/自用"的对象：如"妈妈/女朋友/男士/学生"。
- scenario 是使用场景列表：如 ["夏天", "通勤"] / ["礼物"]。
- preferences 是用户想要的正向偏好：["清爽", "不黏", "保湿", "便携"]。
- avoid 是用户不想要的：["油腻", "香味重", "太贵"]。
- 不要臆造品牌、预算、肤质；找不到就留空 / 空列表。
- 如果缺少商品类目，把 "category" 放进 missing_slots。
- confidence 0.0-1.0，你对当前解析的把握度。
"""


async def _parse_need_llm(
    query: str,
    pending: Optional[Dict[str, Any]],
) -> ShoppingNeed:
    """用 LLM 结构化输出把用户 query 解析成 ShoppingNeed。

    pending 提供"上下文提示"：告诉 LLM 用户上一轮已经说了什么，
    避免 LLM 无视上下文重新解析。
    """
    llm = get_llm()
    if llm is None:
        # LLM 不可用降级：只把 query 塞到 preferences，让 category 缺失 → 走 clarify
        return ShoppingNeed(preferences=[query] if query else [], missing_slots=["category"])

    structured = llm.with_structured_output(ShoppingNeed)

    user_msg = query
    if pending and pending.get("need"):
        # 把上一轮已经收集到的 need 也传给 LLM，让它做增量抽取
        user_msg = (
            f"上一轮已经收集到的需求：{pending.get('need')}\n"
            f"上一轮追问：{pending.get('last_clarify_question', '')}\n"
            f"用户当前回答：{query}\n"
            "请基于当前回答抽取新增/修正的字段，其他字段留空即可（会由代码合并）。"
        )

    try:
        result = await structured.ainvoke(
            [
                {"role": "system", "content": _PARSE_NEED_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            # 标记为内部调用：其结构化 JSON 输出不应作为 token 流给前端。
            # graph.astream 的 messages 流会据此 tag 过滤，避免槽位抽取 JSON 泄漏到聊天框。
            config={"tags": ["ai_internal"]},
        )
        return result if isinstance(result, ShoppingNeed) else ShoppingNeed()
    except Exception:  # noqa: BLE001
        logger.warning("parse_need LLM failed", exc_info=True)
        return ShoppingNeed(missing_slots=["category"])


# ---- 合并 pending 和当前解析 -------------------------------------------


def merge_shopping_need(old: ShoppingNeed, new: ShoppingNeed) -> ShoppingNeed:
    """把上一轮 pending 和当前解析合并；当前轮优先。

    - 标量字段：new 有值就覆盖 old
    - 列表字段：合并去重
    - sort_preference：new 非默认就覆盖
    """
    data = old.model_dump()

    scalar_fields = (
        "category", "brand", "budget_min", "budget_max",
        "target_user", "skin_type",
    )
    for field in scalar_fields:
        v = getattr(new, field, None)
        if v not in (None, ""):
            data[field] = v

    list_fields = ("scenario", "preferences", "avoid", "must_have", "nice_to_have")
    for field in list_fields:
        old_list = list(getattr(old, field, []) or [])
        new_list = list(getattr(new, field, []) or [])
        merged: List[str] = []
        seen: set[str] = set()
        for x in old_list + new_list:
            if x and x not in seen:
                seen.add(x)
                merged.append(x)
        data[field] = merged

    if new.sort_preference != "match":
        data["sort_preference"] = new.sort_preference

    # missing_slots / confidence 用新解析的
    data["missing_slots"] = list(new.missing_slots or [])
    data["confidence"] = float(new.confidence or 0.0)

    return ShoppingNeed(**data)


# ---- clarify_gate --------------------------------------------------------


def get_missing_required_slots(need: ShoppingNeed) -> List[str]:
    """返回还缺哪些必填槽。

    MVP 只强制 category；送礼场景（scenario 含"礼物"或有 target_user）
    如果 category 已有但没 target_user，不强制。
    """
    missing: List[str] = []
    if not need.category:
        missing.append("category")
    return missing


def build_clarify_question(need: ShoppingNeed, missing: List[str]) -> str:
    """模板化澄清问题，MVP 不用 LLM。

    追问原则：一次最多问 1-2 个关键问题。
    """
    if "category" in missing:
        # 送礼场景 + 没品类
        is_gift = "礼物" in (need.scenario or []) or need.target_user
        if is_gift:
            who = need.target_user or "对方"
            return f"送给「{who}」的话，想找哪类商品呢？比如护肤、彩妆、香氛，预算大概多少？"
        return "你想找哪类商品呢？比如防晒、面霜、耳机、粉底液，还是其他？"
    if "target_user" in missing:
        return "这是自己用还是送人？如果送人，是送给谁呢？"
    return "可以再补充一下你的预算或使用场景吗？"


# ---- 主类 ---------------------------------------------------------------


class RecommendCapability:
    def __init__(
        self,
        retriever: Optional[ShoppingRetriever] = None,
        ranker: Optional[ProductRanker] = None,
    ):
        self.retriever = retriever or ShoppingRetriever()
        self.ranker = ranker or ProductRanker()

    async def run(
        self,
        query: str,
        context: ShoppingContext,
        limit: int = 3,
    ) -> RecommendToolResult:
        """主入口 —— 见文件头 Pipeline 图。"""
        trace: List[Dict[str, Any]] = []

        # ── 1. 读 pending + parse 当前 query ──
        pending = await get_pending_shopping_need(context.conversation_id, context.user_id)
        current_need = await _parse_need_llm(query, pending)
        trace.append({"step": "parse_need", "output": current_need.model_dump()})

        # ── 2. merge pending + current ──
        if pending:
            try:
                old_need = ShoppingNeed(**pending.get("need", {}))
            except Exception:  # noqa: BLE001
                old_need = ShoppingNeed()
            need = merge_shopping_need(old_need, current_need)
        else:
            need = current_need
        trace.append({"step": "merge_pending_need", "output": need.model_dump()})

        # Long-term behaviour facts and automatic preference learning are
        # deliberately disabled.  A Shopping turn follows the user's current
        # request; basic profile tags stay available to later candidate judging
        # work but must not silently rewrite this retrieval need.
        trace.append({"step": "preference_scope", "output": {
            "automatic_learning": "disabled",
            "soft_rerank": "not_applied",
        }})

        # ── 3. clarify_gate ──
        # A pure image can establish the product type through image retrieval;
        # do not reject it merely because text need parsing has no category.
        missing = [] if context.image_url else get_missing_required_slots(need)
        if missing:
            clarify_q = build_clarify_question(need, missing)
            turn_count = int((pending or {}).get("turn_count") or 0) + 1
            pending_snapshot = PendingShoppingNeed(
                need=need,
                missing_slots=missing,
                last_clarify_question=clarify_q,
                turn_count=turn_count,
            )
            await remember_pending_shopping_need(
                context.conversation_id, context.user_id, pending_snapshot.model_dump(),
            )
            trace.append({"step": "clarify_gate", "output": {"missing_slots": missing}})
            return RecommendToolResult(
                action="clarify",
                need=need,
                clarify_question=clarify_q,
                trace=trace,
            )

        # 已经补齐了，清 pending
        await clear_pending_shopping_need(context.conversation_id, context.user_id)

        if context.image_url:
            return await self._run_image_recommendation(
                query=query,
                need=need,
                context=context,
                limit=limit,
                trace=trace,
            )

        # ── 4. 文本检索 ──
        # top_k = limit（rerank 从 initial_top_k=20 里挑），Phase 1b 起启用 Milvus hybrid + rerank
        plan = build_retrieval_plan(need, top_k=limit)
        candidates, recall_trace = await self.retriever.retrieve(plan, need)
        trace.append({"step": "retrieval", "output": {
            "plan_primary_query": plan.primary_query,
            "recall_trace": recall_trace,
            "candidates_count": len(candidates),
        }})

        candidate_set = CandidateSet(
            input_mode="text",
            candidates=[dict(candidate) for candidate in candidates],
            retrieval_channels=["bm25", "dense"],
            retrieval_counts={"after_recall": len(candidates)},
            query_text=query,
        )

        if not candidates:
            return RecommendToolResult(
                action="empty",
                need=need,
                candidate_set=candidate_set,
                empty_reason=(
                    f"没找到匹配「{need.category or query}」的商品，"
                    "试试放宽预算、去掉部分偏好，或换一个更通用的品类关键词。"
                ),
                trace=trace,
            )

        # ── 5. 排序 ──
        ranked = self.ranker.rank(candidates, need)
        trace.append({"step": "rank", "output": {
            "top_product_ids": [p.product_id for p in ranked[:limit]],
            "top_scores": [p.score for p in ranked[:limit]],
        }})

        # ── 6. 构造 cards + 记忆 ──
        cards = build_product_cards(ranked, limit=limit)
        if cards:
            await remember_product_cards(context.conversation_id, context.user_id, cards)

        return RecommendToolResult(
            action="recommend",
            need=need,
            candidate_set=candidate_set,
            ranked_products=ranked[:limit],
            product_cards=cards,
            trace=trace,
        )

    async def _run_image_recommendation(
        self,
        *,
        query: str,
        need: ShoppingNeed,
        context: ShoppingContext,
        limit: int,
        trace: List[Dict[str, Any]],
    ) -> RecommendToolResult:
        """Use the existing image retrieval stack behind the same high-level tool.

        The Agent selects ``recommend_products`` once.  This method chooses the
        low-level retrieval path from Router-provided input mode; the LLM never
        needs to choose a vector store or an image embedding tool.
        """
        from app.domain.shopping.multimodal_search import (
            enforce_explicit_product_filters,
            extract_explicit_product_filters,
            search_multimodal_v1,
        )

        input_mode = "image" if context.input_mode == "image" else "multimodal"
        retrieval_query = "" if input_mode == "image" else query
        filters = extract_explicit_product_filters(retrieval_query)
        retrieval_limit = max(int(limit or 3) * 2, int(limit or 3), 1)
        try:
            candidates = await search_multimodal_v1(
                query_text=retrieval_query,
                query_image_url=str(context.image_url),
                top_k=retrieval_limit,
                filters=filters,
            )
        except Exception:  # noqa: BLE001
            logger.exception("multimodal recommend retrieval failed")
            return RecommendToolResult(
                action="empty",
                need=need,
                candidate_set=CandidateSet(
                    input_mode=input_mode,
                    query_text=query,
                    image_fingerprint=_image_fingerprint(context.image_url),
                ),
                empty_reason="图片检索暂时不可用，请稍后再试。",
                trace=[*trace, {"step": "multimodal_retrieval", "output": "error"}],
            )

        # search_multimodal_v1 already applies status / configured retrieval
        # filters.  Keep its factual result shaping here and defer semantic
        # exact/alternative judgement to Phase 3.
        filtered = enforce_explicit_product_filters(list(candidates or []), filters)
        channels = (
            ["image_vector"] if input_mode == "image"
            else ["dense", "bm25", "image_vector", "vl_rerank"]
        )
        candidate_set = CandidateSet(
            input_mode=input_mode,
            candidates=[dict(candidate) for candidate in filtered],
            retrieval_channels=channels,
            retrieval_counts={
                "after_recall": len(candidates or []),
                "after_filters": len(filtered),
            },
            query_text=query,
            image_fingerprint=_image_fingerprint(context.image_url),
        )
        trace.append({"step": "multimodal_retrieval", "output": {
            "input_mode": input_mode,
            "candidate_count": len(filtered),
            "channels": channels,
        }})
        if not filtered:
            return RecommendToolResult(
                action="empty",
                need=need,
                candidate_set=candidate_set,
                empty_reason="没有找到与图片和当前需求相近的在售商品。",
                trace=trace,
            )

        ranked = [_ranked_product_from_multimodal(candidate, input_mode) for candidate in filtered]
        cards = build_product_cards(ranked, limit=limit)
        if cards:
            await remember_product_cards(context.conversation_id, context.user_id, cards)
        return RecommendToolResult(
            action="recommend",
            need=need,
            candidate_set=candidate_set,
            ranked_products=ranked[:limit],
            product_cards=cards,
            trace=trace,
        )


def _image_fingerprint(image_url: Optional[str]) -> Optional[str]:
    if not image_url:
        return None
    return hashlib.sha256(str(image_url).encode("utf-8")).hexdigest()[:16]


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ranked_product_from_multimodal(candidate: Dict[str, Any], input_mode: str) -> RankedProduct:
    sources = list(candidate.get("recall_sources") or [])
    if not sources:
        sources = ["image_vector" if input_mode == "image" else "multimodal"]
    return RankedProduct(
        product_id=int(candidate.get("product_id") or candidate.get("id") or 0),
        title=str(candidate.get("title") or ""),
        brand=str(candidate.get("brand") or ""),
        price=_as_float(candidate.get("price") or candidate.get("base_price")),
        base_price=_as_float(candidate.get("base_price") or candidate.get("price")),
        image_url=str(candidate.get("image_url") or ""),
        rating=_as_float(candidate.get("rating")),
        review_count=int(candidate.get("review_count") or 0),
        sales_count=int(candidate.get("sales_count") or 0),
        category=str(candidate.get("category") or ""),
        sub_category=str(candidate.get("sub_category") or ""),
        tags=str(candidate.get("tags") or ""),
        description=str(candidate.get("description") or ""),
        score=_as_float(candidate.get("score") or candidate.get("rrf_score")),
        recall_sources=sources,
        rank_reason=["图片相似检索命中" if input_mode == "image" else "图文检索命中"],
    )
