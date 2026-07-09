"""针对全量 100 商品数据集，跑几条真实用户会问的 query，
验证三种检索模式的最终效果。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.models import RetrievalPlan  # noqa: E402
from rag.retriever import get_retriever  # noqa: E402

# 覆盖不同风格：品牌昵称、成分咨询、场景需求、精确型号、跨类目
QUERIES = [
    "小棕瓶适合敏感肌吗",              # 中文品牌昵称
    "视黄醇和烟酰胺可以一起用吗",       # 成分搭配（知识+商品混合）
    "推荐一款控油的粉底液",             # 场景+品类
    "SK-II 神仙水 230ml",              # 精确型号
    "iPhone 17 Pro Max 拍照能力怎么样",  # 英文长尾
    "运动 T 恤 吸汗透气",              # 短语
    "低脂零食推荐",                     # 泛化
]


def run_query(query: str, mode: str, top_k: int = 3):
    plan = RetrievalPlan(query=query, top_k=top_k, search_mode=mode)
    out = get_retriever().retrieve(plan)
    print(f"\n  [{mode:6s}] ({len(out.results)} 命中)")
    for i, r in enumerate(out.results, 1):
        title = (r.metadata.title or r.metadata.source or "").strip()
        snippet = (r.content or "").replace("\n", " ").strip()[:70]
        print(f"    {i}. {r.score:>7.4f}  {title[:40]}")
        print(f"                     … {snippet}")


def main():
    for q in QUERIES:
        print("\n" + "=" * 80)
        print(f"[Q] {q}")
        print("=" * 80)
        for mode in ("dense", "bm25", "hybrid"):
            try:
                run_query(q, mode)
            except Exception as e:  # noqa: BLE001
                print(f"  [{mode}] ERROR: {e}")


if __name__ == "__main__":
    main()
