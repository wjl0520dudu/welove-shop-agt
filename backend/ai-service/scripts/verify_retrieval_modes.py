"""端到端验证三种检索模式。

对每条 query 分别跑 dense / bm25 / hybrid，打印 top-3 结果，人眼看差异。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.models import RetrievalPlan  # noqa: E402
from rag.retriever import get_retriever  # noqa: E402

QUERIES = [
    "小棕瓶精华适合敏感肌吗",       # 中文语义 + 品牌昵称
    "iPhone 17 Pro 拍照怎么样",     # 英文品牌 + 中文长尾
    "咖啡有什么推荐",               # 泛化语义
    "T恤面料透气性",                # 短语+专有词
]


def run_query(query: str, mode: str, top_k: int = 3):
    plan = RetrievalPlan(query=query, top_k=top_k, search_mode=mode)
    out = get_retriever().retrieve(plan)
    print(f"\n  --- mode={mode} ({len(out.results)} 命中) ---")
    for i, r in enumerate(out.results, 1):
        title = r.metadata.title or r.metadata.source
        snippet = (r.content or "").replace("\n", " ").strip()[:80]
        print(f"    {i}. score={r.score:.4f}  {title}")
        print(f"       {snippet}…")


def main():
    for q in QUERIES:
        print("\n" + "=" * 70)
        print(f"[Q] {q}")
        print("=" * 70)
        for mode in ("dense", "bm25", "hybrid"):
            try:
                run_query(q, mode)
            except Exception as e:  # noqa: BLE001
                print(f"  ({mode}) ERROR: {e}")


if __name__ == "__main__":
    main()
