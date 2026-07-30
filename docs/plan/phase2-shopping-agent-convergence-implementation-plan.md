# Phase 2：Shopping Tool Agent 收敛与待完成修复计划

> 状态：代码完成，待真实 AI Service / Milvus 人工验收
>
> 前置状态：Phase 1 已完成并验收，基线提交为 `80e58f8 feat(ai): 完成 Phase 1 上下文理解与复杂任务路由收敛`。
>
> 上位计划：`docs/plan/agent-stability-convergence-implementation-plan.md`
>
> 本文用途：作为 Phase 2 后续编码、Review、离线测试、真实 API 冒烟和提交验收的唯一专项清单。本文不覆盖上位计划，也不提前实现 Phase 3 的候选语义评估与诚实替代策略。

> 本次实现记录（2026-07-30）：已完成正常路径 `create_agent` 收敛、请求级 Tool Guard、文本/纯图/图文统一入口、Router 绑定 ID 约束、活动商品 Collection 复用与离线回归。真实 DashScope、Milvus 与多轮 API/H5 验收仍由人工环境执行；Phase 3 的 Candidate Judge、`exact/alternative/reject` 与替代推荐策略仍未提前实现。

## 1. 本阶段目标

Phase 2 只解决 Shopping 领域内部的职责和执行链收敛：

1. Router 负责上层上下文理解、领域路由和商品实体绑定，但不决定 Shopping 内部的推荐、对比或详情操作。
2. ShoppingAgent 必须成为真正的 `create_agent(LLM + 高层工具)`，由 LLM 根据 Router 交付的完整问题选择高层工具。
3. 规则 Dispatcher 退出正常主链，只能在模型工具选择持续失败时做可观测、受限的故障降级。
4. 纯文本、纯图片和图文请求统一进入 ShoppingAgent；输入模式只影响推荐工具内部的候选生成方式。
5. Compare/Detail 只消费 Router 已绑定的商品 ID，不再从原始问题、任意历史文本或历史商品卡中二次猜测。
6. 增加单轮工具调用 Guard，防止相同推荐参数重复执行以及多个主要 Shopping capability 混用。
7. 收紧 ShoppingAgent 输入和 Prompt，使它只承担商品发现、比较、详情、条件权衡和自然表达。
8. 统一工具调用观测，能明确区分正常 Agent Tool Loop、受限规则降级、重复调用拦截和工具异常。
9. 用能力级 Plan-and-Execute 操作手册和 few-shot 约束 ShoppingAgent 的执行顺序，避免开放式 ReAct Loop 在工具之间无收益游走。

本阶段不新增全局 Graph 节点，不新增 Schema/事实语义 Validator，不扩大关键词或正则语义判断。

## 2. 已确认的职责边界

### 2.1 Router 的职责

Router 是唯一的上层上下文理解和领域路由节点，负责：

- 基于完整可用会话上下文完成指代消解；
- 处理槽位继承、话题延续和话题切换；
- 生成无跨轮歧义的 `canonical_question`；
- 判断 `shopping / knowledge / chitchat / unknown`；
- 判断 `simple / complex`；
- 将“第一款和第三款”“前两款”“它们”等引用绑定为真实商品 ID；
- 标记图片是否属于当前任务。

Router 不负责：

- 决定 Shopping 内部应调用 `recommend / compare / detail`；
- 直接执行 Shopping 工具；
- 根据商品候选做推荐结论；
- 查询价格、SKU、库存或向量库。

### 2.2 ShoppingAgent 的职责

ShoppingAgent 属于 Shopping 领域执行 Agent，负责：

- 根据 `canonical_question` 自主选择高层工具；
- 在推荐、比较、详情之间选择本轮主要 Shopping capability；
- 结合高层工具返回的结构化候选和真实事实生成自然回答；
- 解释商品差异、用户条件和商品事实之间的关系；
- 在缺少已绑定商品时给出自然澄清。

ShoppingAgent 不负责：

- 重新读取完整会话历史；
- 重新消解“它、第一款、刚才那个”等跨轮指代；
- 从 Redis、Store 或任意历史卡片中猜商品；
- 重新判断顶层领域或复杂度；
- 绕过工具虚构商品、价格、库存、SKU 或商品 ID。

### 2.3 Compare/Detail 的归属

`compare_products` 和 `answer_product_detail` 是 ShoppingAgent 挂载的高层工具，不属于 Router。

正确链路：

