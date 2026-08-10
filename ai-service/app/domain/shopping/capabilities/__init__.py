"""ShoppingAgent 的高层 Capability 模块。

Capability 为受控业务 Tool 提供真实数据与确定性边界。DeepAgent 主链中推荐
拆为候选召回/终结，比较和详情共用绑定商品事实加载；旧一体化 Capability
仅保留给人工回滚链。

设计准则：
1. 一个 Capability 一个类，`.run(...)` 返回对应的 *ToolResult。
2. 开放语言理解交给 Agent/LLM；代码只处理绑定、事实查询和确定性计算。
3. Capability 里可以调 tools/shopping_tools.py 的旧工具，作为"内部函数"复用
   （search / detail / compare），但**不再**把它们挂给 LLM。
"""

from app.domain.shopping.capabilities.recommend import RecommendCapability
from app.domain.shopping.capabilities.compare import CompareCapability
from app.domain.shopping.capabilities.detail import DetailCapability
from app.domain.shopping.capabilities.facts import BoundProductFactsCapability
from app.domain.shopping.capabilities.user_context import UserShoppingContextCapability

__all__ = [
    "RecommendCapability",
    "CompareCapability",
    "DetailCapability",
    "BoundProductFactsCapability",
    "UserShoppingContextCapability",
]
