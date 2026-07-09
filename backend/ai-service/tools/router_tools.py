"""Router 辅助工具集。

**当前 Router 用纯 LLM 分类 + business_memory 注入 prompt 的方案（方案 B）**，
所以 Router agent 本身不挂工具。这个模块里的函数留作 helper 用：

- `detect_compound_intent`：文本层面的复合意图检测（纯规则，不调 LLM）。
  Router 可以用它做兜底判断，未来切 Supervisor 模式时可以直接复用。

- `format_business_memory_for_router`：把 Store 里的 business_memory 格式化成
  Router 可读的 context 文本，塞进 messages 前面。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai-service.router_tools")


# ---- 复合意图检测（helper，不是 tool）--------------------------------------

# 复合意图标志词：用户在一个句子里切换话题
_COMPOUND_MARKERS = [
    "对了", "顺便", "还有", "另外", "以及", "再加上",
    "同时也想问", "另外问一下", "再问", "顺带问",
    "然后", "再帮我", "另外帮我",
]


def detect_compound_intent(query: str) -> Dict[str, Any]:
    """检测用户问题是否包含多个意图。

    纯规则实现，不调 LLM。Router 分类时可以用它做兜底：
    - 检测到复合意图 → 按主意图（第一段）分类
    - 未检测到 → 按整个 query 分类

    Args:
        query: 用户问题文本。

    Returns:
        dict: {
            "is_compound": bool,
            "primary_part": str,               # 主意图对应的文本片段
            "primary_intent": str,             # 主意图分类（shopping/knowledge/chitchat/unknown）
            "secondary_intents": List[dict],   # 次要意图列表
            "analysis": str,                   # 分析说明
        }
    """
    if not query or not query.strip():
        return {
            "is_compound": False,
            "primary_part": query,
            "primary_intent": "unknown",
            "secondary_intents": [],
            "analysis": "空 query",
        }

    parts: list[tuple[str, str]] = []
    remaining = query

    # 按标志词切分
    for marker in _COMPOUND_MARKERS:
        if marker in remaining:
            idx = remaining.index(marker)
            before = remaining[:idx].strip()
            after = remaining[idx + len(marker):].strip()
            if before:
                parts.append((before, _classify_segment(before)))
            remaining = after

    if remaining.strip():
        parts.append((remaining.strip(), _classify_segment(remaining.strip())))

    if len(parts) <= 1:
        return {
            "is_compound": False,
            "primary_part": query,
            "primary_intent": _classify_segment(query),
            "secondary_intents": [],
            "analysis": "单一意图，无需拆分",
        }

    primary_part, primary_intent = parts[0]
    secondary = [{"intent": intent, "part": part} for part, intent in parts[1:]]

    return {
        "is_compound": True,
        "primary_part": primary_part,
        "primary_intent": primary_intent,
        "secondary_intents": secondary,
        "analysis": f"检测到 {len(parts)} 个意图片段，主意图为 {primary_intent}",
    }


def _classify_segment(text: str) -> str:
    """对单个文本片段做快速意图分类（纯规则，不调 LLM）。"""
    if not text:
        return "unknown"

    # 元问题（关于对话本身）优先归 chitchat
    meta_patterns = ["刚才问", "刚才说", "刚才聊", "还记得", "回顾", "总结一下", "我叫什么"]
    if any(p in text for p in meta_patterns):
        return "chitchat"

    # chitchat 标志
    chitchat_patterns = ["你好", "在吗", "谢谢", "再见", "拜拜", "辛苦"]
    if any(p in text for p in chitchat_patterns):
        return "chitchat"

    # knowledge 标志（了解、理解类）
    knowledge_patterns = [
        "是什么", "什么意思", "功效", "原理", "成分",
        "能不能", "可以吗", "区别", "为什么", "怎么用",
        "适合什么", "适合哪种", "怎么选", "副作用",
        "禁忌", "搭配", "有用吗", "有效吗",
    ]
    if any(p in text for p in knowledge_patterns):
        return "knowledge"

    # shopping 标志（寻找、比较类）
    shopping_patterns = [
        "推荐", "帮我找", "搜一下", "有哪些", "看看",
        "对比", "比较", "性价比", "排行榜", "买",
        "多少钱", "价格", "哪个好", "哪款好",
    ]
    if any(p in text for p in shopping_patterns):
        return "shopping"

    return "unknown"


# ---- business_memory → prompt context ---------------------------------------

def format_business_memory_for_router(memory: Optional[Dict[str, Any]]) -> str:
    """把 Store 里的 business_memory 格式化成 Router 可读的 context 文本。

    Router 分类时把这段文本塞进 messages 前面（作为 SystemMessage 或注释），
    让 Router 能看到"上轮推荐了什么"，正确处理"第二个""刚才那个"类问题。

    只保留 Router 需要的关键字段，避免 prompt 过长：
    - 最多 5 个 last_product_cards（超过截断，仅保留 title + price）
    - last_focused_product 完整字段
    - user_preferences 精简字段

    Args:
        memory: get_business_memory() 返回的合并视图，可能为 None/{}。

    Returns:
        str: 格式化文本；无上下文时返回空串。
    """
    if not memory:
        return ""

    parts: list[str] = []

    last_cards = memory.get("last_product_cards") or []
    if last_cards:
        # 只保留前 5 个，且只留必要字段，避免 token 爆炸
        card_lines: list[str] = []
        for i, card in enumerate(last_cards[:5], 1):
            title = card.get("title") or f"商品{card.get('product_id', 'N/A')}"
            price = card.get("price")
            price_str = f"¥{price}" if price is not None else "价格未知"
            card_lines.append(f"  {i}. {title}（{price_str}）")
        if len(last_cards) > 5:
            card_lines.append(f"  … 另有 {len(last_cards) - 5} 个未列出")
        parts.append("[上轮推荐商品]\n" + "\n".join(card_lines))

    focused = memory.get("last_focused_product")
    if focused:
        title = focused.get("title") or f"商品{focused.get('product_id', 'N/A')}"
        parts.append(f"[当前关注商品] {title}")

    # 知识实体：Router 靠这个判断"第二个的成分"该走 knowledge 还是 shopping。
    # 有商品且无实体 → 商品指代；有实体且无商品 → 知识实体指代；两者都有由 prompt 里的
    # "指代词性质"规则区分（商品维度词 vs 知识维度词）。
    entities = memory.get("last_knowledge_entities") or []
    if entities:
        entity_lines = [f"  {i}. {e}" for i, e in enumerate(entities, 1)]
        parts.append("[上轮谈到的知识实体]\n" + "\n".join(entity_lines))

    prefs = memory.get("user_preferences") or {}
    if prefs:
        # 精简：只保留 skin_type / gender / preference_tags
        keep_keys = ("skin_type", "gender", "preference_tags", "budget_max", "budget_min")
        simplified = {k: v for k, v in prefs.items() if k in keep_keys and v}
        if simplified:
            parts.append("[用户偏好] " + json.dumps(simplified, ensure_ascii=False))

    if not parts:
        return ""

    return "## 会话上下文\n\n" + "\n\n".join(parts)