```text
用户：比较刚才第一款和第三款
  → Router：绑定 product_ids=[42, 37]，路由到 shopping
  → ShoppingAgent：判断应调用 compare_products
  → compare_products(product_ids=[42, 37])
  → ShoppingAgent：根据结构化结果生成回答
```

Router 只绑定商品，ShoppingAgent 才决定调用 Compare 还是 Detail。

## 3. 当前代码审计结果

当前 Phase 2 不是从零开始，已经具备部分骨架，但正常路径仍然混合了 Agent、规则和图片旁路。

| 项目 | 当前状态 | 当前代码表现 | Phase 2 目标 |
|---|---|---|---|
| `create_agent` | 已存在 | `shopping/agent.py` 已挂载 4 个高层工具 | 保留并成为正常请求的唯一 Shopping 决策入口 |
| 高层工具 | 已存在 | 推荐、对比、详情、用户购物上下文均已封装 | 清理职责描述并统一输入输出 |
| Dispatcher | 未收敛 | `ShoppingAgent.run()` 在 `create_agent()` 前调用 `dispatch_shopping_capability()` | 正常路径不再调用；只在 Agent 持续失败后受限降级 |
| 多模态入口 | 未统一 | `assistant/nodes.py` 有图时直接执行 `_multimodal_shopping()` | 文本、图片、图文全部先进入 ShoppingAgent |
| Compare 商品绑定 | 部分完成 | 优先使用 `selected_product_ids`，但仍解析 query 和 `last_product_cards` | 只接受 Router 绑定 ID |
| Detail 商品绑定 | 部分完成 | 优先使用单个绑定 ID，但仍使用序号、代词、focused product 和单卡兜底 | 只接受 Router 绑定 ID |
| 推荐重复调用 | 未实现 | 只有 `recursion_limit` 和结果卡片去重 | 增加请求级参数签名和成功结果复用 |
| Agent 历史输入 | 未收敛 | `ShoppingAgent` 仍构造并接收历史 messages，并读取 business memory | 只接收当前完整问题和最小绑定上下文 |
| Prompt/docstring | 部分完成 | 主 Prompt 已领域化，但工具描述仍提到自动读取/合并历史需求 | 删除上下文理解职责，补充工具 few-shot 和边界 |
| 工具观测 | 部分完成 | 已有 `tool_calls`、`dispatch_source`，但来源、耗时和去重状态不统一 | 统一正常、降级、去重和失败观测字段 |

当前关键位置：

- `ai-service/app/domain/shopping/agent.py`
- `ai-service/app/domain/shopping/dispatcher.py`
- `ai-service/app/domain/shopping/high_level_tools.py`
- `ai-service/app/domain/shopping/capabilities/recommend.py`
- `ai-service/app/domain/shopping/capabilities/compare.py`
- `ai-service/app/domain/shopping/capabilities/detail.py`
- `ai-service/app/domain/shopping/schemas.py`
- `ai-service/app/domain/shopping/context.py`
- `ai-service/app/application/assistant/nodes.py`
- `ai-service/app/application/assistant/state.py`
- `ai-service/app/prompts/prompts.py`

## 4. Phase 2 目标架构

```text
resolve_context
  → Router LLM
      输出：canonical_question、domain=shopping、mode、resolved_product_ids、image_scope
  → shopping_node（只组装数据）
  → ShoppingAgent create_agent
      输入：完整问题、已绑定商品、图片作用域、最小必要用户信息、可用高层工具
      ├─ recommend_products
      ├─ compare_products
      ├─ answer_product_detail
      └─ get_user_shopping_context（仅显式需要个人数据时作为辅助工具）
  → Tool Call Guard
      ├─ 主要 capability 约束
      ├─ 同参数调用去重
      ├─ 已绑定商品 ID 校验
      └─ 调用次数和失败边界
  → 高层 Capability
  → 结构化 ToolResult / CandidateSet
  → ShoppingAgent 自然回答
  → Response / SSE
```

其中 `get_user_shopping_context` 是辅助工具，不算本轮主要 capability。一个明确的推荐请求允许按需先读取用户明确要求的基础画像或收藏摘要，再调用一次 `recommend_products`，但不能同时混用推荐、比较和详情三个主要 capability。

ShoppingAgent 使用 LangChain `create_agent`，因此它是真正能选择和调用工具的 Agent；本阶段不是把它改造成规则工作流。Plan-and-Execute 的作用是用 Prompt 中的能力操作手册约束 Agent 的思考和执行顺序，不是额外增加一个 Shopping Planner LLM 或新的 Graph 节点。

## 5. 内部输入输出契约

