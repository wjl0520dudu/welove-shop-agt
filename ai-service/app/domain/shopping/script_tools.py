"""Narrow LangChain Tool for controlled Shopping Skill scripts."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.tools import tool

from app.domain.shopping.script_runner import (
    SHOPPING_SCRIPT_TOOL_NAME,
    ShoppingSkillScriptError,
    ShoppingSkillScriptRunner,
)
from app.infrastructure.config import config


@tool(SHOPPING_SCRIPT_TOOL_NAME, parse_docstring=True)
async def run_shopping_skill_script(
    skill_name: str,
    script_name: str,
    payload: Dict[str, Any],
) -> dict:
    """运行已发布 Shopping Skill 中的白名单确定性 JSON 脚本。

    仅在已读取 Skill 明确要求时使用。该工具不能访问商品数据库、网络、会话历史或任意文件，
    也不负责理解用户语义。商品事实必须先由商品业务工具提供。

    Args:
        skill_name: 已读取的 Shopping Skill 名称。
        script_name: Skill 中声明的白名单脚本名，不含路径。
        payload: 来自可信 ToolResult 的有限 JSON 对象。

    Returns:
        包含 action、skill_name、script_name、result、duration_ms 和错误状态的结构化结果。
    """
    if str(config.SHOPPING_SKILL_SCRIPT_MODE).lower() != "controlled":
        return {
            "action": "script_error",
            "error": True,
            "error_code": "SHOPPING_SCRIPT_MODE_DISABLED",
            "message": "Shopping Skill scripts 当前未启用。",
        }
    runner = ShoppingSkillScriptRunner(
        timeout_seconds=config.SHOPPING_SKILL_SCRIPT_TIMEOUT_SECONDS,
    )
    try:
        execution = await runner.run(
            skill_name=skill_name,
            script_name=script_name,
            payload=payload,
        )
    except ShoppingSkillScriptError as exc:
        return {
            "action": "script_error",
            "error": True,
            "error_code": exc.code,
            "message": str(exc),
            "skill_name": str(skill_name or ""),
            "script_name": str(script_name or ""),
        }
    return {
        "action": "script_result",
        "error": False,
        **execution,
    }


SHOPPING_SCRIPT_TOOLS = [run_shopping_skill_script]


__all__ = ["SHOPPING_SCRIPT_TOOLS", "run_shopping_skill_script"]
