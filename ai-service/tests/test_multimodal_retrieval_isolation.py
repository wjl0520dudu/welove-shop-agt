"""Multimodal SDK calls must not block the service event loop."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from app.domain.shopping import multimodal_search


def test_multimodal_retrieval_runs_blocking_work_in_a_worker_thread():
    async def run():
        main_thread_id = __import__("threading").get_ident()

        def sync_search(*_args):
            return [{"thread_id": __import__("threading").get_ident()}]

        with patch.object(
            multimodal_search,
            "_search_multimodal_v1_sync",
            side_effect=sync_search,
        ):
            result = await multimodal_search.search_multimodal_v1(
                "", "https://img.example.test/shoe.jpg", top_k=3,
            )

        assert result[0]["thread_id"] != main_thread_id

    asyncio.run(run())


def test_multimodal_retrieval_timeout_releases_async_request():
    async def run():
        def slow_sync_search(*_args):
            time.sleep(0.15)
            return []

        with patch.object(
            multimodal_search.config,
            "SHOPPING_MULTIMODAL_RETRIEVAL_TIMEOUT_SECONDS",
            0.01,
        ), patch.object(
            multimodal_search,
            "_search_multimodal_v1_sync",
            side_effect=slow_sync_search,
        ):
            with pytest.raises(TimeoutError):
                await multimodal_search.search_multimodal_v1(
                    "", "https://img.example.test/shoe.jpg", top_k=3,
                )

    asyncio.run(run())