### 5.1 Router 交给 ShoppingAgent 的最小输入

不新增外部 API，优先通过现有 AssistantState/ShoppingAgentState 扩展内部字段：

```python
class ShoppingTurnInput:
    canonical_question: str
    resolved_product_ids: list[int]
    image_url: str | None
    image_scope: bool
    input_mode: Literal["text", "image", "multimodal"]
    basic_preferences: dict[str, Any]
    conversation_id: str | None
    user_id: int | str | None
    jwt_token: str | None
```

约束：

- 不传 Router 的 `operation`，因为 Router 不决定 `recommend/compare/detail`；
- 不传完整原始历史给 ShoppingAgent；
- `resolved_product_ids` 是跨轮商品绑定的唯一权威来源；
- `basic_preferences` 只保留当前已启用的基础标签，不包含已关闭的长期行为偏好；
- `conversation_id/user_id/jwt_token` 仅用于会话隔离、权限和真实业务查询，不允许用于二次读取历史做指代消解。

### 5.2 ShoppingAgent 输出

保持现有外部响应兼容，内部至少统一以下字段：

```python
{
    "answer": str,
    "task_type": "shopping",
    "capability": "recommend|compare|detail|user_context|clarify",
    "dispatch_source": "agent_tool_loop|restricted_rule_fallback|none",
    "product_cards": list[dict],
    "tool_calls": list[dict],
    "error": bool,
    "error_code": str | None,
}
```

`dispatch_source=agent_tool_loop` 表示由 ShoppingAgent LLM 正常选择工具；正常请求不得再返回当前的 `dispatch_source=rule`。

### 5.3 Phase 2 的 CandidateSet

Phase 2 只统一候选容器，不在本阶段加入 `exact/alternative/reject` 语义判断：

```python
class CandidateSet:
    input_mode: Literal["text", "image", "multimodal"]
    candidates: list[dict[str, Any]]
    retrieval_channels: list[str]
    retrieval_counts: dict[str, int]
    query_text: str
    image_fingerprint: str | None
```

候选商品必须包含稳定的真实字段，例如：

- `product_id`
- `title`
- `brand`
- `category/sub_category`
- `price/base_price`
- `status`
- `image_url`
- 检索或重排所需的内部得分

CandidateSet 是推荐工具内部和 Agent 返回结果之间的统一中间契约，不直接改变现有前端商品卡协议。

### 5.4 ShoppingAgent 的 Plan-and-Execute Prompt 契约

ShoppingAgent 的底层运行时使用 LangChain `create_agent(model=LLM, tools=高层工具)`。它保留 LLM 的工具选择能力，但不采用“没有任务边界的自由 ReAct”：系统 Prompt 为每一种 Shopping capability 提供明确、短小且可执行的操作手册。

每轮的固定执行框架：

```text
1. 读取 Router 已交付的 canonical_question、绑定商品和图片作用域
2. 选择一个主要 capability（recommend / compare / detail）
3. 按该 capability 的操作手册调用必要工具
4. 读取结构化 ToolResult
5. 仅基于 ToolResult 组织自然回答或澄清
6. 不重复调用相同工具，不切换到另一个主要 capability
```

其中第 1、2、4、5 步仍由 LLM 执行；第 3 步执行实际工具；Tool Guard 负责保障调用次数和实体边界。模型的内部推理不向用户或日志暴露。

#### 推荐操作手册

```text
输入：完整商品需求，可选图片作用域，可选基础偏好。
1. 将当前完整问题作为 query；不得自行从历史补写需求。
2. 有图片时仍调用同一个 recommend_products；不直接调用底层向量工具。
3. 每轮只调用一次 recommend_products。
4. tool action=recommend：基于返回的真实候选和卡片回答。
5. tool action=clarify：直接提出该澄清问题，不改写 query 后重复搜索。
6. tool action=empty：如实说明未找到，不调用 compare/detail 试图凑答案。
```

#### 对比操作手册

```text
输入：完整对比问题和 Router 已绑定的多个商品 ID。
1. 只调用 compare_products，并使用已绑定商品 ID。
2. 不自行从问题、历史卡片或记忆中补充商品。
3. tool action=compare：依据 comparison_rows 和 suggestion 回答。
4. tool action=clarify：直接请求用户说明要比较的商品，不改为推荐。
5. 一轮内不再调用 recommend_products 或 answer_product_detail。
```

#### 详情操作手册

