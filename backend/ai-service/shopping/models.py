from __future__ import annotations

from typing import List, Optional, TypedDict

from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field


class ShoppingIntent(BaseModel):
    """LLM 对用户导购需求的结构化理解。"""

    is_shopping_request: bool = Field(description="用户是否在请求商品推荐或导购")
    category: Optional[str] = Field(default=None, description="商品品类，例如 防晒、面霜、耳机")
    brand: Optional[str] = Field(default=None, description="用户明确提到的品牌")
    budget_min: Optional[float] = Field(default=None, description="最低预算")
    budget_max: Optional[float] = Field(default=None, description="最高预算")
    target_user: Optional[str] = Field(default=None, description="使用人群，例如 学生、妈妈、男士")
    scenario: Optional[str] = Field(default=None, description="使用场景，例如 夏天、通勤、户外")
    preferences: List[str] = Field(default_factory=list, description="偏好，例如 清爽、便携、大容量")
    avoid: List[str] = Field(default_factory=list, description="不想要的点，例如 油腻、太贵、香味重")
    compare_mode: bool = Field(default=False, description="是否是在做商品对比")
    need_followup: bool = Field(default=False, description="信息是否不足，需要追问")
    followup_question: Optional[str] = Field(default=None, description="需要追问用户的问题")


class ProductCandidate(BaseModel):
    """数据库中的真实商品候选。"""

    product_id: int
    title: str
    brand: Optional[str] = None
    price: Optional[float] = None
    base_price: Optional[float] = None
    image_url: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    sales_count: Optional[int] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    reason: Optional[str] = None


class ProductCard(BaseModel):
    """返回给前端的稳定商品卡片。"""

    product_id: int
    title: str
    brand: str = ""
    price: float = 0
    image_url: str = ""
    rating: float = 0
    review_count: int = 0
    sales_count: int = 0
    sub_category: str = ""
    reason: str = ""


class ShoppingState(TypedDict, total=False):
    """LangGraph 在各节点之间流转的状态。"""

    question: str
    context: Optional[str]
    user_id: Optional[int]
    session_id: Optional[str]
    intent: ShoppingIntent
    candidates: List[ProductCandidate]
    answer: str
    product_cards: List[ProductCard]
    error: Optional[str]
    profile: Optional[dict]

    memory_saver = InMemorySaver  # 短期记忆
    memory_store = InMemoryStore  # 长期记忆
