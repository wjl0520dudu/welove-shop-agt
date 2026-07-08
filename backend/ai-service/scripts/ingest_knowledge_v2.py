"""电商商品知识文档批量灌入 v2（DashScope text-embedding-v4 + Milvus BM25 Function）。

**变化点 vs v1（backend/db/data/ingest_knowledge.py）**：
- 数据源从"内嵌 DOCUMENTS list"改成扫 `backend/db/data/ecommerce_agent_dataset/`
  的四个 category 子目录，逐个读商品 JSON 的 `rag_knowledge`
- 每个商品的 rag_knowledge 拆成 3 类 chunk：
    marketing_description → 一条"营销描述"chunk
    official_faq[]        → 每个 Q&A 一条 chunk（保留 Q+A 语义完整）
    user_reviews[]        → 每 3 条评价拼一条 chunk（低分/高分保留，帮真实对比）
- 不再写 MySQL knowledge_doc/knowledge_chunk 表（历史 Java 侧字段），
  后续如需 PG 侧知识文档表另加。
- 只灌 Milvus：文本 → DashScope v4 embedding + Milvus BM25 自动生成稀疏

用法：
    cd backend/ai-service
    python scripts/ingest_knowledge_v2.py                    # 全量灌
    python scripts/ingest_knowledge_v2.py --category beauty  # 只灌美妆
    python scripts/ingest_knowledge_v2.py --limit 5          # 每类只导前 5 个（冒烟）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# 让脚本能直接跑
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.models import ChunkMetadata, DocumentChunk  # noqa: E402
from rag.vector_store import create_vector_store  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_knowledge_v2")

# 数据集根目录：backend/db/data/ecommerce_agent_dataset/
DATASET_ROOT = Path(__file__).resolve().parents[2] / "db" / "data" / "ecommerce_agent_dataset"

# 目录名 → (category_id, category_label)
# category_id 与 Java/PG 侧 category 表对齐（1=美妆护肤 2=数码电子 3=服饰运动 4=食品生活）
CATEGORY_MAP: Dict[str, Tuple[int, str]] = {
    "1_美妆护肤": (1, "beauty"),
    "2_数码电子": (2, "digital"),
    "3_服饰运动": (3, "fashion"),
    "4_食品生活": (4, "food"),
}


def iter_product_files(category_filter: str | None, limit: int | None) -> Iterable[Tuple[Path, int, str]]:
    """遍历数据集，yield (json_path, category_id, category_label)。

    - category_filter: "beauty" / "digital" / "fashion" / "food" / None（全量）
    - limit: 每个 category 最多多少个商品（None 不限）
    """
    for dir_name, (cid, label) in CATEGORY_MAP.items():
        if category_filter and category_filter != label:
            continue
        data_dir = DATASET_ROOT / dir_name / "data"
        if not data_dir.exists():
            logger.warning("category 目录不存在：%s", data_dir)
            continue
        files = sorted(data_dir.glob("*.json"))
        if limit:
            files = files[:limit]
        for f in files:
            yield f, cid, label


def _product_id_to_int(pid: str) -> int:
    """把 'p_beauty_001' 这类字符串 ID 转成 category_id * 100000 + seq 的整型。

    Milvus 里的 product_id 是 INT64；PG 里的 products.id 是 BIGINT/SERIAL。
    这里做一个稳定映射，让两侧能对上：
      p_beauty_001  →  100001
      p_digital_012 →  200012
      p_fashion_030 →  300030
      p_food_007    →  400007
    """
    parts = pid.split("_")
    if len(parts) != 3:
        return 0
    # 数据集里服饰类 ID 前缀是 clothes（不是 fashion）—— 目录名 fashion 只是 category_label。
    category_prefix = {"beauty": 1, "digital": 2, "clothes": 3, "fashion": 3, "food": 4}.get(parts[1], 0)
    try:
        seq = int(parts[2])
    except ValueError:
        return 0
    return category_prefix * 100000 + seq


def build_chunks_for_product(
    product: Dict[str, Any],
    category_id: int,
    doc_id_seed: int,
) -> List[DocumentChunk]:
    """把单个商品的 rag_knowledge 拆成若干 chunk。

    doc_id_seed 是这个商品在 Milvus 里的 doc_id（不是数据库主键，是"文档级"标识），
    用整型的 product_id 映射值直接当 doc_id 也可以对齐 —— 简化维护。
    """
    product_id = _product_id_to_int(product.get("product_id", ""))
    title = product.get("title", "") or f"商品{product_id}"
    brand = product.get("brand", "")
    sub_category = product.get("sub_category", "")
    header = f"【商品】{title}｜品牌：{brand}｜类目：{sub_category}"

    rag = product.get("rag_knowledge", {}) or {}
    chunks: list[DocumentChunk] = []
    chunk_idx = 0

    def _mk(content: str, chunk_type: str) -> DocumentChunk:
        nonlocal chunk_idx
        c = DocumentChunk(
            content=content,
            metadata=ChunkMetadata(
                doc_id=doc_id_seed,
                product_id=product_id,
                category_id=category_id,
                source=product.get("product_id", ""),
                title=title,
                doc_type="product_knowledge",
                chunk_type=chunk_type,
                chunk_index=chunk_idx,
            ),
        )
        chunk_idx += 1
        return c

    # 1) 营销描述
    marketing = (rag.get("marketing_description") or "").strip()
    if marketing:
        chunks.append(_mk(f"{header}\n\n[营销描述]\n{marketing}", "marketing"))

    # 2) 官方 FAQ —— 一问一答一 chunk，保持语义完整
    for faq in rag.get("official_faq") or []:
        q = (faq.get("question") or "").strip()
        a = (faq.get("answer") or "").strip()
        if not (q and a):
            continue
        chunks.append(_mk(f"{header}\n\n[官方FAQ]\nQ：{q}\nA：{a}", "faq"))

    # 3) 用户评价 —— 3 条一 chunk（避免单条评价 chunk 过短检索不出）
    reviews = rag.get("user_reviews") or []
    for i in range(0, len(reviews), 3):
        batch = reviews[i : i + 3]
        lines = []
        for r in batch:
            nick = r.get("nickname", "匿名")
            rating = r.get("rating", "?")
            content = (r.get("content") or "").strip()
            if content:
                lines.append(f"- {nick}（{rating}星）：{content}")
        if lines:
            chunks.append(_mk(f"{header}\n\n[用户评价 #{i // 3 + 1}]\n" + "\n".join(lines), "review"))

    return chunks


def main():
    parser = argparse.ArgumentParser(description="灌入商品知识到 Milvus（DashScope v4 + BM25）")
    parser.add_argument("--category", choices=["beauty", "digital", "fashion", "food"], default=None,
                        help="只灌某个类目；不填=全量")
    parser.add_argument("--limit", type=int, default=None,
                        help="每个类目最多灌多少商品（冒烟测试用，None=不限）")
    args = parser.parse_args()

    print("=" * 60)
    print("商品知识灌入 v2（DashScope text-embedding-v4 + Milvus BM25）")
    print(f"数据集：{DATASET_ROOT}")
    print(f"过滤：category={args.category or '全量'} limit={args.limit or '不限'}")
    print("=" * 60)

    vector_store = create_vector_store()
    print(f"[OK] 向量库就绪：{vector_store.stats()}")

    total_products = 0
    total_chunks = 0
    per_category: dict[str, int] = {}

    for json_path, category_id, category_label in iter_product_files(args.category, args.limit):
        try:
            product = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("跳过 %s：解析失败 %s", json_path.name, e)
            continue

        product_id_int = _product_id_to_int(product.get("product_id", ""))
        chunks = build_chunks_for_product(product, category_id=category_id, doc_id_seed=product_id_int)
        if not chunks:
            logger.info("跳过 %s：无 rag_knowledge", json_path.name)
            continue

        try:
            vector_store.upsert_chunks(chunks)
        except Exception:  # noqa: BLE001
            logger.exception("灌入失败：%s", json_path.name)
            continue

        total_products += 1
        total_chunks += len(chunks)
        per_category[category_label] = per_category.get(category_label, 0) + 1
        print(f"  [{total_products:04d}] {product.get('product_id')} — {product.get('title')[:32]}… ({len(chunks)} chunks)")

    print()
    print("=" * 60)
    print(f"[DONE] 灌入完成")
    print(f"  商品数: {total_products}")
    print(f"  分块数: {total_chunks}")
    for cat, n in per_category.items():
        print(f"    {cat}: {n} 个商品")
    print("=" * 60)


if __name__ == "__main__":
    main()