```text
输入：完整详情问题和 Router 已绑定的单个商品 ID。
1. 只调用 answer_product_detail，并使用该绑定 ID。
2. 只引用 ToolResult 中的价格、SKU、库存、规格和商品事实。
3. tool action=detail：直接回答当前关注点。
4. tool action=clarify：请求用户明确商品；不得猜测“它”指谁。
5. 一轮内不再调用 recommend_products 或 compare_products。
```

#### 显式个人数据辅助操作手册

只有用户明确要求“按我的收藏/浏览/订单/基础画像推荐”时，Agent 才可先调用一次 `get_user_shopping_context`，随后执行一个主要 capability。普通推荐不能为了“猜偏好”而自动调用个人数据工具。

#### Prompt few-shot

Prompt 和高层工具 docstring 至少应包含以下示例，示例用于帮助模型理解工具边界，不是供代码做关键词匹配：

| 用户完整问题与绑定上下文 | 正确执行计划 | 不应执行 |
|---|---|---|
| “推荐适合通勤的降噪耳机” + 无商品绑定 | `recommend_products(query=完整问题)` 一次 | 先读历史、比较、重复推荐 |
| “比较上一轮第 1 款和第 3 款” + `[42, 37]` | `compare_products(product_ids=[42,37])` 一次 | 再解析“第 1/3 款”、重新推荐 |
| “上一轮第 1 款多少钱” + `[42]` | `answer_product_detail(product_id=42)` 一次 | 从历史卡片猜价格、重新搜索 |
| “根据这张图找类似跑鞋” + 图片作用域 | `recommend_products(query=完整问题)` 一次，工具内部走图片召回 | 绕过 Agent 直调 `_multimodal_shopping()` |
| “它多少钱” + 无绑定商品 | 直接自然澄清 | 根据 `last_product_cards` 猜商品 |

Prompt 必须明确要求 Agent 在调用工具前遵循上述操作手册，但不要求模型向用户输出计划、思维过程或内部术语。

## 6. 详细修改项

### P2-01：让 ShoppingAgent 成为正常路径的唯一能力决策者

修改 `ShoppingAgent.run()`：

- 删除 `create_agent()` 之前对 `dispatch_shopping_capability()` 的正常调用；
- 正常请求必须先进入 Agent Tool Loop；
- Agent 根据 Router 已消解问题和高层工具描述选择工具；
- 只允许一个主要 Shopping capability 成功执行；
- `create_agent` 的工具列表只暴露高层业务工具，不重新暴露底层检索、向量库或历史解析工具；
- Agent 按第 5.4 节的 Plan-and-Execute 操作手册执行，而不是自由地在多个主要工具之间试探；
- 没有调用工具但能安全直接回答时，仅限非商品事实的简短说明；商品推荐、价格、SKU、库存和对比不得绕过工具。

受限降级触发条件：

1. Agent 模型调用或工具选择结构连续失败；
2. 允许一次受控重试后仍没有合法高层工具调用；
3. 才允许调用 `dispatch_shopping_capability()`；
4. 降级不得读取历史或解析跨轮指代；
5. 降级结果必须标记 `dispatch_source=restricted_rule_fallback`；
6. 模糊请求直接澄清，不通过扩充关键词强行选择能力。

降级不能因以下情况触发：

- 推荐候选为空；
- 某个候选不满足预算；
- Agent 已成功调用工具但结果不理想；
- 普通自然语言没有命中旧正则。

### P2-02：收紧 ShoppingAgent 输入、Prompt 和工具 docstring

修改 ShoppingAgent 消息构造：

- 正常路径只给 Agent 当前 `canonical_question`；
- 不再把完整历史 messages 复制给 ShoppingAgent；
- 不再在 Agent 内部调用 Store/Redis 获取 `last_product_cards` 来完成上下文理解；
- Router 注入的商品 ID、图片作用域和最小基础偏好通过结构化 state 传递；
- ShoppingAgent 内部的 summarization middleware 不再承担跨轮上下文摘要职责；跨轮历史和后续摘要由 Router 上层链路处理。

主 Prompt 只保留：

- 商品发现；
- 比较；
- 详情；
- 条件权衡；
- 基于工具事实自然表达；
- 必要时澄清。

Prompt 采用“能力级 Plan-and-Execute + few-shot”形式：推荐、对比、详情分别写出输入、固定执行步骤、何时停止、结构化结果如何转成答案，以及典型正反例。这样约束的是 Agent 的工具执行策略，不把能力选择重新下沉为关键词或正则规则。

删除以下职责描述：

