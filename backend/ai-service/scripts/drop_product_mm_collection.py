"""清空商品多模态 collection —— 一次性删表。

用途：schema 改动（新增字段、改 dim、改 analyzer）后必须清库重建。
不删知识 collection（那个走 scripts/drop_milvus_collection.py）。

用法：
    python scripts/drop_product_mm_collection.py --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymilvus import MilvusClient   # noqa: E402

from core.config import config       # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop 商品多模态 Milvus collection")
    parser.add_argument("--yes", action="store_true", help="确认执行删除，不加就干跑")
    parser.add_argument("--collection", default=config.MILVUS_PRODUCT_COLLECTION,
                        help="要删的 collection 名称（默认走 config）")
    args = parser.parse_args()

    client = MilvusClient(uri=config.MILVUS_URL)
    coll = args.collection

    if not client.has_collection(coll):
        print(f"[skip] collection '{coll}' 不存在，无需删除。")
        return

    if not args.yes:
        print(f"[dry-run] 将要删除 collection '{coll}'。加 --yes 才真删。")
        return

    client.drop_collection(coll)
    print(f"[ok] 已删除 collection '{coll}'。")


if __name__ == "__main__":
    main()
