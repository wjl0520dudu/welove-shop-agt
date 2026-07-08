"""对比商品 collection 里 dense / bm25 / hybrid 三路 + rerank on/off 的效果。

用法：
    python scripts/verify_product_search_modes.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shopping.vector_store import get_product_milvus_store   # noqa: E402
from rag.reranker import get_reranker                        # noqa: E402


QUERIES = [
    # 场景 → 期望什么类目的商品排前
    ("推荐一款油皮防晒",         {"expect": "防晒/隔离"}),
    ("iPhone 17 Pro Max 拍照怎么样", {"expect": "手机（数码）"}),
    ("运动 T 恤透气",             {"expect": "T恤/运动"}),
    ("送妈妈的护肤礼盒",           {"expect": "护肤/礼盒"}),
    ("低脂零食",                 {"expect": "零食/低脂"}),
    ("敏感肌用什么面霜",           {"expect": "面霜/敏感肌"}),
]


def _fmt(item):
    title = (item.get("title") or "")[:36]
    cat = item.get("category") or ""
    sub = item.get("sub_category") or ""
    price = item.get("base_price")
    score = item.get("score", 0)
    return f"[{cat}/{sub:<8s}] {title} ￥{price} score={score:.4f}"


def run_mode(store, query, mode, top_k=5):
    t0 = time.perf_counter()
    out = store.search(query=query, mode=mode, top_k=top_k)
    dt = (time.perf_counter() - t0) * 1000
    return out, dt


def run_with_rerank(store, query, top_k=5, initial_top_k=20):
    """两阶段：hybrid 召回 initial_top_k → qwen3-rerank 精排。"""
    t0 = time.perf_counter()
    recall = store.hybrid_search(query, top_k=initial_top_k)
    if not recall:
        return [], (time.perf_counter() - t0) * 1000

    reranker = get_reranker()
    docs = [
        " ".join([r.get("title") or "", r.get("brand") or "",
                  r.get("tags") or "", (r.get("description") or "")[:400]]).strip()
        for r in recall
    ]
    pairs = reranker.rerank(query, docs, top_n=top_k)
    if pairs and all(s == 0.0 for _, s in pairs):
        # 降级：退回向量顺序
        out = sorted(recall, key=lambda r: r.get("score", 0), reverse=True)[:top_k]
    else:
        out = []
        for idx, score in pairs:
            if 0 <= idx < len(recall):
                item = dict(recall[idx])
                item["rerank_score"] = float(score)
                item["score"] = float(score)
                out.append(item)
    dt = (time.perf_counter() - t0) * 1000
    return out, dt


def main():
    store = get_product_milvus_store()
    print("Milvus stats:", store.stats())

    for query, meta in QUERIES:
        print("\n" + "=" * 90)
        print(f"[Q] {query}   预期类目 → {meta['expect']}")
        print("=" * 90)

        for mode in ("dense", "bm25", "hybrid"):
            out, dt = run_mode(store, query, mode, top_k=5)
            print(f"\n  ── {mode.upper()} （{dt:.0f}ms） ──")
            for i, r in enumerate(out, 1):
                print(f"    {i}. {_fmt(r)}")

        # hybrid + rerank
        out, dt = run_with_rerank(store, query, top_k=5)
        print(f"\n  ── HYBRID + RERANK （{dt:.0f}ms 两阶段） ──")
        for i, r in enumerate(out, 1):
            print(f"    {i}. {_fmt(r)}")


if __name__ == "__main__":
    main()