- 自行消解指代；
- 自行读取完整会话历史；
- 自行改写用户问题；
- 自行合并任意历史需求；
- 从历史商品卡猜商品；
- 再次执行顶层路由。

`high_level_tools.py` 使用 `@tool(parse_docstring=True)`，docstring 会直接成为 LLM 可见的工具说明，因此必须同步修改。每个工具描述应明确：

- 适用场景；
- 不适用场景；
- 必填结构化输入；
- 返回字段；
- 允许使用的已绑定实体；
- 不允许访问或推断的上下文；
- 典型正例和负例；
- 相同参数不得重复调用。

### P2-03：Compare/Detail 只接受 Router 绑定商品

建立唯一权威字段 `resolved_product_ids/selected_product_ids`，由 Router 输出并在 `shopping_node` 中纯组装后注入 ShoppingAgentState。

Compare：

- 至少需要两个已绑定商品 ID；
- Tool 参数省略时使用 state 中的已绑定 ID；
- Tool 参数显式传入时，必须是已绑定 ID 的有序子集；
- Agent 不能传入未绑定或任意生成的商品 ID；
- 不足两个商品时返回结构化 `clarify`。

Detail：

- 必须且只能定位一个已绑定商品 ID；
- 多个商品但用户问题不能唯一对应时返回结构化 `clarify`；
- 不允许从 `last_focused_product` 或单张历史卡片默认推断。

删除或退出正常路径的逻辑：

- `_resolve_products_from_query()`；
- `_resolve_plural()`；
- `_resolve_ordinal()`；
- `_resolve_pronominal()`；
- `_resolve_implicit()`；
- Compare 默认使用全部 `last_product_cards`；
- Detail 使用 `last_focused_product` 或“历史只有一张卡就是它”的兜底。

这些解析能力应继续由 Router 负责。Capability 只使用真实 ID 查询 Milvus/PostgreSQL 的商品事实。

### P2-04：文本、图片、图文统一进入 ShoppingAgent

修改 `shopping_node`：

- 删除“有图片就直接调用 `_multimodal_shopping()`”的正常旁路；
- 无论有无图片都调用 `ShoppingAgent.run()`；
- 将 `image_url`、`image_scope` 和 `input_mode` 注入 ShoppingAgentState；
- 纯图片问题由 Router 提供可执行的完整问题，例如“根据当前图片查找相似商品”；
- ShoppingAgent 不需要理解图片像素，只需要知道本轮存在可供推荐工具使用的图片。

统一 `recommend_products`：

```text
input_mode=text
  → BM25 + Dense

input_mode=image
  → 图片向量召回

input_mode=multimodal
  → 文本 BM25/Dense + 图片向量 + 融合/VL rerank

三种方式
  → CandidateSet
  → 同一 RecommendToolResult
  → ShoppingAgent 生成回答
```

底层检索通道由代码根据 `input_mode` 选择，不需要 LLM 猜测应该调用哪个底层向量接口。LLM 只选择高层的 `recommend_products`。

现有 `_multimodal_shopping()` 中可复用的检索、图片 URL 规范化、VL rerank 和商品卡构造逻辑应下沉到 RecommendCapability/统一检索层；不在 `nodes.py` 继续维护第二套 Shopping 回答链。

### P2-05：增加请求级 Tool Call Guard 和同参数去重

在 ShoppingAgent 高层工具执行前增加请求级 Guard。优先使用 LangChain Agent middleware/工具包装层实现，不新增全局 Graph 节点。

调用签名建议：

```text
sha256(
  tool_name
  + canonical_json(normalized_args)
  + ordered_bound_product_ids
  + input_mode
  + image_fingerprint
)
```

行为：

- 本轮第一次成功调用：真实执行工具并缓存结构化结果；
- 本轮再次调用相同成功签名：不访问 Milvus、Rerank 或下游服务，直接复用结果；
- 第一次明确失败或超时：不缓存为成功结果，允许一次受控重试；
- 参数、图片或绑定商品变化：视为不同调用；
- 缓存仅在当前请求/Agent run 内有效，不跨用户、会话或下一轮共享；
- 主要 capability 已成功执行后，再调用其他主要 capability 时由 Guard 拒绝并把已有结果返回 Agent 整理。

与 LangChain 自带限制的关系：

- `recursion_limit` 防止整个 Agent 无限循环；
- `ModelCallLimitMiddleware` 限制模型调用总次数；
- `ToolCallLimitMiddleware` 可限制高层工具调用总数；
- 自定义 Tool Call Guard 识别“相同参数”并复用成功结果。

