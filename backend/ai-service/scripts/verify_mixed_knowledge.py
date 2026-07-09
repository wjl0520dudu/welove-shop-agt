"""验证通用知识 + 商品知识两类共存后的检索表现。

针对性挑 3 类 query：
1. 纯通用知识类 → 应命中 doc_type="general_knowledge"（成分搭配/肤质/面料）
2. 纯商品类     → 应命中 doc_type="product_knowledge"（具体商品 FAQ/评价）
3. 混合类       → 两类都会命中，看 hybrid 排序合不合理
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymilvus import Collection, connections  # noqa: E402
from core.config import config  # noqa: E402
from rag.models import RetrievalPlan  # noqa: E402
from rag.retriever import get_retriever  # noqa: E402


CASES = [
    # (query, 期望类型)
    ("视黄醇和烟酰胺可以一起用吗", "general_knowledge"),
    ("敏感肌用什么成分修复屏障", "general_knowledge"),
    ("羊绒和羊毛的区别", "general_knowledge"),
    ("拍照优先选哪款手机", "general_knowledge"),

    ("雅诗兰黛小棕瓶适合敏感肌吗", "product_knowledge"),
    ("SK-II 神仙水 230ml 怎么用", "product_knowledge"),
    ("iPhone 17 Pro Max 大屏体验", "product_knowledge"),
    ("Nike Dri-FIT T恤会掉色吗", "product_knowledge"),

    # 混合类：通用知识 + 具体商品都有关
    ("控油粉底液怎么选", "混合"),
    ("熬夜后用什么精华修复", "混合"),
]


def total_entities() -> int:
    connections.connect(uri=config.MILVUS_URL)
    c = Collection(config.MILVUS_COLLECTION)
    c.load()
    return c.num_entities


def run_case(query: str, expected: str):
    print("\n" + "=" * 80)
    print(f"[Q] {query}")
    print(f"    期望类型: {expected}")
    print("=" * 80)

    for mode in ("dense", "bm25", "hybrid"):
        plan = RetrievalPlan(query=query, top_k=3, search_mode=mode)
        out = get_retriever().retrieve(plan)
        print(f"\n  [{mode:6s}]")
        for i, r in enumerate(out.results, 1):
            dtype = r.metadata.doc_type or "?"
            title = (r.metadata.title or r.metadata.source or "").strip()[:44]
            snippet = (r.content or "").replace("\n", " ").strip()[:70]
            marker = "✓" if dtype == expected or expected == "混合" else "?"
            print(f"    {i}. {marker} score={r.score:>7.4f} [{dtype:18s}] {title}")
            print(f"                     … {snippet}")


def main():
    n = total_entities()
    print(f"[i] Milvus 当前总 chunk 数: {n}")

    for query, expected in CASES:
        run_case(query, expected)


if __name__ == "__main__":
    main()
