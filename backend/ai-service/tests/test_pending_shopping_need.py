"""pending_shopping_need memory API 的行为测试。

只测公开的 get / remember / clear 三个函数，不依赖 Store 后端实现。
风格对齐 tests/test_reference_tools.py：sync 测试内部 asyncio.run(run())。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


class TestGetPendingShoppingNeed:
    def test_returns_none_when_absent(self):
        from agents.memory import get_pending_shopping_need

        async def run():
            with patch("agents.memory._get_conversation", new=AsyncMock(return_value={})):
                return await get_pending_shopping_need("c1", "u1")

        assert asyncio.run(run()) is None

    def test_returns_dict_when_present(self):
        from agents.memory import get_pending_shopping_need

        pending = {"status": "clarifying", "need": {}, "turn_count": 1}

        async def run():
            with patch(
                "agents.memory._get_conversation",
                new=AsyncMock(return_value={"pending_shopping_need": pending}),
            ):
                return await get_pending_shopping_need("c1", "u1")

        assert asyncio.run(run()) == pending

    def test_drops_when_turn_count_exceeds_max(self):
        """turn_count 达到 _MAX_PENDING_TURNS(=3) 时应清除并返回 None。"""
        from agents.memory import get_pending_shopping_need

        pending = {"status": "clarifying", "need": {}, "turn_count": 3}

        async def run():
            mock_get = AsyncMock(return_value={"pending_shopping_need": pending})
            mock_set = AsyncMock()
            with patch("agents.memory._get_conversation", new=mock_get), \
                 patch("agents.memory._set_conversation", new=mock_set):
                result = await get_pending_shopping_need("c1", "u1")
                # 应该触发一次清除写入
                assert mock_set.await_count == 1
                saved_memory = mock_set.await_args.args[1]
                assert "pending_shopping_need" not in saved_memory
                return result

        assert asyncio.run(run()) is None


class TestRememberPendingShoppingNeed:
    def test_writes_snapshot(self):
        from agents.memory import remember_pending_shopping_need

        async def run():
            mock_get = AsyncMock(return_value={})
            mock_set = AsyncMock()
            with patch("agents.memory._get_conversation", new=mock_get), \
                 patch("agents.memory._set_conversation", new=mock_set):
                await remember_pending_shopping_need(
                    "c1", "u1",
                    {"status": "clarifying", "need": {"category": None}, "turn_count": 1},
                )
                assert mock_set.await_count == 1
                saved = mock_set.await_args.args[1]
                assert saved["pending_shopping_need"]["turn_count"] == 1

        asyncio.run(run())

    def test_noop_on_empty(self):
        from agents.memory import remember_pending_shopping_need

        async def run():
            mock_get = AsyncMock(return_value={})
            mock_set = AsyncMock()
            with patch("agents.memory._get_conversation", new=mock_get), \
                 patch("agents.memory._set_conversation", new=mock_set):
                await remember_pending_shopping_need("c1", "u1", {})
                assert mock_set.await_count == 0

        asyncio.run(run())


class TestClearPendingShoppingNeed:
    def test_removes_key(self):
        from agents.memory import clear_pending_shopping_need

        async def run():
            mock_get = AsyncMock(return_value={
                "pending_shopping_need": {"turn_count": 1},
                "last_product_cards": [{"id": 1}],
            })
            mock_set = AsyncMock()
            with patch("agents.memory._get_conversation", new=mock_get), \
                 patch("agents.memory._set_conversation", new=mock_set):
                await clear_pending_shopping_need("c1", "u1")
                assert mock_set.await_count == 1
                saved = mock_set.await_args.args[1]
                assert "pending_shopping_need" not in saved
                # 不能误伤其他字段
                assert "last_product_cards" in saved

        asyncio.run(run())

    def test_noop_when_absent(self):
        from agents.memory import clear_pending_shopping_need

        async def run():
            mock_get = AsyncMock(return_value={"last_product_cards": []})
            mock_set = AsyncMock()
            with patch("agents.memory._get_conversation", new=mock_get), \
                 patch("agents.memory._set_conversation", new=mock_set):
                await clear_pending_shopping_need("c1", "u1")
                # 没有 pending 就不写
                assert mock_set.await_count == 0

        asyncio.run(run())