LangChain 的调用次数限制不能自动识别两组参数是否相同，因此不能替代请求级调用签名去重。

### P2-06：统一工具调用观测

统一 `tool_calls` 内部字段，保持现有外部响应向后兼容：

```python
{
    "tool_name": "recommend_products",
    "capability": "recommend",
    "dispatch_source": "agent_tool_loop",
    "args_hash": "...",
    "input_mode": "text|image|multimodal",
    "status": "success|empty|clarify|error|deduplicated|limited",
    "duration_ms": 1234,
    "deduplicated": False,
    "fallback_stage": None,
    "error_code": None,
}
```

统一来源：

| `dispatch_source` | 含义 |
|---|---|
| `agent_tool_loop` | ShoppingAgent LLM 正常选择并执行工具 |
| `restricted_rule_fallback` | Agent 工具选择连续失败后的受限故障降级 |
| `none` | 未执行商品工具，例如澄清或安全说明 |

不得再把正常关键词命中记录为 `dispatch_source=rule`。

观测要求：

- 记录 ShoppingAgent 模型调用次数；
- 记录每个高层工具耗时；
- 记录底层检索模式和候选数量；
- 记录重复调用是否被拦截；
- 记录受限降级触发原因；
- 不记录完整 Prompt、JWT、用户隐私、原始图片 URL 或敏感历史内容；
- 图片只记录不可逆 fingerprint 或是否存在。

### P2-07：清理双路径与兼容处理

在完成测试前，不立即大范围删除旧文件；先让旧逻辑退出正常路径，再根据引用检查清理。

需要处理：

- `_multimodal_shopping()` 退出 `shopping_node` 正常路径；
- Dispatcher 退出正常主链；
- Compare/Detail 历史解析器退出 Capability 正常路径；
- Store 中 `last_product_cards` 仍可由 Router/Preparation 用于上层绑定，也可用于下一轮卡片展示，但不得由 ShoppingAgent/Capability 用来猜测商品；
- 保持 `final → done`、商品卡、SSE 和 chat-service 兼容；
- 保持 `dispatch_source`、`capability`、`tool_calls` 为向后兼容可选字段；
- 不修改已发布 Flyway 历史迁移；
- 不启用长期行为偏好或自动偏好 Proposal。

## 7. Phase 2 与 Phase 3 的边界

Phase 2 负责“由谁决定工具、三种输入如何统一、工具如何安全执行”。

Phase 3 才负责“召回候选是否满足用户开放条件、如何给出诚实替代推荐”。

本阶段不实现：

- `Candidate Judge LLM`；
- `exact / alternative / reject`；
- 预算不满足时的差距解释；
- `match_status / constraint_gaps` 的新判定逻辑；
- 候选宽召回后的语义筛选与软重排重构；
- Shopping Finalizer 的额外独立 LLM 调用。

Phase 2 只建立稳定的 CandidateSet，为 Phase 3 提供唯一候选入口。现有相关性过滤和重排逻辑可先复用，但不能在 Phase 2 扩充关键词或品类别名来代替后续 Judge。

## 8. 预期文件改动

| 文件 | 预期改动 |
|---|---|
| `shopping/agent.py` | 移除 Dispatcher 正常抢占；收紧消息输入；接入 Tool Guard、调用限制和统一观测 |
| `shopping/dispatcher.py` | 收缩为受限降级；禁止读取历史做语义路由 |
| `shopping/high_level_tools.py` | 清理 docstring；补充 few-shot；统一图片/文本推荐入口；接入绑定 ID |
| `shopping/schemas.py` | 增加或收敛 CandidateSet、工具调用观测和内部状态契约 |
| `shopping/context.py` | 只组装 Router 注入的最小 Shopping 上下文 |
| `shopping/capabilities/recommend.py` | 统一三种输入模式和 RecommendToolResult |
| `shopping/capabilities/compare.py` | 删除 query/历史卡片商品解析，只消费绑定 ID |
| `shopping/capabilities/detail.py` | 删除序号、代词、focused product 和单卡兜底，只消费绑定 ID |
| `shopping/multimodal_search.py` 及检索层 | 复用并下沉多模态候选生成，返回统一 CandidateSet |
| `assistant/nodes.py` | 删除图片绕过 ShoppingAgent 的正常分支；纯组装并调用 Agent |
| `assistant/state.py` | 补充 ShoppingAgent 最小输入、图片作用域和请求级 Guard 状态 |
| `prompts/prompts.py` | 收紧 Shopping Prompt，不再包含上下文消解和历史读取职责 |
| 相关测试 | 补充 Agent 选择、三模态统一、绑定 ID、去重、观测和兼容测试 |

