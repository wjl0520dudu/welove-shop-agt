"""对比 rerank on/off 在真实检索里的效果差异。

同一 query 走两次：先 hybrid-only（use_rerank=False），再 hybrid+rerank（use_rerank=True），
看 top-5 排序是否有质变。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.models import RetrievalPlan  # noqa: E402
from rag.retriever import get_retriever  # noqa: E402

QUERIES = [
    "视黄醇和烟酰胺可以一起用吗",     # 通用成分搭配（rerank 应把成分文档拱到最前）
    "敏感肌用什么成分修复屏障",       # 商品 vs 通用混合
    "iPhone 17 Pro Max 拍照怎么样",   # 精确型号
    "熬夜后用什么精华修复",           # 场景 → 商品/通用混合
    "小棕瓶适合敏感肌吗",             # 品牌昵称
]


def run_once(query: str, use_rerank: bool):
    plan = RetrievalPlan(query=query, top_k=5, use_rerank=use_rerank)
    t0 = time.perf_counter()
    out = get_retriever().retrieve(plan)
    dt = (time.perf_counter() - t0) * 1000
    return out, dt


def fmt_result(r):
    dtype = r.metadata.doc_type or "?"
    title = (r.metadata.title or r.metadata.source or "")[:38]
    return f"[{dtype:18s}] {title}  score={r.score:.4f}"


def main():
    for q in QUERIES:
        print("\n" + "=" * 90)
        print(f"[Q] {q}")
        print("=" * 90)

        out_off, dt_off = run_once(q, use_rerank=False)
        print(f"\n  ── rerank OFF （单阶段 hybrid，{dt_off:.0f}ms）──")
        for i, r in enumerate(out_off.results, 1):
            print(f"    {i}. {fmt_result(r)}")

        out_on, dt_on = run_once(q, use_rerank=True)
        print(f"\n  ── rerank ON （两阶段 hybrid→rerank，{dt_on:.0f}ms）──")
        for i, r in enumerate(out_on.results, 1):
            print(f"    {i}. {fmt_result(r)}")

        # 顺序对比
        off_ids = [(r.metadata.doc_id, r.metadata.chunk_index) for r in out_off.results]
        on_ids = [(r.metadata.doc_id, r.metadata.chunk_index) for r in out_on.results]
        if off_ids == on_ids:
            print("\n  → 顺序一致，rerank 未改变 top-5")
        else:
            changed = sum(1 for a, b in zip(off_ids, on_ids) if a != b)
            print(f"\n  → rerank 改动了 {changed}/{len(on_ids)} 个位置")


if __name__ == "__main__":
    main()
