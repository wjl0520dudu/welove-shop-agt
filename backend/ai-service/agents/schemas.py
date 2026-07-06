# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

# 主图只产 shopping|knowledge|chitchat|unknown；cart 仅为兼容旧购物车库保留。
TaskType = Literal["shopping", "knowledge", "chitchat", "unknown", "cart"]


class IntentDecision(BaseModel):
    task_type: TaskType = Field(
        ...,
        description="意图分类: shopping=搜索/推荐/比较具体商品, knowledge=了解知识/用法/成分/适合什么(即使提到商品名), chitchat=闲聊/问候/元问题(关于对话本身), unknown=无法判断",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="分类置信度")
    reason: str = Field("", description="分类理由")


class AgentFinalResponse(BaseModel):
    answer: str = ""
    task_type: TaskType = "unknown"
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    error: bool = False
    error_code: Optional[str] = None
    message: Optional[str] = None


class AgentRequestContext(BaseModel):
    """cart 库工具上下文（不接入主图，仅购物车库使用）。"""
    question: str = ""
    context: str = ""
    conversation_id: Optional[str] = None
    user_id: Optional[int] = None
    jwt_token: Optional[str] = None
    is_admin: bool = False
    confirmed: bool = False
    cart_action: Optional[str] = None
    product_id: Optional[int] = None
    sku_id: Optional[int] = None
    cart_item_id: Optional[int] = None
    quantity: int = 1
    business_memory: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeResult(BaseModel):
    """知识 agent 的结构化输出。"""
    answer: str = Field(..., description="基于检索结果综合生成的最终回答")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="引用的知识来源列表，包含 title 和 score")
    has_answer: bool = Field(True, description="是否在知识库中找到了相关内容")
    search_query_used: str = Field("", description="实际使用的检索查询词")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="回答置信度")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="本次执行中调用的工具记录")


class ChitchatResult(BaseModel):
    """闲聊 agent 的结构化输出。"""
    answer: str = Field(..., description="自然友好的闲聊回复")
    mood: Literal["friendly", "warm", "professional", "playful"] = Field(
        "friendly", description="回复语气"
    )


class ShoppingResult(BaseModel):
    """导购 agent 的结构化输出。"""
    answer: str = Field(..., description="基于真实商品的推荐话术")
    product_cards: List[Dict[str, Any]] = Field(
        default_factory=list, description="推荐的商品卡片列表"
    )
    need_followup: bool = Field(
        False, description="是否需要追问用户以澄清需求"
    )
    followup_question: Optional[str] = Field(
        None, description="追问用户的问题"
    )
    confidence: float = Field(
        0.0, ge=0.0, le=1.0, description="推荐置信度"
    )