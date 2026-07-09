"""ShoppingAgent 端到端真 LLM 验证脚本（Phase 1a + 1b 集成）。

## 目标
- 验证新 SHOPPING_AGENT_PROMPT + 4 个高层 Tool 后，LLM 能不能：
  1. 从 4 个 Tool 里选对（不出现"12 工具时代"的乱选）
  2. 拿到 Tool 返回的 action=recommend/clarify/detail/compare 后组织出正常话术
  3. 多轮 pending_shopping_need 能合并
  4. 复杂对比/详情能命中正确的 Capability

## 打真 LLM + 真 Milvus
- LLM: ark-code-latest（或 .env 里 LLM_MODEL 配的）
- 商品库: product_mm_collection（100 商品）
- 每条 query 打印：LLM 选的 tool + args + Tool 返回 action + LLM 最终 answer

## 用法
    conda activate D:\\dev\\env\\conda_envs\\wlagt
    python scripts/verify_shopping_e2e.py

## 会话隔离
每条 test case 用独立 conversation_id，防止 pending / last_product_cards 串扰。
多轮 case 里用同一个 conversation_id 表达"上下文延续"。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import get_llm                                # noqa: E402
from shopping.agent import ShoppingAgent                    # noqa: E402
from agents.memory import (                                  # noqa: E402
    clear_pending_shopping_need,
    get_pending_shopping_need,
    get_business_memory,
)

# 静默 pymilvus deprecation warnings（跟 Phase 1b 一致，用的是 ORM API）
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
try:
    from pymilvus.exceptions import PyMilvusDeprecationWarning  # type: ignore
    warnings.filterwarnings("ignore", category=PyMilvusDeprecationWarning)
except Exception:  # noqa: BLE001
    pass

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("verify_shopping_e2e")
logger.setLevel(logging.INFO)


# ---- test case 定义 ------------------------------------------------------

# 每个 case 是一个"会话"，含一到多轮 user 消息。
# expect: 是本轮预期 LLM 选择的 tool（用于断言 + 打印高亮）
CASES: List[Dict[str, Any]] = [
    {
        "name": "单轮·油皮防晒推荐",
        "turns": [
            {"user": "推荐一款适合油皮夏天用的防晒，200 以内不要黏",
             "expect_tool": "recommend_products",
             "expect_action": "recommend"},
        ],
    },
    {
        "name": "模糊需求·应追问",
        "turns": [
            {"user": "推荐一下",
             "expect_tool": "recommend_products",
             "expect_action": "clarify"},
        ],
    },
    {
        "name": "多轮·送妈妈护肤礼盒 → 补品类和预算",
        "turns": [
            {"user": "我想给妈妈送点东西",
             "expect_tool": "recommend_products",
             "expect_action": "clarify"},
            {"user": "护肤品吧，300 以内",
             "expect_tool": "recommend_products",
             "expect_action": "recommend"},
        ],
    },
    {
        "name": "多轮·先推荐再对比",
        "turns": [
            {"user": "推荐几款敏感肌能用的面霜",
             "expect_tool": "recommend_products",
             "expect_action": "recommend"},
            {"user": "这几个哪个更适合我这种敏感肌",
             "expect_tool": "compare_products",
             "expect_action": "compare"},
        ],
    },
    {
        "name": "多轮·先推荐再问详情",
        "turns": [
            {"user": "推荐一款速干 T 恤",
             "expect_tool": "recommend_products",
             "expect_action": "recommend"},
            {"user": "第一个多少钱",
             "expect_tool": "answer_product_detail",
             "expect_action": "detail"},
        ],
    },
]


# ---- helper --------------------------------------------------------------


def _fmt_tool_call(tc: Dict[str, Any]) -> str:
    name = tc.get("name") or "?"
    args = tc.get("args") or {}
    # 只保留 args 的 key + 短 value，避免刷屏
    short_args: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 40:
            v = v[:40] + "…"
        short_args[k] = v
    return f"{name}({json.dumps(short_args, ensure_ascii=False)})"


def _extract_tool_result_action(tool_calls: List[Dict[str, Any]], answer: str, product_cards) -> Optional[str]:
    """从最终结果里推断 Tool 返回的 action。

    ShoppingAgent.run 返回没直接给 action，只能反推：
    - product_cards 有 → recommend 或 compare 或 detail
    - 结合 answer 里的关键词判断
    """
    if product_cards:
        # 简单启发式，实际 action 需要拆开 ToolMessage 抽
        # 这里保守返回 "has_cards"（跟 clarify 区分开就行）
        return "has_cards"
    return None


async def _fresh_conversation_id() -> str:
    """给每个 case 一个独立会话 id，防止 pending / last_product_cards 串扰。"""
    return "e2e-" + uuid.uuid4().hex[:8]


async def _dump_memory_snapshot(conversation_id: str, user_id: Optional[int]) -> Dict[str, Any]:
    """把当前会话的 memory 关键字段打出来，便于诊断。"""
    mem = await get_business_memory(conversation_id, user_id)
    pending = await get_pending_shopping_need(conversation_id, user_id)
    return {
        "last_product_cards_count": len(mem.get("last_product_cards") or []),
        "last_focused_product_title": (mem.get("last_focused_product") or {}).get("title"),
        "pending_shopping_need": pending,
    }


async def run_case(agent: ShoppingAgent, case: Dict[str, Any], case_idx: int) -> Dict[str, Any]:
    conv_id = await _fresh_conversation_id()
    # 先清一次 pending，防止上次会话残留（虽然 conv_id 是新的，Store 里应该也是空的）
    await clear_pending_shopping_need(conv_id, None)

    print("\n" + "=" * 100)
    print(f"[Case #{case_idx}] {case['name']}   conv={conv_id}")
    print("=" * 100)

    messages: List[Dict[str, Any]] = []
    stats = {"turn_count": len(case["turns"]), "correct_tool": 0, "correct_action": 0}

    for turn_idx, turn in enumerate(case["turns"], 1):
        user_msg = turn["user"]
        expect_tool = turn.get("expect_tool")
        expect_action = turn.get("expect_action")

        messages.append({"role": "user", "content": user_msg})

        print(f"\n  ── turn {turn_idx}/{len(case['turns'])} ──")
        print(f"  [USER] {user_msg}")
        print(f"  [EXPECT] tool={expect_tool}  action={expect_action}")

        t0 = time.perf_counter()
        result = await agent.run(
            question=user_msg,
            messages=messages,
            business_memory={},
            conversation_id=conv_id,
            user_id=None,   # 匿名 user；user_context tool 会返回 LOGIN_REQUIRED，不影响主链路
            jwt_token=None,
        )
        dt = (time.perf_counter() - t0) * 1000

        answer = result.get("answer") or ""
        cards = result.get("product_cards") or []
        tool_calls = result.get("tool_calls") or []

        # 断言：LLM 选了预期的 tool
        called_tools = [tc.get("name") for tc in tool_calls if tc.get("name")]
        tool_correct = expect_tool in called_tools if expect_tool else True
        if tool_correct:
            stats["correct_tool"] += 1

        # 推断 action
        inferred_action = _extract_tool_result_action(tool_calls, answer, cards)
        # clarify: 没有 cards + answer 是追问
        looks_like_clarify = (not cards) and any(
            k in answer for k in ("？", "?", "呢", "哪类", "哪个", "预算多少", "什么场景", "什么类型")
        )
        # recommend: 有 cards
        looks_like_recommend_or_detail_or_compare = bool(cards)

        action_correct = True
        if expect_action == "clarify":
            action_correct = looks_like_clarify and not cards
        elif expect_action in ("recommend", "detail", "compare"):
            action_correct = looks_like_recommend_or_detail_or_compare
        if action_correct:
            stats["correct_action"] += 1

        # 打印
        print(f"  [TIME] {dt:.0f}ms")
        print(f"  [TOOLS] {[_fmt_tool_call(tc) for tc in tool_calls] or '(none)'}")
        print(f"  [CARDS] {len(cards)} 张" + (f" → {[c.get('title', '')[:20] for c in cards[:3]]}" if cards else ""))
        print(f"  [ANSWER] {answer[:220]}" + ("…" if len(answer) > 220 else ""))

        # 断言标记
        ok_tool = "✅" if tool_correct else "❌"
        ok_action = "✅" if action_correct else "❌"
        print(f"  [CHECK] tool {ok_tool} | action {ok_action}")

        # 把 AI 回复补进对话历史，供下轮使用
        messages.append({"role": "assistant", "content": answer})

        # 打一份 memory 快照
        snap = await _dump_memory_snapshot(conv_id, None)
        print(f"  [MEMORY] cards={snap['last_product_cards_count']} "
              f"focused={snap['last_focused_product_title'] or '-'} "
              f"pending={'yes' if snap['pending_shopping_need'] else 'no'}")

    print(f"\n  [SUMMARY] tool {stats['correct_tool']}/{stats['turn_count']} | "
          f"action {stats['correct_action']}/{stats['turn_count']}")
    return stats


async def main():
    llm = get_llm()
    if llm is None:
        print("[fatal] LLM 未配置（LLM_API_KEY 空），无法跑真 LLM E2E。")
        sys.exit(1)

    print(f"[info] LLM ready: model={type(llm).__name__}")
    agent = ShoppingAgent(llm)

    total_stats = {"turn_count": 0, "correct_tool": 0, "correct_action": 0}
    t0 = time.perf_counter()
    for idx, case in enumerate(CASES, 1):
        try:
            stats = await run_case(agent, case, idx)
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception:
            logger.exception("[case #%d] 执行失败", idx)

    dt = time.perf_counter() - t0
    print("\n" + "#" * 100)
    print(f"# TOTAL {len(CASES)} cases, {total_stats['turn_count']} turns, {dt:.1f}s")
    print(f"#   tool 选择正确率:   {total_stats['correct_tool']}/{total_stats['turn_count']}")
    print(f"#   action 匹配正确率: {total_stats['correct_action']}/{total_stats['turn_count']}")
    print("#" * 100)


if __name__ == "__main__":
    asyncio.run(main())
