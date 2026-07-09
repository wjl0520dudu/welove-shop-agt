"""方案 B 端到端测试：跳过重的首轮 shopping，直接预置 business_memory，
只测第 2/3/4 轮的指代场景。

流程：
1. 脚本自己 init_runtime() 连上 PG Store
2. 用 remember_product_cards 预置一个 conversation_id 的 memory
3. 向 /api/assistant/run 发追问（同一个 conversation_id）
4. 服务端读 PG Store → 拿到 memory → Router 应正确分类 → ShoppingAgent 应调 resolve_reference

关键：脚本进程和服务器进程都连同一个 PG 库，Store 数据是共享的。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

# Windows: psycopg async 需要 SelectorEventLoop，必须在任何 loop 创建前切换
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 让脚本能 import agents/ tools/ 等（tests/ 不在 sys.path 里）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Windows 控制台 GBK 编码，避免 emoji 打印失败
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import httpx

BASE_URL = "http://localhost:8000"
CONVERSATION_ID = f"e2e-B-{uuid.uuid4().hex[:8]}"

# 预置：3 个粉底液商品（模拟上一轮 shopping 已经推荐过）
PRESET_CARDS = [
    {
        "product_id": 20, "title": "雅诗兰黛持妆粉底液",
        "price": 440, "brand": "雅诗兰黛", "rating": 3.6, "sales_count": 0,
    },
    {
        "product_id": 21, "title": "兰蔻超越持妆粉底液",
        "price": 380, "brand": "兰蔻", "rating": 4.5, "sales_count": 200,
    },
    {
        "product_id": 22, "title": "美宝莲亲肤粉底液",
        "price": 129, "brand": "美宝莲", "rating": 4.2, "sales_count": 500,
    },
]

SCENARIOS = [
    {
        "label": "轮2：序号指代「第二个」",
        "question": "第二个多少钱？",
        "expected_route": "shopping",
        "expected_matched_id": 21,   # 期望解析为 index 1 = 兰蔻
    },
    {
        "label": "轮3：比较指代「更便宜的」",
        "question": "更便宜的那款怎么样",
        "expected_route": "shopping",
        "expected_matched_id": 22,   # 期望解析为 price 最低 = 美宝莲
    },
    {
        "label": "轮4：代词指代「刚才那个」",
        "question": "刚才那个能不能给我详细讲讲",
        "expected_route": "shopping",
        "expected_matched_id": 20,   # 期望 fallback 到 cards[0]（focused 未设）
    },
]


async def preset_memory():
    """脚本进程连 PG，往 Store 里写入预置商品卡。"""
    from agents.runtime import init_runtime, is_persistent
    from agents.memory import remember_product_cards

    ok = await init_runtime()
    print(f"[preset] init_runtime → persistent={is_persistent()}")
    if not ok:
        print("[preset] ⚠️  PG 未连上，脚本预置的 memory 存 InMemory，服务器读不到！")
        return False

    await remember_product_cards(CONVERSATION_ID, None, PRESET_CARDS)
    print(f"[preset] 已写入 {len(PRESET_CARDS)} 个商品到 conversation_id={CONVERSATION_ID}")

    # 验证读回
    from agents.memory import get_business_memory
    memory = await get_business_memory(CONVERSATION_ID, None)
    read_cards = memory.get("last_product_cards", [])
    print(f"[preset] 读回验证：{len(read_cards)} 个商品")
    if len(read_cards) != len(PRESET_CARDS):
        print("[preset] ❌ 读回的商品数不对！")
        return False
    return True


async def run_scenario(client: httpx.AsyncClient, sc: dict) -> dict:
    payload = {
        "question": sc["question"],
        "conversation_id": CONVERSATION_ID,
    }
    print(f"\n{'=' * 70}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {sc['label']}")
    print(f"Q: {sc['question']}")
    print(f"{'=' * 70}")

    resp = await client.post(
        f"{BASE_URL}/api/assistant/run",
        json=payload,
        timeout=180.0,
    )
    resp.raise_for_status()
    data = resp.json()

    route = data.get("route")
    task_type = data.get("task_type")
    answer = data.get("answer", "")
    product_cards = data.get("product_cards", [])
    tool_calls = data.get("tool_calls", [])

    print(f"→ route:         {route}")
    print(f"→ task_type:     {task_type}")
    print(f"→ answer:        {answer[:200]}")
    print(f"→ product_cards: {len(product_cards)} 个")
    for i, card in enumerate(product_cards[:3], 1):
        print(f"    {i}. id={card.get('product_id')} title={card.get('title', 'N/A')[:30]} ¥{card.get('price')}")
    print(f"→ tool_calls:    {len(tool_calls)} 次")
    for tc in tool_calls[:10]:
        name = tc.get("name") or tc.get("tool_name") or "?"
        args = tc.get("args") or tc.get("arguments") or {}
        print(f"    - {name}({json.dumps(args, ensure_ascii=False)[:80]})")

    # 断言
    checks = []
    # task_type 是最终子节点写的，route 是 Router 写的；两个都验证
    effective_route = route or task_type
    if effective_route == sc["expected_route"]:
        checks.append(("✅", f"Router/task_type == {sc['expected_route']}"))
    else:
        checks.append(("❌", f"route={route} task_type={task_type} 均不匹配 {sc['expected_route']}"))

    tool_names = [
        (tc.get("name") or tc.get("tool_name") or "").lower()
        for tc in tool_calls
    ]
    if "resolve_reference" in tool_names:
        checks.append(("✅", "调用了 resolve_reference"))
    else:
        checks.append(("⚠️ ", f"未见 resolve_reference（tools: {tool_names}）"))

    # 期望的商品是否出现在 answer 或 product_cards 里
    expected_id = sc.get("expected_matched_id")
    expected_card = next((c for c in PRESET_CARDS if c["product_id"] == expected_id), None)
    if expected_card:
        expected_title_substr = expected_card["title"][:6]  # 取前 6 字符（品牌+品类特征）
        if expected_title_substr in answer:
            checks.append(("✅", f"answer 提到期望商品「{expected_title_substr}」"))
        else:
            checks.append(("⚠️ ", f"answer 未见期望商品「{expected_title_substr}」"))

    print("→ checks:")
    for status, msg in checks:
        print(f"    {status} {msg}")

    return {
        "label": sc["label"],
        "route": route,
        "task_type": task_type,
        "tool_calls": tool_names,
        "checks": checks,
    }


async def main():
    print(f"conversation_id: {CONVERSATION_ID}\n")

    # Step 1: 脚本自己连 PG，预置商品卡
    ok = await preset_memory()
    if not ok:
        print("\n❌ 预置失败，中止测试")
        return

    # Step 2: 三个场景请求
    async with httpx.AsyncClient() as client:
        results = []
        for sc in SCENARIOS:
            try:
                r = await run_scenario(client, sc)
                results.append(r)
            except Exception as e:
                print(f"❌ 场景失败：{e!r}")
                results.append({"label": sc["label"], "error": str(e)})

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    pass_count = 0
    total_checks = 0
    for r in results:
        for status, _ in r.get("checks", []):
            total_checks += 1
            if status == "✅":
                pass_count += 1
    print(f"{pass_count}/{total_checks} checks passed")


if __name__ == "__main__":
    asyncio.run(main())
