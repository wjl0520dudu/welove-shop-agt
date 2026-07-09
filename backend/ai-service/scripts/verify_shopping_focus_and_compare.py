"""C+D 补充 E2E：focus=sku / focus=ingredients / Compare 显式 product_ids。

单独跑 verify_shopping_e2e.py 覆盖不到的路径。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import get_llm                                # noqa: E402
from shopping.agent import ShoppingAgent                    # noqa: E402
from agents.memory import clear_pending_shopping_need       # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)


CASES: List[Dict[str, Any]] = [
    {
        "name": "C1 · focus=sku （'有几个规格'）",
        "turns": [
            {"user": "推荐一款敏感肌面霜",
             "expect_tool": "recommend_products"},
            {"user": "第二个有几个规格可选",
             "expect_tool": "answer_product_detail",
             "expect_focus": "sku"},
        ],
    },
    {
        "name": "C2 · focus=ingredients （'含什么成分'）",
        "turns": [
            {"user": "推荐一款抗老精华",
             "expect_tool": "recommend_products"},
            {"user": "第一个含什么成分",
             "expect_tool": "answer_product_detail",
             "expect_focus": "ingredients"},
        ],
    },
    {
        "name": "D · compare 显式传 product_ids",
        "turns": [
            # 直接一轮：LLM 应该推断出 product_ids 传给 compare_products
            {"user": "商品 id=7 和 id=8 对比一下哪个好",
             "expect_tool": "compare_products",
             "expect_product_ids": True},
        ],
    },
]


async def _fresh_conv() -> str:
    return "cd-" + uuid.uuid4().hex[:8]


async def run_case(agent: ShoppingAgent, case: Dict[str, Any], case_idx: int) -> Dict[str, int]:
    conv_id = await _fresh_conv()
    await clear_pending_shopping_need(conv_id, None)

    print("\n" + "=" * 100)
    print(f"[Case #{case_idx}] {case['name']}   conv={conv_id}")
    print("=" * 100)

    messages: List[Dict[str, Any]] = []
    stats = {"turns": len(case["turns"]), "tool_ok": 0, "focus_ok": 0, "extra_ok": 0}

    for turn_idx, turn in enumerate(case["turns"], 1):
        user_msg = turn["user"]
        expect_tool = turn.get("expect_tool")
        expect_focus = turn.get("expect_focus")
        expect_product_ids = turn.get("expect_product_ids", False)

        messages.append({"role": "user", "content": user_msg})

        print(f"\n  ── turn {turn_idx}/{len(case['turns'])} ──")
        print(f"  [USER] {user_msg}")
        print(f"  [EXPECT] tool={expect_tool} focus={expect_focus} ids={expect_product_ids}")

        t0 = time.perf_counter()
        result = await agent.run(
            question=user_msg,
            messages=messages,
            business_memory={},
            conversation_id=conv_id,
            user_id=None,
            jwt_token=None,
        )
        dt = (time.perf_counter() - t0) * 1000

        answer = result.get("answer") or ""
        cards = result.get("product_cards") or []
        tool_calls = result.get("tool_calls") or []

        # Tool 断言
        called_tools = [tc.get("name") for tc in tool_calls if tc.get("name")]
        tool_correct = expect_tool in called_tools if expect_tool else True
        if tool_correct:
            stats["tool_ok"] += 1

        # focus 断言（要从 answer_product_detail tool_call args 里看 —— 但 LLM 通常不显式传 focus，
        # 而是让 DetailCapability 内部从 query 提取。所以这里改成"看 answer 内容命中"）
        focus_ok = True
        if expect_focus == "sku":
            focus_ok = any(k in answer for k in ("规格", "SKU", "尺寸", "毫升", "ml", "40ml", "50ml"))
        elif expect_focus == "ingredients":
            focus_ok = any(k in answer for k in ("成分", "含", "浓度"))
        if focus_ok:
            stats["focus_ok"] += 1

        # product_ids 断言
        extra_ok = True
        if expect_product_ids:
            # 找 compare_products 的 args
            for tc in tool_calls:
                if tc.get("name") == "compare_products":
                    args = tc.get("args") or {}
                    pids = args.get("product_ids") or []
                    extra_ok = bool(pids) and len(pids) >= 2
                    print(f"  [product_ids] {pids}")
                    break
        if extra_ok:
            stats["extra_ok"] += 1

        print(f"  [TIME] {dt:.0f}ms")
        print(f"  [TOOLS] {[tc.get('name') for tc in tool_calls]}")
        for tc in tool_calls:
            args = tc.get("args") or {}
            short = {k: (str(v)[:40] + '…' if isinstance(v, str) and len(v) > 40 else v)
                     for k, v in args.items()}
            print(f"    args: {short}")
        print(f"  [CARDS] {len(cards)}")
        print(f"  [ANSWER] {answer[:280]}" + ("…" if len(answer) > 280 else ""))
        print(f"  [CHECK] tool {'✅' if tool_correct else '❌'} | "
              f"focus {'✅' if focus_ok else '❌'} | extra {'✅' if extra_ok else '❌'}")

        messages.append({"role": "assistant", "content": answer})

    print(f"\n  [SUMMARY] tool {stats['tool_ok']}/{stats['turns']} | "
          f"focus {stats['focus_ok']}/{stats['turns']} | "
          f"extra {stats['extra_ok']}/{stats['turns']}")
    return stats


async def main():
    llm = get_llm()
    if llm is None:
        print("[fatal] LLM 未配置")
        sys.exit(1)

    agent = ShoppingAgent(llm)
    print(f"[info] LLM ready: {type(llm).__name__}")

    total = {"turns": 0, "tool_ok": 0, "focus_ok": 0, "extra_ok": 0}
    t0 = time.perf_counter()
    for idx, case in enumerate(CASES, 1):
        try:
            stats = await run_case(agent, case, idx)
            for k in total:
                total[k] += stats[k]
        except Exception:
            import traceback
            traceback.print_exc()

    dt = time.perf_counter() - t0
    print("\n" + "#" * 100)
    print(f"# TOTAL {len(CASES)} cases, {total['turns']} turns, {dt:.1f}s")
    print(f"#   tool  {total['tool_ok']}/{total['turns']}")
    print(f"#   focus {total['focus_ok']}/{total['turns']}")
    print(f"#   extra {total['extra_ok']}/{total['turns']}")
    print("#" * 100)


if __name__ == "__main__":
    asyncio.run(main())
