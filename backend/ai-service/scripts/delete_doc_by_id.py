"""
按 doc_id 从 Milvus 向量库中删除指定文档及其切片。
用法：cd backend/ai-service && python scripts/delete_doc_by_id.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.vector_store import MilvusVectorStore


def main():
    doc_ids = [1, 2]

    print("=" * 50)
    print("Milvus 向量库文档删除")
    print("=" * 50)

    store = MilvusVectorStore()

    total_deleted = 0
    for doc_id in doc_ids:
        count = store.delete_by_doc_id(doc_id)
        print(f"  doc_id={doc_id}: 删除了 {count} 条向量切片")
        total_deleted += count

    print(f"\n总计: 删除了 {total_deleted} 条向量切片")


if __name__ == "__main__":
    main()
