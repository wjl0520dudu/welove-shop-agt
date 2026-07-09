"""清空 Milvus collection。

**使用时机**：schema 有 breaking change（新增/删除字段、维度变更），需要一次性清库重建。
本次 RAG 增强就是这种情况：
- dense 维度 1536 → 1024
- 新增 BM25 Function + sparse_vector 由服务端自动生成
- 新增 product_id 字段

用法：
    python scripts/drop_milvus_collection.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本能直接 `python scripts/drop_milvus_collection.py` 起来
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import config  # noqa: E402
from pymilvus import connections, MilvusClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="删除 Milvus collection（清库）")
    parser.add_argument(
        "--collection",
        default=config.MILVUS_COLLECTION,
        help=f"collection 名称，默认 {config.MILVUS_COLLECTION}",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过交互确认，直接删除（用于 CI/自动化）",
    )
    args = parser.parse_args()

    print(f"[i] Milvus URL: {config.MILVUS_URL}")
    print(f"[i] Collection: {args.collection}")

    connections.connect(uri=config.MILVUS_URL)
    client = MilvusClient(uri=config.MILVUS_URL)

    if not client.has_collection(args.collection):
        print(f"[i] Collection '{args.collection}' 不存在，无需删除。")
        return

    if not args.yes:
        confirm = input(f"[?] 确认删除 collection '{args.collection}' 及其所有数据？(yes/no): ").strip().lower()
        if confirm not in ("y", "yes"):
            print("[i] 已取消。")
            return

    client.drop_collection(args.collection)
    print(f"[OK] Collection '{args.collection}' 已删除。")


if __name__ == "__main__":
    main()
