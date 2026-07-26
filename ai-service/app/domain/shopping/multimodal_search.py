"""product_mm_v2 图文混合检索实验接口。

本模块提供多模态商品检索路线：
- v1：text_dense + BM25 + image_vector → RRF → qwen3-vl-rerank；生产开关开启时读取三路生产 collection
- v2：v1 + multimodal_vector → RRF → qwen3-vl-rerank
- v3：v2 四路召回 → RRF → WeightedRanker
- v4：单路 multimodal_vector（查询图文融合向量 → 匹配 multimodal_vector，无 RRF 无 rerank）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from app.infrastructure.retrieval.multimodal_embeddings import (
    embed_fusion,
    embed_image,
    multimodal_rerank,
)
from app.domain.shopping.category_resolver import normalize_product_category
from app.infrastructure.config import config
from app.infrastructure.vectorstores.product.vector_store_v2 import get_product_milvus_store_v2
from app.infrastructure.vectorstores.product.vector_store_three_path import get_product_milvus_store_three_path

logger = logging.getLogger("ai-service.shopping.multimodal_search")


def extract_explicit_product_filters(query_text: str) -> Dict[str, Any]:
    """Low-cost constraints for image retrieval; never infer a budget silently."""
    import re
    text = query_text or ""
    filters: Dict[str, Any] = {"status": 1}
    max_match = re.search(r"(\d+(?:\.\d+)?)\s*元?(?:以内|以下|不超过|最多)", text)
    min_match = re.search(r"(\d+(?:\.\d+)?)\s*元?(?:以上|起)", text)
    if max_match:
        filters["budget_max"] = float(max_match.group(1))
    if min_match:
        filters["budget_min"] = float(min_match.group(1))
    category = normalize_product_category(text)
    if category:
        filters["category"] = category
    return filters


def enforce_explicit_product_filters(items: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        price = item.get("base_price", item.get("price"))
        if filters.get("budget_max") is not None and (price is None or float(price) > float(filters["budget_max"])):
            continue
        if filters.get("budget_min") is not None and (price is None or float(price) < float(filters["budget_min"])):
            continue
        if filters.get("status") is not None and item.get("status") is not None and int(item["status"]) != int(filters["status"]):
            continue
        out.append(item)
    return out


_ROUTE_SCORE_FIELDS = ("dense_score", "bm25_score", "sparse_score", "image_score", "multimodal_score")


def _is_nonzero_vector(vector: list[float]) -> bool:
    return any(abs(float(x or 0.0)) > 1e-12 for x in vector)


def _merge_sources(target: dict, source: dict) -> None:
    srcs = target.setdefault("recall_sources", [])
    for s in source.get("recall_sources") or []:
        if s not in srcs:
            srcs.append(s)


def _merge_candidate(base: dict, incoming: dict) -> dict:
    """同一商品多路命中时合并分数和召回来源。"""
    out = dict(base)
    for key, value in incoming.items():
        if key in _ROUTE_SCORE_FIELDS:
            if key not in out or float(value or 0.0) > float(out.get(key) or 0.0):
                out[key] = float(value or 0.0)
        elif key in ("score", "distance"):
            if float(value or 0.0) > float(out.get(key) or 0.0):
                out[key] = float(value or 0.0)
        elif key != "recall_sources" and (out.get(key) in (None, "")):
            out[key] = value
    _merge_sources(out, incoming)
    return out


def rrf_fusion(
    result_groups: List[List[Dict[str, Any]]],
    k: int = 60,
    id_field: str = "product_id",
) -> List[Dict[str, Any]]:
    """多路结果 RRF 融合 + 去重。

    同一 product_id 多次出现时，会合并各路分数和 recall_sources；
    最终 `score` 使用 `rrf_score`，便于下游按融合结果截断。
    """
    deduped: dict[str, dict] = {}
    rrf_scores: dict[str, float] = {}

    for group in result_groups:
        for rank, item in enumerate(group):
            if id_field not in item or item.get(id_field) is None:
                continue
            pid = str(item[id_field])
            incoming = dict(item)
            if pid in deduped:
                deduped[pid] = _merge_candidate(deduped[pid], incoming)
            else:
                deduped[pid] = incoming
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (k + rank + 1)

    result: list[dict[str, Any]] = []
    for pid in sorted(rrf_scores, key=rrf_scores.get, reverse=True):
        item = dict(deduped[pid])
        item["rrf_score"] = float(rrf_scores[pid])
        item["score"] = float(rrf_scores[pid])
        result.append(item)
    return result


def weighted_rerank(
    candidates: List[Dict[str, Any]],
    weights: Sequence[float] = (0.3, 0.2, 0.3, 0.2),
) -> List[Dict[str, Any]]:
    """按四路原始分数加权重排。

    weights 顺序：text_dense, bm25, image, multimodal。
    缺失分数按 0 处理。
    """
    if len(weights) != 4:
        raise ValueError("weights 必须包含 4 个值：dense/bm25/image/multimodal")

    out: list[dict[str, Any]] = []
    for item in candidates:
        doc = dict(item)
        bm25_score = doc.get("bm25_score", doc.get("sparse_score", 0.0))
        weighted_score = (
            float(weights[0]) * float(doc.get("dense_score") or 0.0)
            + float(weights[1]) * float(bm25_score or 0.0)
            + float(weights[2]) * float(doc.get("image_score") or 0.0)
            + float(weights[3]) * float(doc.get("multimodal_score") or 0.0)
        )
        doc["weighted_score"] = weighted_score
        doc["score"] = weighted_score
        srcs = doc.setdefault("recall_sources", [])
        if "weighted_ranker" not in srcs:
            srcs.append("weighted_ranker")
        out.append(doc)
    return sorted(out, key=lambda x: x.get("weighted_score", 0.0), reverse=True)


def _safe_path(path_name: str, fn) -> list[dict[str, Any]]:
    try:
        return fn() or []
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 召回失败，跳过该路：%s", path_name, e, exc_info=True)
        return []


def _recall_paths(
    query_text: str,
    query_image_url: str | None,
    *,
    top_k: int,
    filters: Optional[Dict[str, Any]],
    include_multimodal: bool,
    store=None,
) -> List[List[Dict[str, Any]]]:
    """执行三路/四路召回，返回按路径分组的结果。"""
    store = store or get_product_milvus_store_v2()
    recall_top_k = max(int(top_k) * 2, int(top_k), 1)
    groups: list[list[dict[str, Any]]] = []

    if query_text and query_text.strip():
        text = query_text.strip()

        def dense_path():
            return store.dense_search(text, filters=filters, top_k=recall_top_k)

        groups.append(_safe_path("text_dense", dense_path))
        groups.append(_safe_path("bm25", lambda: store.bm25_search(text, filters=filters, top_k=recall_top_k)))

    if query_image_url:
        image_vec = embed_image(query_image_url)
        if _is_nonzero_vector(image_vec):
            groups.append(_safe_path(
                "image_vector",
                lambda: store.image_vector_search(image_vec, filters=filters, top_k=recall_top_k),
            ))
        else:
            logger.warning("image embedding 返回零向量，跳过 image_vector 召回")

        if include_multimodal:
            fusion_vec = embed_fusion(query_text, query_image_url)
            if _is_nonzero_vector(fusion_vec):
                groups.append(_safe_path(
                    "multimodal_vector",
                    lambda: store.multimodal_vector_search(fusion_vec, filters=filters, top_k=recall_top_k),
                ))
            else:
                logger.warning("fusion embedding 返回零向量，跳过 multimodal_vector 召回")

    return groups


def recall_three_path_candidates(
    query_text: str,
    query_image_url: str | None = None,
    *,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    store=None,
    candidate_top_k: int | None = None,
) -> List[Dict[str, Any]]:
    """Recall available production paths and fuse them with RRF.

    Text only uses dense plus BM25, image only uses the image vector, and a
    text/image request uses all three paths.  Reranking stays with the caller:
    text requests use qwen3-rerank and image requests use qwen3-vl-rerank.
    """
    top_k = max(int(top_k or 10), 1)
    groups = _recall_paths(
        query_text=query_text,
        query_image_url=query_image_url,
        top_k=top_k,
        filters=filters,
        include_multimodal=False,
        store=store,
    )
    fused = rrf_fusion(groups, k=60)
    return fused[:max(int(candidate_top_k or top_k), 1)]


async def search_multimodal_v1(
    query_text: str,
    query_image_url: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """接口①：三路融合 + qwen3-vl-rerank。"""
    top_k = max(int(top_k or 10), 1)
    # 生产开关仅影响最终选择的三路 v1；v2-v5 仍使用实验 collection，
    # 因为它们依赖生产 schema 刻意不保存的 multimodal_vector。
    store = (
        get_product_milvus_store_three_path()
        if config.SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION
        else get_product_milvus_store_v2()
    )
    candidates = recall_three_path_candidates(
        query_text=query_text,
        query_image_url=query_image_url,
        top_k=top_k,
        filters=filters,
        store=store,
        candidate_top_k=top_k * 2,
    )
    return multimodal_rerank(
        query_text=query_text,
        query_image_url=query_image_url,
        documents=candidates,
        top_n=top_k,
    )


async def search_multimodal_v2(
    query_text: str,
    query_image_url: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """接口②：四路融合 + qwen3-vl-rerank。"""
    top_k = max(int(top_k or 10), 1)
    groups = _recall_paths(
        query_text=query_text,
        query_image_url=query_image_url,
        top_k=top_k,
        filters=filters,
        include_multimodal=True,
    )
    fused = rrf_fusion(groups, k=60)
    candidates = fused[: top_k * 2]
    return multimodal_rerank(
        query_text=query_text,
        query_image_url=query_image_url,
        documents=candidates,
        top_n=top_k,
    )


async def search_multimodal_v3(
    query_text: str,
    query_image_url: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    weights: Sequence[float] = (0.3, 0.2, 0.3, 0.2),
) -> List[Dict[str, Any]]:
    """接口③：四路融合 + WeightedRanker。"""
    top_k = max(int(top_k or 10), 1)
    groups = _recall_paths(
        query_text=query_text,
        query_image_url=query_image_url,
        top_k=top_k,
        filters=filters,
        include_multimodal=True,
    )
    fused = rrf_fusion(groups, k=60)
    weighted = weighted_rerank(fused, weights=weights)
    return weighted[:top_k]


async def search_multimodal_v4(
    query_text: str,
    query_image_url: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """接口④：单路多模态向量检索。

    查询侧把 (query_text, query_image_url) 走 qwen3-vl-embedding + enable_fusion
    拼成一个融合向量，直接在 product_mm_v2.multimodal_vector 上做向量搜索，
    不走 RRF、不走 rerank。用来对比"多路融合 + 精排"到底比"单路多模态"好在哪。

    没有查询图片或图文融合向量返回零向量时降级为空列表——单路多模态无 fallback。
    """
    top_k = max(int(top_k or 10), 1)

    if not query_image_url:
        logger.warning("v4 单路多模态需要 query_image_url，未提供 → 返回空")
        return []

    fusion_vec = embed_fusion(query_text, query_image_url)
    if not _is_nonzero_vector(fusion_vec):
        logger.warning("v4 fusion embedding 返回零向量 → 返回空")
        return []

    store = get_product_milvus_store_v2()
    try:
        results = store.multimodal_vector_search(
            fusion_vec, filters=filters, top_k=top_k,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("v4 multimodal_vector_search 失败：%s", e, exc_info=True)
        return []

    return results[:top_k]


async def search_multimodal_v5(
    query_text: str,
    query_image_url: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """接口⑤：单路图文融合召回 + qwen3-vl-rerank。

    与 v4 使用相同的 ``multimodal_vector`` 候选空间，唯一变量是对
    Top(2 * top_k) 候选调用多模态重排，用于隔离并量化 VL rerank 的增益。
    """
    top_k = max(int(top_k or 10), 1)
    if not query_image_url:
        logger.warning("v5 单路多模态需要 query_image_url，未提供 → 返回空")
        return []

    fusion_vec = embed_fusion(query_text, query_image_url)
    if not _is_nonzero_vector(fusion_vec):
        logger.warning("v5 fusion embedding 返回零向量 → 返回空")
        return []

    store = get_product_milvus_store_v2()
    try:
        candidates = store.multimodal_vector_search(
            fusion_vec,
            filters=filters,
            top_k=top_k * 2,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("v5 multimodal_vector_search 失败：%s", e, exc_info=True)
        return []

    return multimodal_rerank(
        query_text=query_text,
        query_image_url=query_image_url,
        documents=candidates,
        top_n=top_k,
    )
