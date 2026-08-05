"""Controlled long-conversation fixtures for rolling-summary evaluation.

Each fixture is one conversation, not one isolated follow-up.  The eligible
prefix is deliberately expanded by the runner to the configured production
character threshold; then three consecutive follow-ups reuse the same summary.
The assistant replies between measured turns are fixed visible fixtures so that
the full-history and rolling-summary variants receive semantically identical
history.  This isolates the effect of context representation from answer-model
drift.
"""

from __future__ import annotations

from typing import Any


def _messages(topic: str, facts: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return an old prefix plus exactly ten recent visible messages."""

    eligible_prefix = [
        {"role": "user", "content": f"我想咨询{topic}，请结合我的情况说明。"},
        {"role": "assistant", "content": f"好的。已确认的需求与事实：{facts}"},
        {"role": "user", "content": "我还关心价格、使用场景和注意事项。"},
        {"role": "assistant", "content": f"已记录：{facts}；后续会以这些已确认条件为准。"},
        {"role": "user", "content": "先不用马上下结论，我再补充一些背景。"},
        {"role": "assistant", "content": "明白，我会保留已确认的需求、约束与讨论对象。"},
        {"role": "user", "content": "请把这些条件作为后续回答的基础，不要遗漏。"},
        {"role": "assistant", "content": f"已确认并记录本轮前缀事实：{facts}"},
    ]
    # This is the same newest-message window that production keeps verbatim.
    recent = [
        {"role": "user", "content": "请继续围绕刚才的需求，不要混入其他话题。"},
        {"role": "assistant", "content": "好的，我会只使用这次会话已确认的信息。"},
        {"role": "user", "content": "如果信息不足，请直接说明，不要编造。"},
        {"role": "assistant", "content": "收到。"},
        {"role": "user", "content": "之前提到的限制条件仍然有效。"},
        {"role": "assistant", "content": "我会继续遵守已确认的限制条件。"},
        {"role": "user", "content": "后面的问题会基于这次会话继续问。"},
        {"role": "assistant", "content": "明白，我会延续当前会话的已确认上下文。"},
        {"role": "user", "content": "不需要切换到其他商品或话题。"},
        {"role": "assistant", "content": "好的，保持当前讨论范围。"},
    ]
    return eligible_prefix, recent


def _continuations(topic: str, facts: str, first_question: str, route: str) -> list[dict[str, str]]:
    """Three post-summary turns that must reuse the same prior context."""

    if route == "shopping":
        questions = [
            first_question,
            "请继续按刚才已确认的预算、场景和偏好筛选，不要换成其他品类。",
            "如果前面有多个候选，请继续说明我该怎样结合刚才的条件选择。",
        ]
    elif route == "knowledge":
        questions = [
            first_question,
            "基于刚才的结论，再说明使用或判断时最需要注意的一点。",
            "请继续解释这个结论适用于什么情况，不要脱离前面的讨论对象。",
        ]
    else:
        questions = [
            first_question,
            "把刚才讨论过的重点再归纳一下。",
            "谢谢，今天先这样。",
        ]
    return [
        {
            "question": question,
            "expected_route": route,
            # Fixed, minimal visible reply.  It is appended before the next
            # measured question to model a continuous conversation without
            # allowing one variant's generated answer to contaminate the other.
            "assistant_reply": f"已继续围绕{topic}回答；后续仍以已确认上下文为准。",
            "topic_facts": facts,
        }
        for question in questions
    ]


def summary_context_cases() -> list[dict[str, Any]]:
    """Return 20 multi-turn long-conversation scenarios; no production data."""

    specs = [
        ("summary-001", "通勤耳机", "预算 500 元以内，通勤使用，优先降噪和舒适佩戴", "按我前面说的预算和通勤场景推荐耳机", "shopping"),
        ("summary-002", "油皮防晒", "油皮，夏天出油多，想要清爽不黏腻的防晒", "继续按我之前的肤质推荐防晒", "shopping"),
        ("summary-003", "护肤成分", "此前讨论了烟酰胺、视黄醇及其刺激风险", "我之前问过哪些成分问题？", "chitchat"),
        ("summary-004", "跑鞋", "男士通勤慢跑，预算 800 元以内，需要缓震和日常耐穿", "按前面的条件推荐跑鞋", "shopping"),
        ("summary-005", "知识咨询", "用户询问果酸和视黄醇能否同用，已强调刺激叠加风险", "刚才那个成分搭配的结论是什么？", "knowledge"),
        ("summary-006", "对话回顾", "用户先问防晒，再问通勤耳机，最后询问烟酰胺作用", "总结一下这次对话", "chitchat"),
        ("summary-007", "咖啡", "用户想要无糖、提神、适合下午饮用的咖啡", "继续找符合我前面要求的咖啡", "shopping"),
        ("summary-008", "话题切换", "早先讨论油皮护肤；用户现在只想了解开放式耳机和入耳式耳机区别", "开放式耳机和入耳式耳机有什么区别？", "knowledge"),
        ("summary-009", "手机", "预算 5000 元以内，重视拍照、续航和通勤使用", "按刚才的预算推荐手机", "shopping"),
        ("summary-010", "敏感肌面霜", "敏感肌，想保湿修护，避免刺激性成分和浓重香味", "前面说的敏感肌面霜怎么选？", "shopping"),
        ("summary-011", "商品对比", "此前推荐三款真无线耳机，讨论重点是降噪、续航和佩戴", "把刚才那几款耳机按降噪和续航对比一下", "shopping"),
        ("summary-012", "防晒知识", "已经讨论防晒的补涂频率、通勤场景和油皮肤感", "防晒霜多久补涂一次？", "knowledge"),
        ("summary-013", "护肤回顾", "用户依次问了视黄醇、果酸、烟酰胺的作用和搭配", "我刚才问了什么？", "chitchat"),
        ("summary-014", "运动鞋", "用户需要男士 42 码、周末跑步和日常通勤都能穿的跑鞋", "继续推荐适合我的跑鞋", "shopping"),
        ("summary-015", "成分安全", "用户有敏感肌，之前询问高浓度烟酰胺是否会刺激", "那我这种肤质使用烟酰胺要注意什么？", "knowledge"),
        ("summary-016", "零食", "用户正在减脂，偏好低糖、方便携带的下午加餐", "按前面的减脂要求找点零食", "shopping"),
        ("summary-017", "对话状态", "用户已得到油皮防晒推荐，并表示暂时不需要更多商品", "谢谢，今天先这样", "chitchat"),
        ("summary-018", "知识话题切换", "前面讨论了咖啡推荐；当前问题转为玻尿酸的保湿原理", "透明质酸为什么能保湿？", "knowledge"),
        ("summary-019", "预算继承", "用户先设定 300 元预算，再要求送给妈妈、偏温和护肤", "继续在之前预算内推荐礼物", "shopping"),
        ("summary-020", "历史总结", "用户先后讨论通勤耳机、油皮防晒和敏感肌护肤", "总结我们这次聊过的需求", "chitchat"),
    ]
    cases: list[dict[str, Any]] = []
    for case_id, topic, facts, question, route in specs:
        prefix, recent = _messages(topic, facts)
        continuations = _continuations(topic, facts, question, route)
        cases.append({
            "id": case_id,
            "scenario": "rolling_summary_long_conversation",
            "eligible_prefix_messages": prefix,
            "recent_messages": recent,
            "continuations": continuations,
        })
    return cases
