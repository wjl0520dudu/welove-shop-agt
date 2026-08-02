"""Phase S3 tests for reviewed Shopping Skill scripts and runner limits."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.domain.shopping.script_runner import (
    SHOPPING_SKILL_SCRIPT_REGISTRY,
    ShoppingSkillScriptError,
    ShoppingSkillScriptRunner,
)
from app.domain.shopping.script_tools import run_shopping_skill_script
from app.infrastructure.config import config


def test_phase_s3_registry_contains_only_the_six_published_scripts():
    assert set(SHOPPING_SKILL_SCRIPT_REGISTRY) == {
        ("discover-products", "normalize-candidates"),
        ("discover-products", "validate-selection"),
        ("discover-products", "sort-by-preference"),
        ("compare-products", "normalize-units"),
        ("compare-products", "build-comparison-matrix"),
        ("inspect-product", "summarize-sku-facts"),
    }
    assert all(path.is_file() for path in SHOPPING_SKILL_SCRIPT_REGISTRY.values())


def test_discovery_scripts_normalize_validate_and_stably_sort():
    async def run():
        runner = ShoppingSkillScriptRunner()
        normalized = await runner.run(
            skill_name="discover-products",
            script_name="normalize-candidates",
            payload={"candidates": [{
                "id": "7", "name": "测试耳机", "base_price": "499", "tags": "通勤,降噪",
            }]},
        )
        validated = await runner.run(
            skill_name="discover-products",
            script_name="validate-selection.py",
            payload={
                "candidates": [{"product_id": 7, "match_status": "exact"}],
                "selected_indices": [1],
            },
        )
        sorted_result = await runner.run(
            skill_name="discover-products",
            script_name="sort-by-preference",
            payload={
                "items": [
                    {"product_id": 1, "personalization_score": 0.2},
                    {"product_id": 2, "personalization_score": 0.9},
                ],
                "preference_applicability_score": 0.9,
            },
        )
        return normalized, validated, sorted_result

    normalized, validated, sorted_result = asyncio.run(run())
    item = normalized["result"]["candidates"][0]
    assert item["product_id"] == 7
    assert item["price"] == 499.0
    assert item["tags"] == ["通勤", "降噪"]
    assert validated["result"]["valid"] is True
    assert validated["result"]["selected_candidates"][0]["product_id"] == 7
    assert [item["product_id"] for item in sorted_result["result"]["items"]] == [2, 1]
    assert sorted_result["result"]["applied"] is True


def test_selection_validation_is_atomic_on_any_invalid_index():
    async def run():
        return await ShoppingSkillScriptRunner().run(
            skill_name="discover-products",
            script_name="validate-selection",
            payload={
                "candidates": [
                    {"product_id": 7, "match_status": "exact"},
                    {"product_id": 8, "match_status": "alternative"},
                ],
                "selected_indices": [1, 3],
            },
        )

    result = asyncio.run(run())["result"]
    assert result["valid"] is False
    assert result["selected_candidates"] == []
    assert result["invalid_indices"] == [3]


def test_comparison_and_sku_scripts_only_transform_provided_facts():
    async def run():
        runner = ShoppingSkillScriptRunner()
        units = await runner.run(
            skill_name="compare-products",
            script_name="normalize-units",
            payload={"rows": [{"weight": "1.2kg", "storage": "1TB", "color": "black"}]},
        )
        matrix = await runner.run(
            skill_name="compare-products",
            script_name="build-comparison-matrix",
            payload={
                "products": [{"product_id": 1, "title": "A", "facts": {"price": 99}}],
                "dimensions": [{"key": "facts.price", "label": "价格"}],
            },
        )
        aggregate_matrix = await runner.run(
            skill_name="compare-products",
            script_name="build-comparison-matrix",
            payload={
                "products": [{
                    "product_id": 1,
                    "title": "A",
                    "skus": [
                        {"price": 99, "stock": 3},
                        {"price": 109, "stock": 0},
                    ],
                }],
                "dimensions": [
                    {"key": "skus.price", "label": "SKU 价格区间", "aggregate": "range"},
                    {"key": "skus.stock", "label": "总库存", "aggregate": "sum"},
                ],
            },
        )
        sku = await runner.run(
            skill_name="inspect-product",
            script_name="summarize-sku-facts",
            payload={"product": {
                "product_id": 1,
                "skus": [
                    {"id": 11, "price": 99, "stock": 3},
                    {"id": 12, "price": 109, "stock": 0},
                ],
            }},
        )
        return units, matrix, aggregate_matrix, sku

    units, matrix, aggregate_matrix, sku = asyncio.run(run())
    assert units["result"]["rows"][0]["weight"]["value"] == 1200.0
    assert units["result"]["rows"][0]["storage"]["value"] == 1024.0
    assert units["result"]["rows"][0]["color"] == "black"
    assert matrix["result"]["matrix"][0]["values"] == {"价格": 99}
    aggregate_values = aggregate_matrix["result"]["matrix"][0]["values"]
    assert aggregate_values["SKU 价格区间"] == {"min": 99.0, "max": 109.0}
    assert aggregate_values["总库存"] == 3.0
    assert sku["result"]["sku_count"] == 2
    assert sku["result"]["available_sku_count"] == 1
    assert sku["result"]["total_stock"] == 3


def test_runner_rejects_unknown_script_and_large_input():
    async def run_unknown():
        await ShoppingSkillScriptRunner().run(
            skill_name="discover-products",
            script_name="../../secrets",
            payload={},
        )

    with pytest.raises(ShoppingSkillScriptError) as unknown:
        asyncio.run(run_unknown())
    assert unknown.value.code == "SHOPPING_SCRIPT_NOT_ALLOWED"

    async def run_large():
        await ShoppingSkillScriptRunner(max_input_bytes=1024).run(
            skill_name="discover-products",
            script_name="normalize-candidates",
            payload={"value": "x" * 2000},
        )

    with pytest.raises(ShoppingSkillScriptError) as large:
        asyncio.run(run_large())
    assert large.value.code == "SHOPPING_SCRIPT_INPUT_TOO_LARGE"


def test_runner_blocks_unreviewed_imports_and_times_out():
    with TemporaryDirectory(prefix=".phase-s3-", dir=Path.cwd()) as temp_dir:
        test_root = Path(temp_dir)
        blocked = test_root / "blocked.py"
        blocked.write_text("import os\n", encoding="utf-8")
        looping = test_root / "looping.py"
        looping.write_text("while True:\n    pass\n", encoding="utf-8")

        async def run_blocked():
            await ShoppingSkillScriptRunner(
                registry={("test-skill", "blocked"): blocked},
            ).run(skill_name="test-skill", script_name="blocked", payload={})

        with pytest.raises(ShoppingSkillScriptError) as import_error:
            asyncio.run(run_blocked())
        assert import_error.value.code == "SHOPPING_SCRIPT_IMPORT_BLOCKED"

        async def run_timeout():
            await ShoppingSkillScriptRunner(
                timeout_seconds=0.1,
                registry={("test-skill", "looping"): looping},
            ).run(skill_name="test-skill", script_name="looping", payload={})

        with pytest.raises(ShoppingSkillScriptError) as timeout:
            asyncio.run(run_timeout())
        assert timeout.value.code == "SHOPPING_SCRIPT_TIMEOUT"


def test_script_tool_honors_the_runtime_mode(monkeypatch):
    monkeypatch.setattr(config, "SHOPPING_SKILL_SCRIPT_MODE", "disabled")
    result = asyncio.run(run_shopping_skill_script.ainvoke({
        "skill_name": "discover-products",
        "script_name": "normalize-candidates",
        "payload": {"candidates": []},
    }))
    assert result["error"] is True
    assert result["error_code"] == "SHOPPING_SCRIPT_MODE_DISABLED"
