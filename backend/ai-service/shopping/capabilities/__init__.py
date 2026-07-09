"""ShoppingAgent 的高层 Capability 模块。

每个 Capability 对应一个高层 @tool（recommend/compare/detail/user_context），
Tool 只做参数收敛 + 结果 dump，Capability 才是"确定性 pipeline"的主体。

设计准则：
1. 一个 Capability 一个类，`.run(...)` 返回对应的 *ToolResult。
2. 不依赖 LLM 的地方一律走规则代码；只有 parse_need / feature extract
   这种真需要 LLM 语义的地方才 with_structured_output。
3. Capability 里可以调 tools/shopping_tools.py 的旧工具，作为"内部函数"复用
   （search / detail / compare），但**不再**把它们挂给 LLM。
"""

from shopping.capabilities.recommend import RecommendCapability
from shopping.capabilities.compare import CompareCapability
from shopping.capabilities.detail import DetailCapability
from shopping.capabilities.user_context import UserShoppingContextCapability

__all__ = [
    "RecommendCapability",
    "CompareCapability",
    "DetailCapability",
    "UserShoppingContextCapability",
]
