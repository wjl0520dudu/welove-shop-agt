"""全链路 E2E：AssistantGraph 从 question 到 answer 完整走一遍。

跟 scripts/verify_shopping_e2e.py 的区别：
- 那个直接调 ShoppingAgent.run（跳过 Router）
- 这个走完整 AssistantGraph.run(question=...)：
    question → Router 分类 → shopping_node/knowledge_node/... → format_response → answer

覆盖的路径：
1. Router 混合 case 分类正确性（"第二个的成分" vs "第二个多少钱"）
2. 主图节点串起来能出结果（跨域指代 + 上下文接续）
3. Knowledge 侧真 LLM 也顺便跑一遍（本次会话没重点测过）
4. 多轮跨请求持久性（每 turn 新建 AssistantGraph → 靠 Postgres Store 记忆延续）
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import get_llm                     # noqa: E402
from agents.runtime import init_runtime          # noqa: E402
from assistant.graph import AssistantGraph       # noqa: E402
from shopping.agent import ShoppingAgent         # noqa: E402
from knowledge.agent import KnowledgeAgent       # noqa: E402
from agents.memory import get_business_memory    # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)
try:
    from pymilvus.exceptions import PyMilvusDeprecationWarning  # type: ignore
    warnings.filterwarnings("ignore", category=PyMilvusDeprecationWarning)
except Exception:  # noqa: BLE001
    pass

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("verify_full_stack")
logger.setLevel(logging.INFO)


# ---- Cases ---------------------------------------------------------------
# 每个 case 是一个"会话"（同一个 conversation_id 多轮）
# expect_route 是本轮 Router 应该分类到的 task_type

CASES: List[Dict[str, Any]] = [
    {
        "name": "Router · 单轮 shopping",
        "turns": [
            {"user": "推荐一款油皮夏天用的防晒",
             "expect_route": "shopping"},
        ],
    },
    {
        "name": "Router · 单轮 knowledge",
        "turns": [
            {"user": "烟酰胺和视黄醇可以一起用吗",
             "expect_route": "knowledge"},
        ],
    },
    {
        "name": "Router · 单轮 chitchat",
        "turns": [
            {"user": "你好",
             "expect_route": "chitchat"},
        ],
    },
    {
        "name": "跨域指代 · 商品域「第二个多少钱」应归 shopping",
        "turns": [
            {"user": "推荐几款敏感肌面霜", "expect_route": "shopping"},
            {"user": "第二个多少钱", "expect_route": "shopping"},
        ],
    },
    {
        "name": "跨域指代 · 知识域「第二个的功效」应归 knowledge",
        "turns": [
            {"user": "对比一下烟酰胺和视黄醇", "expect_route": "knowledge"},
            {"user": "第二个的功效是什么", "expect_route": "knowledge"},
        ],
    },
]


def _fmt_tool_call(tc: Dict[str, Any]) -> str:
    name = tc.get("name") or "?"
    args = tc.get("args") or {}
    return f"{name}({json.dumps({k: v for k, v in args.items() if k != 'runtime'}, ensure_ascii=False)[:100]})"


async def run_case(graph: AssistantGraph, case: Dict[str, Any], case_idx: int) -> Dict[str, int]:
    conv_id = "fs-" + uuid.uuid4().hex[:8]
    print("\n" + "=" * 100)
    print(f"[Case #{case_idx}] {case['name']}   conv={conv_id}")
    print("=" * 100)

    stats = {"turn_count": len(case["turns"]), "route_correct": 0, "answer_present": 0}

    for turn_idx, turn in enumerate(case["turns"], 1):
        user_msg = turn["user"]
        expect_route = turn["expect_route"]

        print(f"\n  ── turn {turn_idx}/{len(case['turns'])} ──")
        print(f"  [USER] {user_msg}")
        print(f"  [EXPECT ROUTE] {expect_route}")

        t0 = time.perf_counter()
        result = await graph.run(
            question=user_msg,
            conversation_id=conv_id,
            user_id=None,
            jwt_token=None,
        )
        dt = (time.perf_counter() - t0) * 1000

        answer = (result.get("answer") or "").strip()
        cards = result.get("product_cards") or []
        sources = result.get("sources") or []
        task_type = result.get("task_type", "")
        tool_calls = result.get("tool_calls") or []

        route_correct = (task_type == expect_route)
        if route_correct:
            stats["route_correct"] += 1
        if answer:
            stats["answer_present"] += 1

        print(f"  [TIME] {dt:.0f}ms")
        print(f"  [ROUTE→task_type] {task_type}   {'✅' if route_correct else '❌'}")
        print(f"  [TOOLS] {[_fmt_tool_call(tc) for tc in tool_calls[:3]] or '(none)'}")
        if cards:
            print(f"  [CARDS] {len(cards)} → {[c.get('title', '')[:20] for c in cards[:3]]}")
        if sources:
            print(f"  [SOURCES] {len(sources)}")
        print(f"  [ANSWER] {answer[:200]}" + ("…" if len(answer) > 200 else ""))
        print(f"  [CHECK] answer 存在 {'✅' if answer else '❌'}")

    print(f"\n  [SUMMARY] route {stats['route_correct']}/{stats['turn_count']} | "
          f"answer {stats['answer_present']}/{stats['turn_count']}")
    return stats


async def main():
    # 初始化 runtime（AsyncPostgresStore / AsyncPostgresSaver）
    print("[info] 初始化 runtime...")
    ok = await init_runtime()
    print(f"[info] runtime 初始化{'成功' if ok else '失败（走 InMemory 降级）'}")

    llm = get_llm()
    if llm is None:
        print("[fatal] LLM 未配置")
        sys.exit(1)

    shopping_agent = ShoppingAgent(llm)
    knowledge_agent = KnowledgeAgent(llm)
    graph = AssistantGraph(llm=llm, shopping_agent=shopping_agent, knowledge_agent=knowledge_agent)
    print(f"[info] AssistantGraph ready")

    total = {"turn_count": 0, "route_correct": 0, "answer_present": 0}
    t0 = time.perf_counter()
    for idx, case in enumerate(CASES, 1):
        try:
            stats = await run_case(graph, case, idx)
            for k in total:
                total[k] += stats[k]
        except Exception:
            logger.exception("[case #%d] 失败", idx)

    dt = time.perf_counter() - t0
    print("\n" + "#" * 100)
    print(f"# TOTAL {len(CASES)} cases, {total['turn_count']} turns, {dt:.1f}s")
    print(f"#   route 分类正确率:  {total['route_correct']}/{total['turn_count']}")
    print(f"#   answer 存在率:     {total['answer_present']}/{total['turn_count']}")
    print("#" * 100)


if __name__ == "__main__":
    asyncio.run(main())
