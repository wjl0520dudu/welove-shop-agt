"""Controlled executor for reviewed Shopping Skill scripts."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from app.domain.shopping.skill_backend import AI_SERVICE_ROOT


SHOPPING_SCRIPT_TOOL_NAME = "run_shopping_skill_script"
SHOPPING_SCRIPT_MAX_INPUT_BYTES = 64 * 1024
SHOPPING_SCRIPT_MAX_OUTPUT_BYTES = 128 * 1024

_ALLOWED_IMPORT_ROOTS = frozenset({"__future__", "json", "re", "sys", "typing"})
_FORBIDDEN_CALLS = frozenset({"open", "exec", "eval", "compile", "__import__"})


def _default_registry() -> dict[tuple[str, str], Path]:
    root = AI_SERVICE_ROOT / "skills" / "shopping-agent"
    return {
        ("discover-products", "normalize-candidates"): root / "discover-products" / "scripts" / "normalize-candidates.py",
        ("discover-products", "validate-selection"): root / "discover-products" / "scripts" / "validate-selection.py",
        ("discover-products", "sort-by-preference"): root / "discover-products" / "scripts" / "sort-by-preference.py",
        ("compare-products", "normalize-units"): root / "compare-products" / "scripts" / "normalize-units.py",
        ("compare-products", "build-comparison-matrix"): root / "compare-products" / "scripts" / "build-comparison-matrix.py",
        ("inspect-product", "summarize-sku-facts"): root / "inspect-product" / "scripts" / "summarize-sku-facts.py",
    }


SHOPPING_SKILL_SCRIPT_REGISTRY = _default_registry()


class ShoppingSkillScriptError(RuntimeError):
    """Stable controlled-runner failure with a public-safe error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ShoppingSkillScriptRunner:
    """Execute only fixed repository scripts in an isolated Python process."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        registry: Mapping[tuple[str, str], Path] | None = None,
        max_input_bytes: int = SHOPPING_SCRIPT_MAX_INPUT_BYTES,
        max_output_bytes: int = SHOPPING_SCRIPT_MAX_OUTPUT_BYTES,
    ) -> None:
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.registry = dict(registry or SHOPPING_SKILL_SCRIPT_REGISTRY)
        self.max_input_bytes = max(1024, int(max_input_bytes))
        self.max_output_bytes = max(1024, int(max_output_bytes))

    async def run(
        self,
        *,
        skill_name: str,
        script_name: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        skill = str(skill_name or "").strip()
        script = str(script_name or "").strip()
        if script.endswith(".py"):
            script = script[:-3]
        path = self.registry.get((skill, script))
        if path is None:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_NOT_ALLOWED",
                "该 Shopping Skill script 未发布或不在执行白名单中。",
            )
        resolved = path.resolve()
        if not resolved.is_file():
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_NOT_FOUND",
                "Shopping Skill script 文件不存在。",
            )
        self._validate_source(resolved)

        try:
            encoded_input = json.dumps(
                dict(payload or {}),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_INPUT_INVALID",
                "script 输入必须是可序列化的 JSON 对象。",
            ) from exc
        if len(encoded_input) > self.max_input_bytes:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_INPUT_TOO_LARGE",
                "script 输入超过允许大小。",
            )

        started = time.perf_counter()
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-I", "-S", str(resolved)],
                input=encoded_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(resolved.parent),
                env=self._minimal_environment(),
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_TIMEOUT",
                "Shopping Skill script 执行超时。",
            ) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        if len(completed.stdout) > self.max_output_bytes:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_OUTPUT_TOO_LARGE",
                "script 输出超过允许大小。",
            )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()[:300]
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_FAILED",
                detail or "Shopping Skill script 执行失败。",
            )
        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_OUTPUT_INVALID",
                "script 未返回有效 UTF-8 JSON。",
            ) from exc
        if not isinstance(result, dict):
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_OUTPUT_INVALID",
                "script 输出必须是 JSON 对象。",
            )
        return {
            "skill_name": skill,
            "script_name": script,
            "result": result,
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _validate_source(path: Path) -> None:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ShoppingSkillScriptError(
                "SHOPPING_SCRIPT_SOURCE_INVALID",
                "Shopping Skill script 源码无法通过安全检查。",
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
                if not roots <= _ALLOWED_IMPORT_ROOTS:
                    raise ShoppingSkillScriptError(
                        "SHOPPING_SCRIPT_IMPORT_BLOCKED",
                        "Shopping Skill script 引用了未允许的模块。",
                    )
            elif isinstance(node, ast.ImportFrom):
                root = str(node.module or "").split(".", 1)[0]
                if root not in _ALLOWED_IMPORT_ROOTS:
                    raise ShoppingSkillScriptError(
                        "SHOPPING_SCRIPT_IMPORT_BLOCKED",
                        "Shopping Skill script 引用了未允许的模块。",
                    )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_CALLS:
                    raise ShoppingSkillScriptError(
                        "SHOPPING_SCRIPT_CALL_BLOCKED",
                        "Shopping Skill script 使用了未允许的动态执行或文件调用。",
                    )

    @staticmethod
    def _minimal_environment() -> dict[str, str]:
        allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG")
        environment = {
            key: value for key in allowed if (value := os.environ.get(key))
        }
        environment.update({
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        return environment


__all__ = [
    "SHOPPING_SCRIPT_MAX_INPUT_BYTES",
    "SHOPPING_SCRIPT_MAX_OUTPUT_BYTES",
    "SHOPPING_SCRIPT_TOOL_NAME",
    "SHOPPING_SKILL_SCRIPT_REGISTRY",
    "ShoppingSkillScriptError",
    "ShoppingSkillScriptRunner",
]
