"""Execute one recommendation selected by ShoppingAgent.

The complete turn from Router is the retrieval query. This capability does not
re-parse conversation context or require a catalog slot before searching. Its
only semantic post-processing step is the single candidate Judge.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

from app.infrastructure.persistence.memory import remember_product_cards
from app.infrastructure.llm.llm import get_llm
from app.domain.shopping.cards import build_product_cards
from app.domain.shopping.relevance_judge import filter_recommendation_candidates
from app.domain.shopping.retrieval import ShoppingRetriever, build_retrieval_plan
from app.domain.shopping.schemas import (
    CandidateSearchToolResult,
    CandidateSet,
    RankedProduct,
    RecommendToolResult,
    ShoppingContext,
    ShoppingNeed,
)

logger = logging.getLogger("ai-service.shopping.recommend")


# ---- 主类 ---------------------------------------------------------------


class RecommendCapability:
    def __init__(
        self,
        retriever: Optional[ShoppingRetriever] = None,
    ):
        self.retriever = retriever or ShoppingRetriever()

    async def run(
        self,
        query: str,
        context: ShoppingContext,
        limit: int = 3,
    ) -> RecommendToolResult:
        """Backward-compatible composition of the two Phase S4 operations."""
        search_result = await self.search_candidates(
            query=query,
            context=context,
            limit=limit,
        )
        if search_result.action != "candidates" or search_result.candidate_set is None:
            return RecommendToolResult(
                action="clarify" if search_result.action == "clarify" else "empty",
                need=search_result.need,
                candidate_set=search_result.candidate_set,
                clarify_question=search_result.clarify_question,
                empty_reason=search_result.empty_reason,
                trace=search_result.trace,
            )
        return await self.finalize_candidates(
            query=query,
            context=context,
            candidate_set=search_result.candidate_set,
            limit=limit,
            need=search_result.need,
            trace=search_result.trace,
        )

    async def search_candidates(
        self,
        *,
        query: str,
        context: ShoppingContext,
        limit: int = 3,
    ) -> CandidateSearchToolResult:
        """Retrieve a bounded factual CandidateSet without semantic judging."""
        trace: List[Dict[str, Any]] = []
        query_text = str(query or "").strip()
        need = ShoppingNeed()
        trace.append({"step": "recommend_input", "output": {
            "query": query_text,
            "input_mode": context.input_mode,
            "has_image": bool(context.image_url),
        }})

        if not query_text and not context.image_url:
            return CandidateSearchToolResult(
                action="clarify",
                need=need,
                clarify_question="请描述一下想找的商品或使用需求。",
                trace=trace,
            )

        if context.image_url:
            return await self._search_image_candidates(
                query=query_text,
                need=need,
                context=context,
                limit=limit,
                trace=trace,
            )

        # ── 4. 文本检索 ──
        # top_k = limit（rerank 从 initial_top_k=20 里挑），Phase 1b 起启用 Milvus hybrid + rerank
        # Keep a wider semantic candidate window for the single LLM Judge.
        # Cards are still capped by ``limit`` after judging.
        candidate_limit = max(int(limit or 3) * 4, 20)
        plan = build_retrieval_plan(
            need,
            top_k=candidate_limit,
            query_text=query_text,
        )
        candidates, recall_trace = await self.retriever.retrieve(plan, need)
        trace.append({"step": "retrieval", "output": {
            "plan_primary_query": plan.primary_query,
            "recall_trace": recall_trace,
            "candidates_count": len(candidates),
        }})

        candidate_set = CandidateSet(
            input_mode="text",
            candidates=[
                _candidate_for_transport(candidate, "text")
                for candidate in candidates
            ],
            retrieval_channels=["bm25", "dense"],
            retrieval_counts={"after_recall": len(candidates)},
            query_text=query_text,
        )

        if not candidates:
            return CandidateSearchToolResult(
                action="empty",
                need=need,
                candidate_set=candidate_set,
                empty_reason=(
                    f"没找到匹配「{query_text}」的商品，"
                    "试试放宽预算、去掉部分偏好，或换一个更通用的品类关键词。"
                ),
                trace=trace,
            )

        return CandidateSearchToolResult(
            action="candidates",
            need=need,
            candidate_set=candidate_set,
            trace=trace,
        )

    async def finalize_candidates(
        self,
        *,
        query: str,
        context: ShoppingContext,
        candidate_set: CandidateSet,
        limit: int = 3,
        need: Optional[ShoppingNeed] = None,
        trace: Optional[List[Dict[str, Any]]] = None,
    ) -> RecommendToolResult:
        """Judge server-owned candidates, validate them and construct cards."""
        bounded_limit = max(1, int(limit or 3))
        output_trace = list(trace or [])
        ranked: List[RankedProduct] = []
        for candidate in candidate_set.candidates:
            try:
                item = RankedProduct.model_validate(candidate)
            except Exception:  # noqa: BLE001
                continue
            if item.product_id > 0 and item.title.strip():
                ranked.append(item)

        if not ranked:
            return RecommendToolResult(
                action="empty",
                need=need or ShoppingNeed(),
                candidate_set=candidate_set,
                empty_reason="候选商品数据不完整，暂时无法生成可靠推荐。",
                trace=output_trace,
            )

        if candidate_set.input_mode == "image":
            # Pure-image candidates have already passed image-vector retrieval
            # and the configured multimodal reranker. The text Judge cannot see
            # the reference image, so it must not reject valid visual matches.
            for item in ranked:
                item.match_status = "exact"
                item.judge_reason = "图片相似检索命中"
            output_trace.append({"step": "candidate_judge", "output": {
                "status": "skipped_for_pure_image",
                "candidate_count": len(ranked),
            }})
        else:
            ranked = await _judge_ranked_candidates(
                str(query or candidate_set.query_text or "").strip(),
                ranked,
                context.user_preferences,
            )
            output_trace.append({"step": "candidate_judge", "output": {
                "status": "completed",
                "candidate_count": len(ranked),
            }})

        if not ranked:
            return RecommendToolResult(
                action="empty",
                need=need or ShoppingNeed(),
                candidate_set=candidate_set,
                empty_reason="商城暂时没有找到符合或可替代的相关商品。",
                trace=output_trace,
            )

        output_trace.append({"step": "rank", "output": {
            "top_product_ids": [p.product_id for p in ranked[:bounded_limit]],
            "top_scores": [p.score for p in ranked[:bounded_limit]],
        }})
        cards = build_product_cards(ranked, limit=bounded_limit)
        if cards:
            await remember_product_cards(context.conversation_id, context.user_id, cards)

        return RecommendToolResult(
            action="recommend",
            need=need or ShoppingNeed(),
            candidate_set=candidate_set,
            ranked_products=ranked[:bounded_limit],
            product_cards=cards,
            trace=output_trace,
        )

    async def _search_image_candidates(
        self,
        *,
        query: str,
        need: ShoppingNeed,
        context: ShoppingContext,
        limit: int,
        trace: List[Dict[str, Any]],
    ) -> CandidateSearchToolResult:
        """Retrieve image or multimodal candidates without semantic judging."""
        from app.domain.shopping.multimodal_search import (
            enforce_explicit_product_filters,
            search_multimodal_v1,
        )

        input_mode = "image" if context.input_mode == "image" else "multimodal"
        retrieval_query = "" if input_mode == "image" else query
        # User wording is intentionally not converted into category/budget
        # expressions. The common semantic Judge handles those conditions.
        filters = {"status": 1}
        retrieval_limit = max(int(limit or 3) * 4, 20)
        try:
            candidates = await search_multimodal_v1(
                query_text=retrieval_query,
                query_image_url=str(context.image_url),
                top_k=retrieval_limit,
                filters=filters,
            )
        except Exception:  # noqa: BLE001
            logger.exception("multimodal recommend retrieval failed")
            return CandidateSearchToolResult(
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
        # Do not hard-filter category or budget before judging. The image and
        # text embedding paths already provide semantic similarity; the Judge
        # decides exact versus same-type alternative from real candidate data.
        filtered = enforce_explicit_product_filters(
            list(candidates or []), {"status": filters.get("status", 1)}
        )
        channels = (
            ["image_vector"] if input_mode == "image"
            else ["dense", "bm25", "image_vector", "vl_rerank"]
        )
        candidate_set = CandidateSet(
            input_mode=input_mode,
            candidates=[
                _candidate_for_transport(candidate, input_mode)
                for candidate in filtered
            ],
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
            return CandidateSearchToolResult(
                action="empty",
                need=need,
                candidate_set=candidate_set,
                empty_reason="没有找到与图片和当前需求相近的在售商品。",
                trace=trace,
            )

        return CandidateSearchToolResult(
            action="candidates",
            need=need,
            candidate_set=candidate_set,
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


def _ranked_product_from_candidate(candidate: Dict[str, Any], input_mode: str) -> RankedProduct:
    sources = list(candidate.get("recall_sources") or [])
    if not sources:
        source = "image_vector" if input_mode == "image" else input_mode
        sources = [source]
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
        rank_reason=[{
            "image": "图片相似检索命中",
            "multimodal": "图文检索命中",
            "text": "文本语义检索命中",
        }.get(input_mode, "语义检索命中")],
    )


def _candidate_for_transport(candidate: Dict[str, Any], input_mode: str) -> Dict[str, Any]:
    """Build a bounded factual row for Tool transport and the existing Judge."""
    item = _ranked_product_from_candidate(candidate, input_mode)
    # Candidate Judge already consumes at most 400 description characters.
    # Bound Tool payloads as well so the extra S4 Agent step does not receive
    # unbounded catalog prose.
    item.description = item.description[:400]
    item.tags = item.tags[:500]
    return item.model_dump()


async def _judge_ranked_candidates(
    query: str,
    ranked: List[RankedProduct],
    preferences: Optional[Dict[str, Any]] = None,
) -> List[RankedProduct]:
    selected = await filter_recommendation_candidates(
        llm=get_llm(),
        query=query,
        candidates=[item.model_dump() for item in ranked],
        preferences=preferences,
    )
    return [RankedProduct.model_validate(item) for item in selected]
