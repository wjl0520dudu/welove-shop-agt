"""Restricted failure fallback for Shopping capabilities.

Normal requests are decided by ``ShoppingAgent(create_agent)``.  This module
is intentionally retained only for a model/tool-loop failure after the Agent
path has already been attempted.  It must not inspect history or resolve
cross-turn product references.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping


ShoppingCapability = Literal[
    "recommend", "compare", "detail", "user_context", "transaction_unsupported"
]


@dataclass(frozen=True)
class DispatchDecision:
    capability: ShoppingCapability
    confidence: float
    source: Literal["rule", "llm"] = "rule"
    reason: str = ""


_TRANSACTION_RE = re.compile(r"加(入)?购物车|加购|下单|结算|支付|购买这(个|款)|直接买")
_COMPARE_RE = re.compile(r"对比|比较|哪个好|哪款好|性价比|前[两二]个|这[两二]个|它们")
_DETAIL_RE = re.compile(r"多少钱|什么价|价格|库存|有货|缺货|规格|色号|尺码|型号|成分|详情|介绍一下|第二个|第[一二三四五六七八九]个|这款|那款")
_RECOMMEND_RE = re.compile(r"推荐|帮我(找|选)|找(一|几|个|款)|搜(一|索)|想买|适合我|预算|[0-9]+\s*元|同款|相似")
_CONTEXT_RE = re.compile(r"我的(收藏|订单|浏览|历史|偏好)|根据我的|我上次买")
# Query-level product reference: "{name}的{detail_aspect}" — e.g. "小棕瓶的成分".
# Allows first-turn detail dispatch without prior product memory.
_PRODUCT_ATTR_IN_QUERY = re.compile(r".{2,6}的(成分|功效|作用|原理|用法|浓度|副作用|禁忌)")


def dispatch_shopping_capability(
    question: str,
    memory: Mapping[str, Any] | None = None,
) -> DispatchDecision | None:
    """Return only high-certainty choices; ambiguous requests remain LLM-owned."""
    text = (question or "").strip()
    del memory

    if _TRANSACTION_RE.search(text):
        return DispatchDecision("transaction_unsupported", 0.99, reason="explicit transaction request")
    if _CONTEXT_RE.search(text):
        return DispatchDecision("user_context", 0.95, reason="explicit user shopping context request")
    if _COMPARE_RE.search(text):
        return DispatchDecision("compare", 0.96, reason="explicit comparison expression")
    # Only a query-local product attribute can be a detail fallback.  Generic
    # “它多少钱” must remain unresolved rather than consuming history.
    if _DETAIL_RE.search(text) and _PRODUCT_ATTR_IN_QUERY.search(text):
        return DispatchDecision("detail", 0.95, reason="explicit query-level product attribute")
    if _RECOMMEND_RE.search(text):
        return DispatchDecision("recommend", 0.94, reason="explicit product discovery/recommendation expression")
    return None
