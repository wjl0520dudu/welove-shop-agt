content = r"""# AI 助手架构文档 — Day22

> 生成时间：2026-07-06
> 工作目录：`G:\dev\welove-shop-agt\backend\ai-service`

---

## 目录

1. [已完成功能（当前稳定版）](#1-已完成功能当前稳定版)
2. [核心设计：共享记忆机制](#2-核心设计共享记忆机制)
3. [Current Architecture — 全景图](#3-current-architecture-全景图)
4. [ShoppingAgent 评估与改造计划](#4-shoppingagent-评估与改造计划)
5. [数据库选型：pgvector vs Milvus](#5-数据库选型pgvector-vs-milvus)
6. [未来功能路线图](#6-未来功能路线图)
7. [关键文件索引](#7-关键文件索引)

---

## 1. 已完成功能（当前稳定版）

### 1.1 Supervisor 主图（assistant/graph.py）

主图是一个 LangGraph StateGraph，结构为：

```
START → route_intent → [shopping | knowledge | chitchat | unknown] → format_response → END
```

**关键设计决策**：

- 主图编译时带 `checkpointer=checkpointer`（InMemorySaver），按 `thread_id` 持久化完整对话历史
- `state["messages"]` 使用 `add_messages` reducer 自动累积合并
- 所有子 agent 从 `state["messages"]` 接收完整对话历史，实现多 agent 共享记忆
- 主图 checkpointer 是唯一的事实来源（single source of truth）

**`run()` 方法流程**：

```python
state = {
    "question": question,
    "conversation_id": conversation_id,
    "messages": [HumanMessage(content=question)],
    ...
}
final = await self.graph.ainvoke(
    state,
    config={"configurable": {"thread_id": conversation_id}}
)
```

同一 `conversation_id` → 同一 `thread_id` → checkpointer 加载旧 state → `add_messages` 合并新消息 → 子 agent 看到完整历史。

### 1.2 路由器（router agent）

- 使用 `create_agent` + `ToolStrategy(IntentDecision)` 结构化输出
- **独立 checkpointer**（`_router_checkpointer = InMemorySaver()`），每次调用传唯一 `thread_id`（`str(uuid4())`）
- 独立隔离的原因：`create_agent` 内部的工具调用会往 checkpointer 写消息，如果用共享 checkpointer + 同一 thread_id，router 上一轮的 tool_call 消息（空 content 的 IntentDecision AIMessage）会混入下一轮对话，LLM 被污染

**ROUTER_PROMPT（已修复）**：

```markdown
分类规则：
- shopping: 搜索/推荐/比较具体商品
- knowledge: 了解知识/用法/成分/适合什么（即使提到商品名）
- chitchat: 闲聊/问候/元问题（关于对话本身）
- unknown: 无法判断

判断优先级（从高到低）：
1. 先查是否为元问题 → chitchat
2. 再查是否为知识问题 → knowledge
3. 最后才考虑 shopping
```

**已修复的问题**：
- "干皮适合什么粉底液？" 曾被误判为 shopping（因为 knowledge 定义模糊）
- "我刚刚问了什么问题？" 曾被误判为 knowledge（因为历史话题是知识）

### 1.3 KnowledgeAgent（knowledge/agent.py）

- 使用 `create_agent` + `search_knowledge` 工具 + `KnowledgeResult` 结构化输出
- **独立 checkpointer**（`_knowledge_checkpointer = InMemorySaver()`）+ 每次唯一 `thread_id`
- **对话级知识缓存**：`_knowledge_cache` 字典，key = `MD5(question)`，同一问题直接返回缓存
- **置信度分流**：`run()` 返回 `confidence` 字段
- 检索底层：Milvus 向量库（hybrid search）

**结构化输出**：

```python
class KnowledgeResult(BaseModel):
    answer: str
    sources: List[Dict]
    has_answer: bool
    search_query_used: str
    confidence: float  # 0.0 - 1.0
    tool_calls: List[Dict]
```

### 1.4 ChitchatAgent（assistant/nodes.py — chitchat_node）

- 使用 `create_agent` + `ToolStrategy(ChitchatResult)` 结构化输出
- **独立 checkpointer**（`_chitchat_checkpointer = InMemorySaver()`）+ 每次唯一 `thread_id`
- 从 `state["messages"]` 接收完整对话历史，能看到全部上下文

**CHITCHAT_PROMPT（专业增强）**：

```markdown
角色：电商导购助手，不是通用聊天机器人
工作流程：
1. 先理解对话历史
2. 判断聊天气氛
3. 自然回应

回应规范：
- 问候类 → 热情打招呼
- 感谢类 → 愉快回应
- 告别类 → 简短道别
- 记忆类（"刚才说了什么"）→ 准确回顾对话历史
- 无关话题 → 引导回购物场景
- 情绪表达 → 简短共情后引导回正题
```

**结构化输出**：

```python
class ChitchatResult(BaseModel):
    answer: str
    mood: Literal["friendly", "warm", "professional", "playful"]
```

### 1.5 置信度分流（knowledge_node）

```python
confidence = result.get("confidence", 1.0)
if confidence < 0.5:
    # 不暂停图（非 HITL），只换回答策略
    clarify_msg = f"关于「{question}」，我目前的信息不够充分..."
    return {"answer": clarify_msg, "task_type": "chitchat", ...}
```

这不是 Human-in-the-Loop（不需要 `interrupt()`），图不暂停，只是在节点内根据置信度换一种回答策略。

### 1.6 ShoppingAgent（shopping/agent.py — 当前工作流版）

- LangGraph 子图：`analyze_query → search_products → generate_answer → build_response`
- LCEL 三段式 chain（INTENT_PROMPT | llm | StrOutputParser → JSON 解析）
- 商品检索：MySQL `LIKE` 子串匹配 + 确定性软匹配排序
- 返回全量 ProductCard（product_id + title + brand + price + image_url + rating + ...）
- **这是待改造的部分**（详见第 4 节）

---

## 2. 核心设计：共享记忆机制

### 2.1 两层记忆架构

| 层级 | 机制 | 作用域 | 实现 |
|------|------|--------|------|
| 短期记忆（对话级） | `checkpointer` + `add_messages` reducer | 同一 `thread_id`（即同一 `conversation_id`） | `InMemorySaver` in `agents/runtime.py` |
| 长期记忆（业务级） | `InMemoryStore` | 跨 thread（用户偏好、上次推荐商品） | `InMemoryStore` in `agents/runtime.py` |

### 2.2 多 Agent 共享记忆流程

```
第1轮：用户问 "干皮适合什么粉底液？"
  → run() 将 HumanMessage 写入 state["messages"]
  → graph.ainvoke(state, thread_id="conv-123")
  → checkpointer 保存 state（messages 含 Human + AI 回答）

第2轮：用户问 "我刚刚问了什么问题？"
  → run() 将新 HumanMessage 写入 state["messages"]
  → graph.ainvoke(state, thread_id="conv-123")
  → checkpointer 加载旧 state
  → add_messages reducer 合并 → messages 现在有 4 条
  → router 看到 4 条历史 → 分类为 chitchat
  → chitchat_node 看到 4 条历史 → 回顾对话内容
```

### 2.3 子 Agent 的 checkpointer 隔离原则

**为什么子 agent 不能用主图的 checkpointer？**

`create_agent` 必须带 checkpointer 才能让 `ainvoke` 返回 coroutine（否则返回 dict，报 `TypeError: object dict can't be used in 'await' expression`）。

但子 agent 内部的工具调用会往自己的 checkpointer 写消息。如果用共享 checkpointer + 同一 thread_id，上一轮的 tool_call 消息（如 `IntentDecision` 结构化输出的空 content AIMessage）会混入下一轮对话，LLM 被污染。

**解决方案**：每个子 agent 使用独立 `InMemorySaver` + 每次调用传唯一 `thread_id`（`str(uuid4())`）。

| 子 Agent | checkpointer | thread_id |
|----------|-------------|-----------|
| Router | `_router_checkpointer` | `str(uuid4())` 每次 |
| KnowledgeAgent | `_knowledge_checkpointer` | `str(uuid4())` 每次 |
| ChitchatAgent | `_chitchat_checkpointer` | `str(uuid4())` 每次 |

共享记忆通过主图的 `state["messages"]` 传入，子 agent 不需要自己的持久化对话记忆。

### 2.4 `g.compile(checkpointer=checkpointer)` 做了什么

把 checkpointer 注册到编译好的图中。具体行为：

- 调用 `graph.ainvoke(state, config={"configurable": {"thread_id": ...}})` 时
- checkpointer 用 `thread_id` 查之前保存的状态
- 如果有，加载并用 `add_messages` reducer 合并新旧 messages
- 图执行完毕后，最新状态自动保存回 checkpointer
- 同一 `conversation_id` → 同一 `thread_id` → 同一个持久化槽位 → 跨轮次记忆

---

## 3. Current Architecture — 全景图

```
用户输入
  │
  ▼
graph.run(state, thread_id=conversation_id)     ← 主图 checkpointer（共享记忆）
  │
  ▼
route_intent ──── router agent ─────────────── 独立 checkpointer + uuid thread_id
  │                  ToolStrategy(IntentDecision)   从 state["messages"] 读取完整历史
  │
  ├─ shopping  ── ShoppingAgent（LCEL 子图）── MySQL LIKE 检索        ⚠️ 待改造
  ├─ knowledge ── KnowledgeAgent ──────────── 独立 checkpointer + uuid thread_id
  │                  └─ confidence < 0.5? → fallback 到 chitchat-style 追问
  │                  └─ 对话级知识缓存
  ├─ chitchat  ── create_agent ────────────── 独立 checkpointer + uuid thread_id
  │                  ToolStrategy(ChitchatResult)
  └─ unknown   ── 静态回复
  │
  ▼
format_response → 输出
```

**已稳定的子 Agent**：Router、KnowledgeAgent、ChitchatAgent
**待改造**：ShoppingAgent

---

## 4. ShoppingAgent 评估与改造计划

### 4.1 当前状态

```
ShoppingAgent (agent.py)
  └→ ShoppingRecommender (recommender.py) — LangGraph 子图
       ├→ analyze_query    — LCEL: INTENT_PROMPT | llm | StrOutputParser → JSON 解析
       ├→ search_products  — ProductRepository.search_products() → MySQL LIKE
       ├→ generate_answer  — LCEL: ANSWER_PROMPT | llm
       └→ build_response   — 构造 ProductCard + log_recommendation
```

### 4.2 三个核心问题

**问题 1：检索层 — MySQL LIKE 是瓶颈**

```python
# product_repository.py 当前实现
stmt = select(ProductORM).where(
    or_(
        CategoryORM.name.like(f"%{intent.category}%"),
        ProductORM.title.like(f"%{intent.category}%"),
        ProductORM.tags.like(f"%{intent.category}%"),
        ProductORM.description.like(f"%{intent.category}%"),
    )
).order_by(ProductORM.sales_count.desc())
```

这是精确子串匹配，存在以下问题：
- "干皮适合什么粉底液" → intent.category 可能是"粉底液"，LIKE 查不到标签为"保湿""滋润"的粉底液
- 同义词覆盖不到：用户说"控油"，商品标签写的是"清爽"
- 语义偏好匹配不了：用户说"适合熬夜肌"，商品里没有"熬夜"两个字

`ProductORM` 已预留 `embedding_status` 字段，说明数据库层面考虑过向量化。

**问题 2：架构层面 — 固定流水线，LLM 没有工具调用能力**

KnowledgeAgent 已经是 `create_agent`（有工具、能多轮调用、能结构化输出）。ShoppingAgent 还是老式三段式 LCEL chain + 固定 SQL。LLM 不能自主决定：换关键词重搜、追问用户澄清、对比两个商品。

`recommender2.py` 导入了 `create_agent` 但没用上，注释说"部分 OpenAI 兼容代理不支持 function calling / structured output，会 400"。

**问题 3：可扩展性差**

每加一个功能（反选排除、用户画像、多模态）都要改子图节点结构，不像 `create_agent` 加个 tool 那么简单。

### 4.3 改造方案：做成真正的 create_agent

```python
# 目标架构
create_agent(
    model=llm,
    checkpointer=_shopping_checkpointer,  # 独立
    system_prompt=SHOPPING_PROMPT,         # 专业规则
    tools=[search_products, get_product_detail, compare_products],
    response_format=ToolStrategy(ShoppingResult),
)
```

**工具设计**：

| 工具 | 功能 | 参数 |
|------|------|------|
| `search_products` | 向量召回 + 关系过滤 | query, category, brand, budget_min, budget_max, exclude_brands, exclude_tags, limit |
| `get_product_detail` | 查单个商品详情 | product_id |
| `compare_products` | 对比多个商品 | product_ids: list[int] |

**结构化输出**：

```python
class ShoppingResult(BaseModel):
    answer: str
    product_cards: List[ProductCard]
    need_followup: bool = False
    followup_question: Optional[str] = None
    confidence: float = 0.0
```

**提示词升级**（类似 KNOWLEDGE_PROMPT 的完整规则）：

```markdown
你是「微爱商城」的专业导购 agent。你必须严格遵循以下规则：

## 工作流程
1. 理解用户需求：结合对话历史和当前问题
2. 调用搜索工具：用 search_products 检索真实商品
3. 如果结果不够，改关键词重搜
4. 基于真实商品生成推荐话术
5. 如需对比，调用 compare_products

## 搜索策略
- 第一次用用户原话搜索
- 如果结果少，尝试同义词或更宽泛的关键词
- 用户提到"第二个""刚才那个"时，从对话历史理解指代

## 回答规范
- 只能基于工具返回的真实商品推荐
- 禁止编造商品、价格、评分、销量
- 推荐时说明每个商品的适合人群和理由
- 如果商品信息不足，明确说"从当前商品信息看"

## 结构化输出
answer + product_cards + need_followup + confidence
```

### 4.4 返回格式：保持全量 ProductCard

当前返回全量 ProductCard（product_id + title + brand + price + image_url + rating + review_count + sales_count）是合理的。前端直接渲染卡片，不多一次 HTTP 调用。AI 侧 MySQL 和 SpringBoot 侧 MySQL 是同一实例，不存在同步问题。

---

## 5. 数据库选型：pgvector vs Milvus

### 5.1 当前状态

- 主库：MySQL（商品、分类、推荐日志、购物车）
- 向量库：Milvus（仅存知识库向量）
- 商品检索：SQLAlchemy + MySQL `LIKE`

### 5.2 未来需求对数据库的要求

| 需求 | 目录 | 需要的能力 |
|------|------|-----------|
| 对话式购物车管理 | 关系型读写 | 增删改购物车条目 |
| 反选排除 | 精确过滤 | `brand NOT IN (...)` + `price NOT IN range` |
| 用户画像感知 | KV 读写 | 读写用户偏好（key-value） |
| 多模态图文检索 | embedding + metadata | CLIP embedding → 向量召回 + 过滤 |
| 渐进式需求收敛 | 叠加过滤 | 多轮过滤条件叠加 + 保持中间状态 |

### 5.3 三方案对比

| 能力 | MySQL + Milvus 双库 | 纯 pgvector | MySQL（当前） |
|------|---------------------|-------------|----------------|
| 向量语义检索 | Milvus 负责 | pgvector 负责 | 不支持 |
| 精确过滤（价格/品牌/排除） | MySQL 负责 | 同一条 SQL | LIKE，弱 |
| 跨库 JOIN（向量结果 + 商品详情） | 需要应用层拼接 | 原生 JOIN | 原生 |
| 购物车 / 推荐日志 | MySQL | PostgreSQL | MySQL |
| 多模态 embedding | Milvus 支持 | pgvector 支持 | 不支持 |
| 长期记忆（user profile） | 需要额外 store | 同一库的表 | MySQL 表 |
| 运维复杂度 | 两个库 | 一个库 | 一个库 |
| 团队熟悉度 | MySQL 熟 | 需要学 | 熟 |

### 5.4 推荐：pgvector（方案 A）

**核 reel 价值**：在同一个 SQL 查询里同时做向量召回 + 关系过滤 + 聚合排序：

```sql
-- 一条语句同时完成向量召回 + 关系过滤 + 排序
SELECT id, title, brand, price, image_url, rating,
       embedding <=> $1 AS distance
FROM products_search
WHERE status = 1
  AND brand NOT IN ('排除品牌')
  AND base_price <= $2
ORDER BY embedding <=> $1
LIMIT 10;
```

不需要跨库拼接。

**分阶段迁移路径**：

**阶段 1（现在）**：MySQL 继续做主业务库。引入 pgvector 做搜索层专用数据库

```
MySQL（主库，不变）
  ├→ 商品表、购物车、推荐日志、用户信息 — SpringBoot 读写
  └→ 同步到 pgvector（只读副本）
        └→ products_search 表（id, title, brand, price, ..., embedding）
              AI 检索只查这里
```

**阶段 2（未来）**：pgvector 稳定后，考虑把主库逐步迁移到 PostgreSQL

### 5.5 备选：Milvus 加商品 collection（方案 B）

```
MySQL（主库）
  ├→ 商品表 — SpringBoot 读写
  └→ 同步到 Milvus
        └→ products collection
              向量召回 → 拿 product_id → 回 MySQL 过滤
```

**优点**：复用已有 Milvus 基础设施，最快上线
**缺点**：反选排除 / 渐进式收敛要用 Milvus expr 拼接，调试体验不如 SQL；跨库拼接增加应用层复杂度

### 5.6 决策建议

- 如果优先快速验证搜索效果 → 先走方案 B，后续迁到方案 A
- 如果优先长期可维护性 → 直接走方案 A（pgvector）
- 两条路的 embedding 生成一样，迁移成本主要在数据搬运

---

## 6. 未来功能路线图

### 6.1 实施优先级

```
第一步（检索层 — 最大收益）
  □ 选 pgvector 或 Milvus 建商品搜索表/集合
  □ 把 MySQL 商品批量向量化写入
  □ 检索工具切换为向量召回 + 关系过滤

第二步（agent 架构对齐）
  □ ShoppingAgent 改为 create_agent + search_products tool
  □ 和 KnowledgeAgent 架构统一
  □ 独立 checkpointer + uuid thread_id

第三步（未来功能逐步加工具）
  □ 反选排除：search_products 工具加 exclude_brands / exclude_price_range 参数
  □ 用户画像感知：get_user_profile / save_user_preference 工具
  □ 多模态图文检索：search_by_image 工具（CLIP embedding → pgvector）
  □ 对话式购物车管理：add_to_cart / remove_from_cart / list_cart 工具
  □ 渐进式需求收敛：create_agent 工具调用循环天然实现
```

### 6.2 未来功能 → 工具映射

| 未来功能 | 对应工具 | 底层依赖 |
|----------|----------|----------|
| 对话式购物车管理 | add_to_cart, remove_from_cart, list_cart | MySQL（购物车表），需要 jwt_token |
| 反选排除 | search_products 加 exclude_brands / exclude_price_range 参数 | pgvector SQL 或 Milvus expr |
| 用户画像感知 | get_user_profile / save_user_preference | InMemoryStore 或 pgvector 表 |
| 多模态图文检索 | search_by_image | CLIP embedding → pgvector / Milvus |
| 渐进式需求收敛 | create_agent 工具调用循环 | 无额外工具，agent 天然支持多轮工具调用 |

### 6.3 为什么 create_agent 适合渐进式收敛

用户说"再便宜点""不要这个牌子"，agent 自主改参数重新调用 `search_products`，不需要在固定工作流里硬编码分支。工具调用循环本身就是渐进式收敛的最佳载体。

---

## 7. 关键文件索引

| 文件 | 职责 | 状态 |
|------|------|------|
| `assistant/graph.py` | Supervisor 主图：路由 → 子节点 → 格式化 | ✅ 稳定 |
| `assistant/nodes.py` | 子节点实现（shopping/knowledge/chitchat/unknown/format） | ✅ 稳定（chitchat 已改为 create_agent） |
| `assistant/router.py` | 旧版规则兜底路由（LCEL 管道式），当前未接入主图 | 📦 备用 |
| `agents/state.py` | AssistantState TypedDict + add_messages reducer | ✅ 稳定 |
| `agents/schemas.py` | IntentDecision / KnowledgeResult / ChitchatResult / ProductCard | ✅ 稳定 |
| `agents/prompts.py` | ROUTER_PROMPT / KNOWLEDGE_PROMPT / CHITCHAT_PROMPT / SHOPPING_AGENT_PROMPT | ✅ 稳定 |
| `agents/runtime.py` | 全局 checkpointer（InMemorySaver）+ store（InMemoryStore） | ✅ 稳定 |
| `knowledge/agent.py` | KnowledgeAgent（create_agent + search_knowledge + 缓存 + confidence） | ✅ 稳定 |
| `shopping/agent.py` | ShoppingAgent（转发到 ShoppingRecommender） | ⚠️ 待改造 |
| `shopping/recommender.py` | ShoppingRecommender（LangGraph 子图 + LCEL chain） | ⚠️ 待改造 |
| `shopping/recommender2.py` | 未使用的 create_agent 版本（导入但未启用） | 📦 参考 |
| `shopping/product_repository.py` | ProductRepository（MySQL LIKE 检索） | ⚠️ 待改造 |
| `shopping/models.py` | ShoppingIntent / ProductCandidate / ProductCard / ShoppingState | ✅ 稳定 |
| `shopping/orm_models.py` | SQLAlchemy ORM（ProductORM / CategoryORM / RecommendationLogORM） | ✅ 稳定 |
| `rag/vector_store.py` | MilvusVectorStore（知识库向量检索） | ✅ 稳定 |
| `rag/retriever.py` | Retriever（知识库检索逻辑） | ✅ 稳定 |
| `rag/models.py` | RetrievalPlan / SearchRequest / SearchResult / Source | ✅ 稳定 |
| `tests/test_router.ipynb` | 路由测试 notebook | ✅ 已修复 typo |
| `tests/test_check_router.ipynb` | 路由验证测试 notebook | ✅ 已修复 typo |

---

## 8. 已解决的 Bug 记录

### Bug 1：`ValueError: Checkpointer requires one or more of the following 'configurable' keys`

**根因**：`create_agent` 的 `ainvoke` 需要 config 里带 `thread_id`，否则 checkpointer 不知道存哪个槽位。

**修复**：所有子 agent 的 `ainvoke` 都传 `config={"configurable": {"thread_id": str(uuid4())}}`。

### Bug 2：`TypeError: object dict can't be used in 'await' expression`

**根因**：`create_agent(checkpointer=None)` 的 `ainvoke` 返回 dict 而非 coroutine。

**修复**：`create_agent` 必须带 checkpointer（`InMemorySaver()`），不能传 `None`。

### Bug 3：Router 消息污染（"我刚刚问了什么" 误判为 knowledge）

**根因**：router 使用共享 checkpointer + 同一 thread_id，上一轮的 tool_call 消息（空 content 的 IntentDecision AIMessage）混入下一轮对话。

**修复**：router 用独立 checkpointer + 每次唯一 uuid thread_id。

### Bug 4：地铁问题分类错误（"干皮适合什么粉底液" 误判为 shopping）

**根因**：ROUTER_PROMPT 把 knowledge 定义为"与具体商品无关的知识问答"，LLM 看到"粉底液"就归到 shopping。

**修复**：重写 ROUTER_PROMPT，明确 knowledge 标志词包括「适合什么」「怎么用」「区别」等，即使提到商品品类名也归 knowledge。加判断优先级：元问题 > 知识 > shopping。

### Bug 5：Notebook typo（"我刚刚问了什么" 实际没问到）

**根因**：`test_check_router.ipynb` Cell 4 写成了 `uestion`（少了 `q`），Python 用了 Cell 3 的旧变量 `question = "干皮适合什么粉底液？"`。

**修复**：`question` → `question`。

---

## 9. ShoppingAgent 改造实施清单

> 以下为后续开发参考的实施步骤

### Step 1：数据库选型与搭建

```
□ 决定方案 A（pgvector）还是方案 B（Milvus 加 collection）
□ 如选 pgvector：
    - 安装 PostgreSQL + pgvector 扩展
    - 创建 products_search 表（id, title, brand, price, ..., embedding vector(1536)）
    - 建立 HNSW 索引
□ 如选 Milvus：
    - 创建 products collection（product_id, dense_vector, title, brand, price, ...）
    - 建立索引
```

### Step 2：商品数据向量化

```
□ 编写 build_product_embeddings.py 脚本
□ 从 MySQL 读取所有 status=1 的商品
□ 用 OpenAIEmbeddings 生成 embedding（title + description + tags + category + sub_category）
□ 批量写入 pgvector 表 / Milvus collection
□ 验证向量检索效果
```

### Step 3：检索工具实现

```
□ 实现 search_products 工具
    - 向量召回（embedding → pgvector / Milvus）
    - 关系过滤（price, brand, exclude_brands, exclude_tags）
    - 排序（distance + sales_count + rating）
□ 实现 get_product_detail 工具（查单个商品）
□ 实现 compare_products 工具（对比多个商品，可选）
```

### Step 4：ShoppingAgent 改造为 create_agent

```
□ 创建 ShoppingResult 结构化输出 schema
□ 升级 SHOPPING_AGENT_PROMPT 为完整工作规则
□ 创建独立 checkpointer + uuid thread_id
□ 集成 search_products / get_product_detail / compare_products 工具
□ 测试：用户问 "干皮适合什么粉底液" → 向量召回 + 推荐话术
□ 测试：多轮对话 "再便宜点" "不要这个品牌" → 渐进式收敛
```

### Step 5：未来功能逐步迭代

```
□ 反选排除：search_products 加 exclude 参数
□ 用户画像感知：get_user_profile / save_user_preference 工具
□ 多模态图文检索：search_by_image 工具
□ 对话式购物车管理：cart 工具集
□ 渐进式需求收敛：验证 create_agent 多轮工具调用
```

---

*文档结束*
"""
import os

path = r"G:\dev\ShopAgent-X\docs\output\day22\ai-assistant-architecture-day22.md"
os.makedirs(os.path.dirname(path), exist_ok=True)

encoding = __import__("codecs").lookup("utf-8")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

print(f"Written to: {path}")
print(f"Size: {os.path.getsize(path)} bytes")
print(f"Lines: {content.count(chr(10)) + 1}")