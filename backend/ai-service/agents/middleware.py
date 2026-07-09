"""Agent Middleware 集合。

## SummarizationMiddleware（教程 08-01）
长对话压缩：当消息数或 token 数超过阈值时，用小模型把历史压缩为摘要，
保留最近 N 条原始消息。防止 token 越积越多导致 LLM 上下文溢出。

## PreferenceLearningMiddleware（自定义，教程 08-06）
after_model 钩子：每次 LLM 回复后，用小模型分析对话中用户是否透露了新偏好
（肤质、预算、品牌偏好等），发现就 fire-and-forget 写入 Store 用户级 namespace。

注意：after_model 是同步钩子（LangChain 不支持 async），偏好抽取的异步
LLM 调用 + Store 写入通过 asyncio.create_task 投递到 event loop 后台执行。
不阻塞主回复路径。

## 使用
在 create_agent(middleware=[...]) 里传入。3 个子 agent（Shopping/Knowledge/Chitchat）
各自独立挂载，middleware 实例可共享。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    SummarizationMiddleware,
)
from langgraph.runtime import Runtime

from agents.memory import remember_user_preferences

logger = logging.getLogger("ai-service.middleware")


# ---- 摘要模型（懒加载单例）-----------------------------------------------

_summarization_model = None


def _get_summarization_model():
    """懒加载摘要模型。与主 LLM 同一配置，但 temperature=0（摘要要稳定）。"""
    global _summarization_model
    if _summarization_model is not None:
        return _summarization_model
    from core.llm import get_llm
    _summarization_model = get_llm()
    return _summarization_model


# ---- SummarizationMiddleware --------------------------------------------

def build_summarization_middleware() -> SummarizationMiddleware:
    """构建对话摘要中间件。

    trigger: tokens > 4000 或 messages > 20 → 触发摘要
    keep: 保留最近 6 条原始消息，更早的压缩为 SystemMessage 摘要
    """
    return SummarizationMiddleware(
        model=_get_summarization_model(),
        trigger=[
            ("tokens", 4000),
            ("messages", 20),
        ],
        keep=("messages", 6),
    )


# ---- PreferenceLearningMiddleware ---------------------------------------

_PREFERENCE_EXTRACT_PROMPT = """分析以下对话，判断用户是否透露了新的购物偏好。

对话：
{messages}

请提取用户偏好（只返回 JSON，找不到就返回空对象）：
{{
    "skin_type": "干皮/油皮/混合/敏感/中性 或空字符串",
    "gender": "男/女 或空字符串",
    "budget_preference": "平价/中端/高端 或空字符串",
    "brand_preference": "偏好品牌 或空字符串",
    "category_interest": "感兴趣的品类 或空字符串",
    "other_notes": "其他值得记录的偏好 或空字符串"
}}"""


def _extract_and_store_preferences(
    state: AgentState,
    runtime: Runtime,
) -> None:
    """同步入口：投递偏好抽取到 event loop 后台执行。

    after_model 是同步钩子（LangChain 不支持 async 返回），
    真正的 LLM 调用 + Store 写入通过 create_task 异步执行，
    不阻塞主回复路径。
    """
    try:
        messages = state.get("messages", [])
        if len(messages) < 3:
            return

        user_id = state.get("user_id")
        conversation_id = state.get("conversation_id")
        if not user_id:
            return

        # 取最近 4 轮（8 条）消息
        recent = messages[-8:]
        dialog_lines: List[str] = []
        for m in recent:
            role = getattr(m, "type", "") if hasattr(m, "type") else ""
            content = getattr(m, "content", "") if hasattr(m, "content") else ""
            if role == "human":
                dialog_lines.append(f"用户：{content}")
            elif role == "ai":
                dialog_lines.append(f"助手：{content}")

        if not dialog_lines:
            return

        dialog_text = "\n".join(dialog_lines)
        cid = str(conversation_id) if conversation_id else None
        uid = user_id

        async def _do_extract() -> None:
            try:
                model = _get_summarization_model()
                prompt = _PREFERENCE_EXTRACT_PROMPT.format(messages=dialog_text)
                response = await model.ainvoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1]
                    content = content.rsplit("```", 1)[0]
                prefs = json.loads(content)
                prefs = {k: v for k, v in prefs.items() if v and v != ""}
                if prefs:
                    await remember_user_preferences(cid, uid, prefs)
                    logger.info("PreferenceLearning: extracted %s for user=%s", list(prefs.keys()), uid)
            except Exception:
                logger.debug("PreferenceLearning background task failed", exc_info=True)

        loop = asyncio.get_event_loop()
        loop.create_task(_do_extract())
    except Exception:
        logger.debug("PreferenceLearning hook skipped", exc_info=True)


class PreferenceLearningMiddleware(AgentMiddleware):
    """偏好学习中间件：after_model 投递后台任务抽取偏好写 Store。

    用法：create_agent(middleware=[PreferenceLearningMiddleware()])
    """

    def after_model(
        self, state: AgentState, runtime: Runtime
    ) -> Optional[Dict[str, Any]]:
        _extract_and_store_preferences(state, runtime)
        return None
