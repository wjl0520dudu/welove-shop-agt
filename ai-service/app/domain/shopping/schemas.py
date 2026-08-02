"""ShoppingAgent 高层 Capability 的稳定契约（Pydantic）。

设计原则：
1. **schemas 是 Capability 之间、Capability 和 Tool 之间的唯一通信协议**。
   底层 dict 只在 Capability 内部流转（比如召回结果、Milvus 行）；
   一旦跨模块，就要走这里定义的模型。
2. **字段命名对齐前端**：product_cards 里的 key 保持和当前 `_cards_from_products`
   一致（title/brand/price/image_url/rating/sales_count/sub_category/reason），
   前端不需要改。
3. **Tool 返回结构必须自解释**：`action` 字段（recommend/clarify/empty/detail/compare）
   直接告诉 LLM 该怎么组织回答；`trace` 字段给上层观测用。
4. **不做过度类型化**：ranked_products 里的 metadata 类字段仍用 dict，
   避免把召回层的所有可能字段都提前枚举。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---- 上下文（Capability 入参 + 内部传递）--------------------------------

class ShoppingContext(BaseModel):
    """一次 Capability 调用的上下文快照。

    从 ToolRuntime.state 和 Store 一次读齐，避免 Capability 内部再回读。
    """

    conversation_id: Optional[str] = None
    user_id: Optional[int | str] = None
    jwt_token: Optional[str] = None
    run_id: Optional[str] = None

    is_logged_in: bool = False
    # Router 注入的最小业务快照。它不用于在 Shopping Capability 内二次
    # 消解指代；跨轮商品选择只能使用 selected_product_ids。
    business_memory: Dict[str, Any] = Field(default_factory=dict)

    # 常用快捷字段，避免每个 Capability 都 memory.get(...)
    last_product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    selected_product_ids: List[int] = Field(default_factory=list)
    last_focused_product: Optional[Dict[str, Any]] = None
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    image_url: Optional[str] = None
    input_mode: Literal["text", "image", "multimodal"] = "text"


# ---- 购物需求（ShoppingNeed）--------------------------------------------

# 需要 clarify 时兜底提问的必填槽位。MVP 只强制 category；送礼场景加 target_user。
REQUIRED_SLOTS = ("category",)


class ShoppingNeed(BaseModel):
    """LLM parse_need 抽取的结构化购物需求，跨轮合并的载体。

    与旧 `ShoppingIntent` 的区别：
    - 不再是"是否是购物请求"的判定器（那是 Router 的活）；
    - 新增 preferences / avoid / must_have / nice_to_have / sort_preference / missing_slots / confidence。
    """

    category: Optional[str] = None
    brand: Optional[str] = None

    budget_min: Optional[float] = None
    budget_max: Optional[float] = None

    target_user: Optional[str] = None   # 学生 / 妈妈 / 男士 / 自用
    skin_type: Optional[str] = None      # 油皮 / 干皮 / 敏感肌 / 混油
    scenario: List[str] = Field(default_factory=list)   # 通勤 / 夏天 / 礼物 / 户外

    preferences: List[str] = Field(default_factory=list)    # 正向偏好：清爽/保湿/便携
    avoid: List[str] = Field(default_factory=list)          # 反向排除：油腻/香味重
    must_have: List[str] = Field(default_factory=list)
    nice_to_have: List[str] = Field(default_factory=list)

    # 长期画像只参与软重排；与本轮明确 preferences/avoid 分开，保证当前请求优先。
    personalization_preferences: List[str] = Field(default_factory=list)
    personalization_avoid: List[str] = Field(default_factory=list)
    personalization_budget_min: Optional[float] = None
    personalization_budget_max: Optional[float] = None
    applied_preference_facts: List[Dict[str, Any]] = Field(default_factory=list)

    sort_preference: Literal[
        "match", "price_low", "price_high", "rating", "sales", "value"
    ] = "match"

    missing_slots: List[str] = Field(default_factory=list)  # parse_need 觉得缺的槽
    confidence: float = 0.0


class ProductFilterPlan(BaseModel):
    """Server-owned product constraints; LLM output never becomes an expr directly."""
    hard_filters: Dict[str, Any] = Field(default_factory=dict)
    soft_preferences: List[str] = Field(default_factory=list)
    relaxation_policy: Dict[str, bool] = Field(default_factory=dict)


# ---- 检索计划（内部使用，MVP 阶段仅召回层内部消费）-----------------------

class ShoppingRetrievalPlan(BaseModel):
    """把 ShoppingNeed 翻译成"给检索器看"的计划。

    Phase 1a 只有一路（PgVectorStore），字段仍然预留完整，
    Phase 1b 切 Milvus 三路时零改动。
    """

    primary_query: str = ""
    semantic_queries: List[str] = Field(default_factory=list)
    keyword_queries: List[str] = Field(default_factory=list)

    # Milvus/PG 通用过滤字段
    filters: Dict[str, Any] = Field(default_factory=dict)
    hard_filters: Dict[str, Any] = Field(default_factory=dict)
    # 召回不足时的放宽阶梯
    relaxed_filters: List[Dict[str, Any]] = Field(default_factory=list)

    top_k: int = 20
    initial_top_k: int = 20    # 两阶段召回时的第一阶段候选数
    use_rerank: bool = True

    # Phase 1b：检索模式（hybrid/dense/bm25），默认 hybrid。
    # A/B 测试时可以显式指定，让 verify 脚本对比效果。
    search_mode: Literal["hybrid", "dense", "bm25", "sparse"] = "hybrid"


# ---- 排序后的商品（Capability 内部 + Tool 输出）--------------------------

class RankedProduct(BaseModel):
    """排序后的商品，携带匹配理由。

    LLM 拿到这个 dict 后写话术不用重新发明理由 —— rank_reason / matched_needs
    直接抄。这也是把"为什么推荐它"从 LLM 逻辑里剥出来的关键手段。
    """

    product_id: int
    title: str
    brand: str = ""
    price: Optional[float] = None
    base_price: Optional[float] = None
    image_url: str = ""
    rating: Optional[float] = None
    review_count: int = 0
    sales_count: int = 0
    category: str = ""
    sub_category: str = ""
    tags: str = ""
    description: str = ""

    # 排序侧字段
    score: float = 0.0
    recall_sources: List[str] = Field(default_factory=list)   # dense / bm25 / hybrid / relaxed
    matched_needs: List[str] = Field(default_factory=list)
    unmatched_needs: List[str] = Field(default_factory=list)
    rank_reason: List[str] = Field(default_factory=list)      # 可读的匹配理由，喂给 LLM 抄
    risk_notes: List[str] = Field(default_factory=list)       # 潜在提醒（超预算/避雷词命中等）
    personalization_score: float = 0.0
    matched_preferences: List[str] = Field(default_factory=list)
    preference_conflicts: List[str] = Field(default_factory=list)
    # Phase 3 single LLM judge verdict. Optional for Phase 2/old messages.
    match_status: Optional[Literal["exact", "alternative"]] = None
    constraint_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    judge_reason: str = ""


class CandidateSet(BaseModel):
    """One retrieval result contract for text, image and multimodal recommend.

    Phase 2 only unifies candidate transport.  Semantic match verdicts such as
    exact/alternative/reject intentionally remain a later Candidate Judge task.
    """

    input_mode: Literal["text", "image", "multimodal"] = "text"
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_channels: List[str] = Field(default_factory=list)
    retrieval_counts: Dict[str, int] = Field(default_factory=dict)
    query_text: str = ""
    image_fingerprint: Optional[str] = None


# ---- 三个高层 Tool 的返回契约 -------------------------------------------

class CandidateSearchToolResult(BaseModel):
    """候选召回窄 Tool 的内部契约。

    ``candidates`` 只表示已经从真实商城召回的有限候选，还没有完成
    exact / alternative 语义审核，也不会直接生成商品卡。
    """

    action: Literal["candidates", "clarify", "empty"]
    need: Optional[ShoppingNeed] = None
    candidate_set: Optional[CandidateSet] = None
    clarify_question: Optional[str] = None
    empty_reason: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)


class RecommendToolResult(BaseModel):
    """recommend_products 高层 Tool 返回的稳定结构。

    action 三态：
    - recommend: 正常出卡片
    - clarify:   槽位不齐，把 clarify_question 问给用户
    - empty:     检索没结果，给 empty_reason
    """

    action: Literal["recommend", "clarify", "empty"]
    need: Optional[ShoppingNeed] = None
    candidate_set: Optional[CandidateSet] = None
    assumptions: List[str] = Field(default_factory=list)
    ranked_products: List[RankedProduct] = Field(default_factory=list)
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    clarify_question: Optional[str] = None
    empty_reason: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)


class CompareToolResult(BaseModel):
    """旧回滚 ``compare_products`` Tool 返回。

    dimensions 是维度顺序（价格/评分/销量/成分/…），
    comparison_rows 每行一个商品在各维度上的取值；正常 DeepAgent 主链使用
    ``BoundProductFactsToolResult``，不依赖本契约的 suggestion。
    """

    action: Literal["compare", "clarify", "empty"]
    products: List[Dict[str, Any]] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    comparison_rows: List[Dict[str, Any]] = Field(default_factory=list)
    suggestion: Dict[str, Any] = Field(default_factory=dict)
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    clarify_question: Optional[str] = None
    empty_reason: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)


class DetailToolResult(BaseModel):
    """旧回滚 ``answer_product_detail`` Tool 返回。

    当前回滚实现返回完整可信 facts，focus 仅为旧消息兼容字段；正常 DeepAgent
    主链使用 ``BoundProductFactsToolResult``，由 Agent 理解开放详情问法。
    """

    action: Literal["detail", "clarify", "empty"]
    product: Optional[Dict[str, Any]] = None
    focus: Optional[Literal[
        "price", "stock", "sku", "overview", "suitability", "ingredients"
    ]] = None
    facts: Dict[str, Any] = Field(default_factory=dict)
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    clarify_question: Optional[str] = None
    empty_reason: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)


class BoundProductFactsToolResult(BaseModel):
    """DeepAgent 主链统一的已绑定商品事实契约。

    Agent 负责理解用户关心的比较或详情维度；Tool 只按 Router 已绑定 ID
    返回真实商品与 SKU 事实，不从 query 猜测 focus，也不替 Agent 做选择。
    """

    action: Literal["compare_facts", "detail_facts", "clarify", "empty"]
    purpose: Literal["compare", "detail"]
    products: List[Dict[str, Any]] = Field(default_factory=list)
    product_cards: List[Dict[str, Any]] = Field(default_factory=list)
    missing_product_ids: List[int] = Field(default_factory=list)
    clarify_question: Optional[str] = None
    empty_reason: Optional[str] = None
    trace: List[Dict[str, Any]] = Field(default_factory=list)


# ---- pending_shopping_need（多轮澄清结构化槽位）--------------------------

class PendingShoppingNeed(BaseModel):
    """跨轮保留在 Store 里的"待补全需求"快照。

    只在 RecommendCapability 决定 clarify 时写入；
    下一轮 recommend_products 被调用时读出、和当前 parse 结果合并、清空。
    """

    status: Literal["clarifying"] = "clarifying"
    need: ShoppingNeed
    missing_slots: List[str] = Field(default_factory=list)
    last_clarify_question: str = ""
    turn_count: int = 1
