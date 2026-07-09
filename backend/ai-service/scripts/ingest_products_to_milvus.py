"""把 backend/db/data 里的 100 商品灌进 Milvus product_mm_collection。

⚠️ **LEGACY / 冷启专用** —— 生产运维**不要**走这个脚本！

## 什么时候用它

只在 PG 里还没有商品数据、需要给 Milvus 灌一批冒烟数据时用。它的 product_id
是从 JSON 里的字符串 code（"p_beauty_001"）**合成**出来的（100001 / 200001 / ...），
跟 PG 的 product.id（1-100 自然主键）**对不上**。

## 生产运维走哪个？

`scripts/sync_products_pg_to_milvus.py` —— 那个是权威路径：
- PG 是商品的唯一真源
- Milvus product_id = PG.id（一一对应，无需映射转换）
- 支持全量 / 增量 / 单商品同步 + watermark

## 数据源

```
backend/db/data/ecommerce_agent_dataset/
  1_美妆护肤/data/p_beauty_*.json    (25 商品)
  2_数码电子/data/p_digital_*.json   (25 商品)
  3_服饰运动/data/p_clothes_*.json   (25 商品)
  4_食品生活/data/p_food_*.json      (25 商品)
```

每个 JSON 有 title / brand / category / sub_category / base_price / image_path /
skus / rag_knowledge。rag_knowledge.marketing_description 用来做 description（→ BM25 + dense）。

## product_id 映射（**仅本 legacy 脚本使用**）

数据集里的 product_id 是字符串 `p_beauty_001`。Milvus 主键必须 INT64，用：
    prefix_num * 100000 + seq
    beauty=1 → 100001, digital=2 → 200001, clothes=3 → 300001, food=4 → 400001

跑完之后**必须**接一次 `sync_products_pg_to_milvus.py --mode full` 把合成 id
数据换成 PG.id 数据（sync 脚本会 diff 出老 id 并自动删除）。

## 用法（仅冷启）

    # 冒烟：每类灌 3 个 = 12 商品
    python scripts/ingest_products_to_milvus.py --limit 3

    # 全量
    python scripts/ingest_products_to_milvus.py

    # 单类
    python scripts/ingest_products_to_milvus.py --category beauty --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shopping.vector_store import get_product_milvus_store   # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("ingest_products")


# 数据集目录 → 内部类目名 + product_id 前缀数
_CATEGORY_DIRS = {
    "beauty": ("1_美妆护肤", 1),
    "digital": ("2_数码电子", 2),
    "clothes": ("3_服饰运动", 3),
    "fashion": ("3_服饰运动", 3),   # alias
    "food": ("4_食品生活", 4),
}


def _resolve_data_root() -> Path:
    """确定 backend/db/data/ecommerce_agent_dataset/ 位置。

    ai-service 在 backend/ai-service/，往上一级到 backend/db/data/...
    """
    return Path(__file__).resolve().parents[2] / "db" / "data" / "ecommerce_agent_dataset"


def _string_id_to_int(pid_str: str) -> Optional[int]:
    """`p_beauty_001` → 100001 / `p_digital_012` → 200012 / `p_clothes_003` → 300003。

    找不到映射返回 None（这条商品跳过）。
    """
    parts = pid_str.split("_")
    if len(parts) < 3:
        return None
    prefix = parts[1]
    cat_prefix = {"beauty": 1, "digital": 2, "clothes": 3, "fashion": 3, "food": 4}.get(prefix)
    if cat_prefix is None:
        return None
    try:
        seq = int(parts[2])
    except ValueError:
        return None
    return cat_prefix * 100000 + seq


def _image_url_from_path(image_path: str) -> str:
    """数据集里 image_path 是 `1_美妆护肤/images/p_beauty_001_live.jpg`。

    MVP 阶段图片还没上 OSS/CDN，先把相对路径塞进 image_url，前端渲染时兜底 placeholder。
    Phase 2 图片就绪时改成完整 URL。
    """
    return image_path or ""


def _tags_from_rag(rag: Dict[str, Any]) -> str:
    """从 rag_knowledge.user_reviews 抽 5 条评论关键词拼成 tags。

    MVP：直接取 reviews 前 5 条内容各取前 30 字符拼接。
    足够给 BM25 / rerank 用；不做 LLM 关键词抽取（那是 Phase 2 优化）。
    """
    reviews = rag.get("user_reviews") or []
    parts: List[str] = []
    for r in reviews[:5]:
        if isinstance(r, dict):
            content = str(r.get("content") or r.get("comment") or "")
        else:
            content = str(r)
        content = content.strip()[:30]
        if content:
            parts.append(content)
    return " ".join(parts)


def _load_one_product(json_path: Path, cat_key: str) -> Optional[Dict[str, Any]]:
    """把一个 JSON 文件读成 ProductMilvusStore.upsert_products 需要的 dict。

    返回 None 表示这条数据不合法（缺 product_id 或 title）。
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pid_str = data.get("product_id") or ""
    pid_int = _string_id_to_int(pid_str)
    if pid_int is None:
        logger.warning("跳过 %s：product_id=%s 无法映射到 int", json_path.name, pid_str)
        return None

    title = str(data.get("title") or "").strip()
    if not title:
        logger.warning("跳过 %s：缺 title", json_path.name)
        return None

    rag = data.get("rag_knowledge") or {}
    description = str(rag.get("marketing_description") or "").strip()
    tags = _tags_from_rag(rag)

    return {
        "product_id": pid_int,
        "title": title,
        "brand": str(data.get("brand") or ""),
        "category": str(data.get("category") or ""),
        "sub_category": str(data.get("sub_category") or ""),
        "base_price": float(data.get("base_price") or 0),
        "image_url": _image_url_from_path(str(data.get("image_path") or "")),
        "description": description,
        "tags": tags,
        # 数据集没有 rating/sales_count/review_count，给合成默认值：
        # 让不同商品有区分度 —— 用 product_id 尾数做种子造点差异（避免所有商品排序完全一样）
        "rating": round(4.0 + (pid_int % 10) / 10.0, 1),   # 4.0-4.9
        "sales_count": 100 + (pid_int % 100) * 10,          # 100-1090
        "review_count": 20 + (pid_int % 50) * 5,             # 20-265
        "status": 1,
    }


