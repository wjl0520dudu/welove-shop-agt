"""sync_products_pg_to_milvus 的单测：diff 判断 + 删除同步 + watermark 逻辑。

不打真 PG / 真 Milvus，用 mock 验证核心决策逻辑。真实端到端 sync 靠脚本手跑
（scripts/sync_products_pg_to_milvus.py --mode full --dry-run）验证。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# 直接 import 脚本模块（scripts 已加入 sys.path）
import sync_products_pg_to_milvus as sync   # noqa: E402


class TestDiffSets:
    """核心 diff 判断：确定谁该新增、谁该删除。"""

    def test_new_products_only_in_pg_are_to_add(self):
        diff = sync._diff_sets(pg_ids={1, 2, 3}, milvus_ids={1, 2})
        assert diff["to_add"] == {3}
        assert diff["to_delete"] == set()
        assert diff["common"] == {1, 2}

    def test_orphans_only_in_milvus_are_to_delete(self):
        """Milvus 有但 PG 没有的（下架/被删的）→ to_delete。"""
        diff = sync._diff_sets(pg_ids={1, 2}, milvus_ids={1, 2, 999})
        assert diff["to_delete"] == {999}
        assert diff["to_add"] == set()

    def test_empty_pg_deletes_everything(self):
        diff = sync._diff_sets(pg_ids=set(), milvus_ids={1, 2, 3})
        assert diff["to_delete"] == {1, 2, 3}
        assert diff["to_add"] == set()

    def test_empty_milvus_adds_everything(self):
        diff = sync._diff_sets(pg_ids={1, 2, 3}, milvus_ids=set())
        assert diff["to_add"] == {1, 2, 3}
        assert diff["to_delete"] == set()

    def test_id_alignment_scenario(self):
        """真实场景：Phase 1b 遗留合成 id（100001+）→ Sync 后对齐 PG.id（1-100）。

        old_milvus_ids: 100001~100100（老合成 id）
        new_pg_ids:     1~100（新 PG.id）
        期望：全部替换 → to_delete=100 老 id, to_add=100 新 id, common=空
        """
        old_milvus_ids = {100001 + i for i in range(100)}
        new_pg_ids = {1 + i for i in range(100)}
        diff = sync._diff_sets(pg_ids=new_pg_ids, milvus_ids=old_milvus_ids)
        assert len(diff["to_add"]) == 100
        assert len(diff["to_delete"]) == 100
        assert diff["common"] == set()


class TestParseSince:
    def test_iso_format_space_separator(self):
        dt = sync._parse_since("2026-07-08 12:30:00")
        assert dt.year == 2026
        assert dt.month == 7
        assert dt.day == 8

    def test_iso_format_t_separator(self):
        dt = sync._parse_since("2026-07-08T12:30:00")
        assert dt.hour == 12
        assert dt.minute == 30

    def test_naive_datetime_gets_tz(self):
        dt = sync._parse_since("2026-07-08T00:00:00")
        assert dt.tzinfo is not None


class TestRunOne:
    """单商品同步：upsert / 下架删除 / PG 不存在删除。"""

    def _mock_store(self):
        store = MagicMock()
        store.upsert_products = MagicMock(return_value=1)
        store.delete_by_product_id = MagicMock(return_value=1)
        return store

    def test_upsert_active_product(self):
        store = self._mock_store()
        product = {"product_id": 42, "title": "A", "status": 1}

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=[product])), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_one(product_id=42, dry_run=False)

        stats = asyncio.run(run())
        assert stats == {"upserted": 1, "deleted": 0, "skipped": 0}
        store.upsert_products.assert_called_once_with([product])
        store.delete_by_product_id.assert_not_called()

    def test_inactive_product_gets_deleted(self):
        """商品在 PG 但 status != 1（下架）→ 从 Milvus 删除。"""
        store = self._mock_store()
        inactive_product = {"product_id": 42, "title": "A", "status": 0}

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=[inactive_product])), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_one(product_id=42, dry_run=False)

        stats = asyncio.run(run())
        assert stats == {"upserted": 0, "deleted": 1, "skipped": 0}
        store.upsert_products.assert_not_called()
        store.delete_by_product_id.assert_called_once_with(42)

    def test_pg_missing_product_gets_deleted_from_milvus(self):
        """PG 里根本没有该 id（真被删了）→ Milvus 同步删除。"""
        store = self._mock_store()

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=[])), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_one(product_id=999, dry_run=False)

        stats = asyncio.run(run())
        assert stats["deleted"] == 1
        store.delete_by_product_id.assert_called_once_with(999)

    def test_dry_run_skips_writes(self):
        store = self._mock_store()

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=[{"product_id": 42, "title": "A", "status": 1}])), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_one(product_id=42, dry_run=True)

        stats = asyncio.run(run())
        assert stats["skipped"] == 1
        assert stats["upserted"] == 0
        store.upsert_products.assert_not_called()
        store.delete_by_product_id.assert_not_called()


class TestRunFull:
    """全量同步：diff 出 add/delete 再执行。"""

    def test_dry_run_no_writes(self):
        store = MagicMock()
        store.upsert_products = MagicMock(return_value=0)
        store.delete_by_product_id = MagicMock(return_value=0)

        pg_products = [{"product_id": i, "title": f"P{i}", "status": 1} for i in range(1, 4)]

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=pg_products)), \
                 patch.object(sync, "_fetch_milvus_product_ids", return_value={2, 3, 999}), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_full(dry_run=True)

        stats = asyncio.run(run())
        assert stats["skipped"] == 3   # PG 里的 3 条被记为 skipped
        store.upsert_products.assert_not_called()
        store.delete_by_product_id.assert_not_called()

    def test_orphans_get_deleted(self):
        """Milvus 有但 PG 没的（如老合成 id 数据）→ 全部删除。"""
        store = MagicMock()
        store.upsert_products = MagicMock(return_value=2)
        store.delete_by_product_id = MagicMock(return_value=1)

        pg_products = [{"product_id": 1, "title": "P1", "status": 1},
                       {"product_id": 2, "title": "P2", "status": 1}]

        async def run():
            with patch.object(sync, "_fetch_products_from_pg",
                              new=AsyncMock(return_value=pg_products)), \
                 patch.object(sync, "_fetch_milvus_product_ids", return_value={100001, 100002}), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_full(dry_run=False)

        stats = asyncio.run(run())
        # 应该 upsert 2 条新 id
        assert stats["upserted"] == 2
        # 应该删掉 2 条老合成 id 孤儿
        assert stats["deleted"] == 2
        # 删除应该调 delete_by_product_id 2 次
        assert store.delete_by_product_id.call_count == 2
        deleted_ids = {call.args[0] for call in store.delete_by_product_id.call_args_list}
        assert deleted_ids == {100001, 100002}


class TestRunIncremental:
    def test_no_watermark_falls_back_to_full(self):
        """没 watermark 又没传 --since → 退回 full 模式（首次跑友好）。"""
        async def run():
            with patch.object(sync, "_get_last_synced_at", new=AsyncMock(return_value=None)), \
                 patch.object(sync, "_run_full", new=AsyncMock(return_value={
                     "upserted": 5, "deleted": 0, "skipped": 0,
                 })):
                return await sync._run_incremental(since=None, dry_run=False)

        stats = asyncio.run(run())
        assert stats["upserted"] == 5

    def test_incremental_upserts_and_deletes_downgraded(self):
        """update_time > since 且 status=1 的 upsert；status!=1 的删除。"""
        store = MagicMock()
        store.upsert_products = MagicMock(return_value=2)
        store.delete_by_product_id = MagicMock(return_value=1)

        active = [
            {"product_id": 1, "title": "改过标题的 P1", "status": 1},
            {"product_id": 3, "title": "P3", "status": 1},
        ]
        # 所有 update_time>since 的（含下架的）
        all_changed = active + [{"product_id": 7, "title": "下架的 P7", "status": 0}]

        # since 传固定值绕过 watermark 读取
        since = datetime(2026, 7, 8, tzinfo=timezone.utc)

        async def _fake_fetch(*, since=None, product_id=None, only_active=True):  # noqa: ARG001
            return active if only_active else all_changed

        async def run():
            with patch.object(sync, "_fetch_products_from_pg", new=_fake_fetch), \
                 patch.object(sync, "get_product_milvus_store", return_value=store):
                return await sync._run_incremental(since=since, dry_run=False)

        stats = asyncio.run(run())
        assert stats["upserted"] == 2
        assert stats["deleted"] == 1
        store.delete_by_product_id.assert_called_once_with(7)