实际编码时以最小改动为原则；如果已有契约能够承载字段，不为同一含义重复新增类型或状态。

## 9. 实施顺序

```text
P2-01 固定 Router → ShoppingAgent 输入边界
  → P2-02 移除 Dispatcher 正常抢占
  → P2-03 清理 Prompt 和高层工具 docstring
  → P2-04 Compare/Detail 严格使用绑定 ID
  → P2-05 图片路径下沉并统一 CandidateSet
  → P2-06 接入 Tool Call Guard 和调用次数限制
  → P2-07 统一工具观测
  → P2-08 离线回归、真实 API 冒烟和 H5 人工验收
```

顺序原因：先固定职责和输入，再移动执行路径；否则图片统一、去重和观测仍会建立在旧 Dispatcher/历史兜底之上，后续还需要重复返工。

## 10. 测试计划

### 10.1 单元测试

ShoppingAgent 工具选择：

- “推荐适合通勤的耳机”只调用 `recommend_products`；
- “比较已绑定的第一款和第三款”只调用 `compare_products`；
- “第一款多少钱”只调用 `answer_product_detail`；
- Router 绑定 ID 不传 operation，ShoppingAgent 仍能自主选择正确工具；
- 正常请求不调用 `dispatch_shopping_capability()`；
- Agent 工具选择持续失败时才进入 `restricted_rule_fallback`；
- 模糊输入不通过规则强行执行。

Compare/Detail：

- Compare 按 Router 绑定 ID 的顺序查询并返回；
- Detail 只查询唯一绑定 ID；
- Tool 参数不能引用未绑定 ID；
- 无绑定、绑定不足或绑定歧义时返回 `clarify`；
- `last_product_cards`、`last_focused_product` 和 query 中的序号不能在 Capability 内触发商品绑定。

文本、图片和图文：

- 三种输入都进入 ShoppingAgent；
- 纯文本使用文本召回通道；
- 纯图片使用图片向量通道；
- 图文使用融合/VL rerank 通道；
- 三种通道都返回统一 CandidateSet；
- 纯图片没有文字时不返回 `AI_SHOPPING_EMPTY_INPUT`；
- 图片不属于当前 DAG 子任务时不会污染 Shopping 工具。

Tool Guard：

- 同一轮相同推荐参数只真实执行一次；
- 第二次相同成功调用返回缓存结果并标记 `deduplicated=true`；
- 参数、图片或绑定 ID 变化时允许调用；
- 第一次失败时允许一次受控重试；
- 已完成推荐后不能再混用 Compare/Detail；
- `recursion_limit`、模型调用上限和工具调用上限能终止异常循环。

Prompt 与输入边界：

- ShoppingAgent 消息中不包含完整跨轮历史；
- Shopping Prompt 和 Tool docstring 不包含“自行消解指代、自动读取历史、从历史卡片猜商品”等职责；
- Router 已绑定信息以结构化 state 传入；
- 不相关基础偏好不会被注入为商品事实。

观测与兼容：

- 正常路径为 `dispatch_source=agent_tool_loop`；
- 受限降级为 `dispatch_source=restricted_rule_fallback`；
- 每个工具调用包含耗时、状态和去重标记；
- SSE `final → done` 顺序不变；
- 商品卡协议不变；
- 旧客户端忽略新增可选观测字段时仍能正常解析。

### 10.2 定向验证命令

```powershell
cd D:\dev\project\py\welove-shop-agt\ai-service
D:\dev\env\conda_envs\wlagt\python.exe -m pytest -q `
  tests/test_shopping_high_level_tools.py `
  tests/test_shopping_capabilities.py `
  tests/test_shopping_tools.py `
  tests/test_multimodal_retrieval_v2.py `
  tests/test_assistant_graph.py `
  tests/test_context_resolver.py

D:\dev\env\conda_envs\wlagt\python.exe -m compileall -q app tests

cd ..
git diff --check
```

如果 response adapter、chat-service 兼容字段或前端商品卡受到改动，再追加：

```powershell
mvn -pl services/chat-service -am test

cd web/welove-shop
npm run build:h5
```

### 10.3 核心真实 API 冒烟

离线测试通过后再启动真实依赖。Phase 2 核心直接冒烟至少需要：

- ai-service；
- Milvus 本地栈和正确商品 Collection；
- DashScope 文本 Embedding、图片 Embedding、Rerank/VL Rerank；
- 当前使用的 LLM 配置。