def _collect_json_files(data_root: Path, category: Optional[str], limit: Optional[int]) -> List[tuple[Path, str]]:
    """收集要处理的 JSON 文件列表：(path, cat_key)。"""
    if category:
        target_keys = [category]
    else:
        target_keys = ["beauty", "digital", "clothes", "food"]

    files: List[tuple[Path, str]] = []
    for cat_key in target_keys:
        dir_name, _ = _CATEGORY_DIRS[cat_key]
        cat_dir = data_root / dir_name / "data"
        if not cat_dir.exists():
            logger.warning("类目目录不存在：%s", cat_dir)
            continue
        json_files = sorted(cat_dir.glob("*.json"))
        if limit is not None:
            json_files = json_files[:limit]
        for jf in json_files:
            files.append((jf, cat_key))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="[LEGACY] Ingest products to Milvus product_mm_collection from JSON files. "
                    "生产运维请用 sync_products_pg_to_milvus.py",
    )
    parser.add_argument("--limit", type=int, default=None, help="每类最多灌几个（冒烟用）")
    parser.add_argument("--category", choices=list(_CATEGORY_DIRS.keys()),
                        help="只灌指定类目（beauty/digital/clothes/food）")
    parser.add_argument("--batch-size", type=int, default=10, help="每批 upsert 多少个（DashScope 单次 batch=10）")
    args = parser.parse_args()

    logger.warning(
        "⚠️  这是 legacy 冷启脚本。product_id 从 JSON code 合成（100001~），"
        "跟 PG.id（1~100）**不一致**。跑完后必须接 sync_products_pg_to_milvus.py --mode full "
        "把合成 id 数据替换成 PG.id 数据。生产运维不要走这个脚本。"
    )

    data_root = _resolve_data_root()
    if not data_root.exists():
        raise FileNotFoundError(f"数据目录不存在：{data_root}")

    files = _collect_json_files(data_root, args.category, args.limit)
    if not files:
        print("[skip] 没有找到要灌的 JSON 文件。")
        return

    logger.info("准备灌入 %d 个商品（category=%s, limit=%s）", len(files), args.category, args.limit)

    store = get_product_milvus_store()
    logger.info("Milvus stats: %s", store.stats())

    # 分批灌，DashScope embedding 每批最多 10 条
    total_ok = 0
    t0 = time.perf_counter()
    for i in range(0, len(files), args.batch_size):
        batch_files = files[i : i + args.batch_size]
        batch_products: List[Dict[str, Any]] = []
        for jf, cat_key in batch_files:
            p = _load_one_product(jf, cat_key)
            if p:
                batch_products.append(p)

        if not batch_products:
            continue

        try:
            n = store.upsert_products(batch_products)
        except Exception:  # noqa: BLE001
            logger.exception("batch upsert 失败，跳过该批")
            continue
        total_ok += n
        logger.info("[batch %d-%d] upsert=%d，累计 %d", i, i + len(batch_files) - 1, n, total_ok)

    dt = time.perf_counter() - t0
    print(f"[done] 累计灌入 {total_ok} 个商品，耗时 {dt:.1f}s（{total_ok / dt:.1f} 商品/秒）")


if __name__ == "__main__":
    main()