多轮 Router 商品绑定、真实 chat SSE 和登录会话验收再启动：

- PostgreSQL；
- Redis；
- Nacos；
- gateway；
- user-service；
- chat-service；
- ai-service。

本阶段不需要 trade-service，因为不开发 Agent 加购、下单或支付。

## 11. 核心验收场景

```text
1. 推荐 5 款耳机
2. 推荐 5 款耳机 → 比较这 5 款
3. 推荐 5 款耳机 → 第一款和第三款呢
4. 推荐 5 款耳机 → 第一款多少钱
5. 无商品绑定时直接问“它多少钱”
6. 纯图片找相似商品
7. 图片 + “找类似跑鞋，预算 500 元以内”
8. 纯文本“夏天出油多，推荐控油清爽的护肤品”
9. 同一轮模型两次调用相同 recommend_products 参数
10. 推荐工具首次超时后受控重试
11. 推荐成功后模型试图再次调用 compare/detail
12. 图片存在，但当前复杂任务的 Knowledge 子任务 use_image=false
```

通过标准：

- Router 只输出领域、复杂度、完整问题和实体绑定，不输出 Shopping operation；
- ShoppingAgent 自主选择推荐、比较或详情工具；
- 正常请求没有 Dispatcher 规则抢占；
- 纯文本、纯图片、图文都经过 ShoppingAgent；
- Compare/Detail 不从历史文本或卡片猜商品；
- 同参数推荐真实执行次数为 1；
- 商品卡、价格、SKU 和库存来自真实工具；
- 无法绑定商品时自然澄清；
- 工具来源、耗时、去重和降级原因可追踪；
- 没有新增无收益 LLM 调用；
- SSE 和前端商品卡保持兼容。

## 12. 风险与处理原则

### 12.1 Router 绑定质量决定 Compare/Detail 可用性

严格删除 Capability 历史兜底后，Router 绑定失败会直接暴露为澄清。这是职责收敛后的预期行为。应通过 Router 测试提升绑定质量，不能把解析职责偷偷放回 Compare/Detail。

如果用户只说商品名称但当前上下文没有可绑定 ID，Phase 2 不允许 Capability 从任意历史中猜测。可以自然澄清商品，或后续设计显式的商品定位/发现能力；不能恢复隐式历史兜底。

### 12.2 文本 LLM 不需要直接看图片

ShoppingAgent 只需知道图片存在且作用于当前任务，并选择高层推荐工具。图片像素理解、图片向量和 VL rerank 位于推荐工具内部，因此无需为统一入口强制把文本模型更换为视觉模型。

### 12.3 调用限制不能替代语义能力

Tool Guard、`recursion_limit` 和调用次数 middleware 只负责执行安全与成本控制，不得使用关键词替代 ShoppingAgent 的能力选择。

### 12.4 不用提高超时掩盖重复调用

如果请求慢，必须通过观测区分 Router、Agent 模型、检索、rerank 和重复工具调用。先消除重复调用和双路径，再评估是否需要调整外部调用超时。

## 13. Definition of Done

Phase 2 只有同时满足以下条件才算完成：

- [ ] 正常 Shopping 请求全部先进入 `create_agent`；
- [ ] `create_agent` 仅挂载高层 Shopping 工具，ShoppingAgent 是真正的 LLM Tool Agent；
- [ ] `dispatch_shopping_capability()` 不再抢占正常路径；
- [ ] Router 不决定 `recommend/compare/detail`；
- [ ] ShoppingAgent 不读取完整历史做上下文理解；
- [ ] Shopping Prompt 和高层工具 docstring 职责已收敛；
- [ ] Shopping Prompt 已包含推荐、对比、详情的 Plan-and-Execute 操作手册和 few-shot，且不向用户暴露内部计划；
- [ ] Compare/Detail 只接受 Router 绑定 ID；
- [ ] 纯文本、纯图片、图文统一进入 ShoppingAgent；
- [ ] 三种推荐输入统一输出 CandidateSet；
- [ ] 同参数推荐调用真实执行次数最多一次；
- [ ] 一个请求只执行一个主要 Shopping capability；
- [ ] `agent_tool_loop`、受限降级、去重和失败来源可观测；
- [ ] 定向测试、compileall 和 `git diff --check` 通过；
- [ ] 真实文本、图片、图文和多轮商品绑定冒烟通过；
- [ ] SSE、商品卡和现有客户端兼容；
- [ ] 用户 Review 并确认后再提交，不自动发布。
