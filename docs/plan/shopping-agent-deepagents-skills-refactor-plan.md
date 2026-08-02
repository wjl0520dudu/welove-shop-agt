# ShoppingAgent 基于 Deep Agents 与 Agent Skills 的重构方案

> 文档状态：设计完成；Phase S0 至 Phase S5 已开发，Phase S4/S5 待真实服务冒烟
>
> 适用范围：`ai-service` 内部 ShoppingAgent，不改顶层 Router、Planner、DAG、SSE 和前端商品卡协议
>
> 设计日期：2026-08-02
>
> 参考资料：桌面文档《Deep Agents API 与 Agent 构建参考指南》、LangChain Deep Agents 官方文档、Agent Skills 规范
>
> 当前代码基线：`develop`，Phase S0 提交 `83bca3d feat(ai): 完成 ShoppingAgent Deep Agents Phase S0 兼容验证`

## 1. 结论先行

当前 ShoppingAgent 适合迁移为 Deep Agents Skill 驱动，但不能简单地把现有四个高层 Tool 改名为四个 Skill，也不能把 PostgreSQL、Milvus、实时价格、库存和安全校验全部搬进 `SKILL.md` 或任意脚本。

正确的迁移目标是：

```text
Router / Planner 已交付的无指代购物任务
  → ShoppingDeepAgent
      ├─ 短小常驻 Prompt：角色、事实边界、全局安全规则
      ├─ Skills：推荐、对比、详情、个性化任务的工作方法
      ├─ Tools：查询真实商品、候选、SKU、库存、用户数据
      ├─ Scripts：字段标准化、索引校验、稳定排序、差额计算等确定性逻辑
      ├─ Tool Guard：绑定商品、重复调用、图片作用域和写操作边界
      └─ Backend：Skill 读取、临时文件和受控脚本执行
  → 保持现有 ShoppingAgent.run() 返回契约
  → 保持现有 token SSE、product_cards 和 agent_meta
```

这次改造的核心价值不是“减少所有代码”，而是把目前散落在长 Prompt、Tool docstring 和 Capability 注释里的流程知识，变成可独立发现、按需读取、单独测试和迭代的 Skills。

必须坚持以下边界：

| 内容 | 应放位置 | 原因 |
| --- | --- | --- |
| “推荐任务先召回，再判断候选，再诚实说明替代” | `discover-products/SKILL.md` | 属于任务工作方法，只在推荐时需要 |
| 商品实时价格、库存、SKU、在售状态 | Tool / Repository | 是实时事实，不能写进 Skill |
| 预算差额、候选编号校验、稳定排序 | `scripts/` 或受控 Tool | 确定性强，应可测试、可复现 |
| “不同品类不能作为替代”这类开放语义判断 | Agent LLM / Candidate Judge | 不能靠枚举全部商品词解决 |
| 只能使用 Router 绑定商品 ID | Tool Guard | 是系统执行边界，不能只靠模型自觉 |
| 用户基础标签是否与当前品类有关 | LLM 语义判断 | 例如肤质不能影响耳机推荐 |
| 跨轮指代消解和完整历史总结 | 上层 Router / Chitchat | ShoppingAgent 不应重新读取历史 |

## 2. 当前 ShoppingAgent 的真实结构

当前主链为：

```text
Router
  → ShoppingAgent.run()
      → LangChain create_agent
          → 4 个高层 Tool
              ├─ recommend_products
              │   → RecommendCapability
              │       → 文本或多模态召回
              │       → Candidate Judge LLM
              │       → 偏好软排序
              │       → 商品卡生成
              ├─ compare_products
              │   → CompareCapability
              │       → 按 Router 绑定 ID 查商品
              │       → 特征抽取
              │       → 代码选择建议
              ├─ answer_product_detail
              │   → DetailCapability
              │       → 商品与 SKU 查询
              │       → 代码识别关注点
              │       → 必要时 LLM 抽取成分特征
              └─ get_user_shopping_context
                  → UserShoppingContextCapability
      → ShoppingToolGuardMiddleware
      → 自然语言回答与 SSE
```

主要文件如下：

| 当前文件 | 当前职责 | 当前问题 |
| --- | --- | --- |
| `ai-service/app/domain/shopping/agent.py` | 创建 Agent、组装 Prompt、运行工具循环、SSE、降级 | 与 LangChain `create_agent` 强绑定；尚无 Skill Backend 和 Skill 观测 |
| `ai-service/app/prompts/prompts.py` | 保存完整 Shopping 操作手册 | `SHOPPING_AGENT_PROMPT` 过长，每轮常驻，新增能力继续膨胀 |
| `ai-service/app/domain/shopping/high_level_tools.py` | 暴露四个高层 Tool | docstring 又复制了一套完整操作手册，与 Prompt 重复 |
| `capabilities/recommend.py` | 推荐完整流水线 | 召回、Judge、卡片构造集中在一个大 Capability，难以按 Skill 组合 |
| `capabilities/compare.py` | 对比流水线 | 关注点抽取与选择建议部分仍有固定关键词/固定算法 |
| `capabilities/detail.py` | 详情流水线 | 关注点识别仍是固定分支，扩展新详情类型需改代码 |
| `relevance_judge.py` | 单次候选语义审核和偏好相关度评分 | 逻辑可复用，但它作为推荐工具内部额外 LLM 调用，需关注延迟 |
| `tool_guard.py` | 绑定 ID、主能力限制、重复调用去重、观测 | 这是正确的系统边界，应保留，不应迁入 Skill |
| `context.py` | 从 ToolRuntime 组装最小 ShoppingContext | 这是纯组装，应保留 |

### 2.1 当前最明显的扩展性问题

当前同一流程知识至少存在三份表达：

1. `SHOPPING_AGENT_PROMPT` 中的“操作手册 A/B/C”；
2. 四个高层 Tool 的 docstring；
3. Capability 内部的代码与注释。

因此新增“按套装推荐”“同类替换”“礼物推荐”“规格选择”等能力时，通常需要同时修改 Prompt、Tool docstring、Capability、Schema 和测试。模型每轮还会收到全部操作手册，即使当前只是问一个商品价格。

### 2.2 当前并不是纯 Skill Agent

现有 ShoppingAgent 是真实的 Tool Agent，因为模型会选择并调用高层工具；但它还不是 Skill 驱动 Agent：

- 所有任务流程在启动 Prompt 中常驻；
- Agent 不会先根据 Skill metadata 发现能力；
- 不会按需读取某个 `SKILL.md`；
- 没有 Skill 自带的 scripts、references 和权限边界；
- 无法独立统计某个 Skill 的激活率和成功率。

## 3. 目标架构

### 3.1 与现有多 Agent 主架构的关系

本次只替换 ShoppingAgent 内部 Harness，不新增第二套路由或第二套 Planner：

```text
resolve_context
  → Router LLM
      ├─ simple shopping
      │   → ShoppingDeepAgent
      ├─ simple knowledge
      │   → KnowledgeAgent
      ├─ simple chitchat
      │   → ChitchatAgent
      └─ complex
          → 现有 Planner LLM
          → 现有 DAG Executor
              ├─ ShoppingDeepAgent
              ├─ KnowledgeAgent
              └─ ChitchatAgent
```

Deep Agents 自带的 Subagent 和 `task` 能力第一阶段不启用。顶层系统已经有 Router、Planner 和 DAG，如果 ShoppingAgent 再自由创建 Subagent 或 Todo Planner，会形成双重编排、增加延迟，并破坏 Phase 5 已完成的任务级 SSE。

### 3.2 ShoppingDeepAgent 内部目标结构

```text
ShoppingDeepAgent Adapter
  ├─ create_deep_agent(...)
  ├─ Core system prompt
  │   ├─ 只处理当前 Shopping 子任务
  │   ├─ 事实必须来自 Tools
  │   ├─ 需要时读取最匹配 Skill
  │   └─ 不读取完整历史、不重新路由
  ├─ SkillsMiddleware
  │   ├─ discover-products
  │   ├─ compare-products
  │   ├─ inspect-product
  │   └─ use-shopping-profile
  ├─ Shopping Tools
  │   ├─ 候选召回/推荐结果
  │   ├─ 绑定商品事实查询
  │   ├─ SKU/库存查询
  │   └─ 用户基础画像查询
  ├─ Skill scripts
  │   ├─ 规范化候选
  │   ├─ 校验候选选择
  │   ├─ 稳定偏好排序
  │   └─ 构造对比矩阵/数值差额
  ├─ ShoppingToolGuard
  └─ Backend / controlled execution
```

### 3.3 一次推荐请求的目标时序

```text
用户：推荐 500 元以内、适合通勤的耳机
  → Router 已输出完整问题，领域=shopping
  → ShoppingDeepAgent 看到 Skill metadata
  → 读取 discover-products/SKILL.md
  → 按 Skill 调用真实商品候选工具
  → 依据用户问题和候选真实字段判断 exact / alternative / reject
  → 必要时执行 Skill 的确定性脚本
  → 受控终结工具验证候选编号、价格和商品存在性
  → 生成商品卡和自然回答
  → token SSE / product_cards 保持现有协议
```

Skill 读取是 Deep Agents 的渐进式加载过程，不是新的顶层业务节点，也不需要让 Router 选择具体 Shopping Skill。

## 4. Skill、Tool、Script、Reference 和 Guard 的职责

### 4.1 Skill：描述“如何完成一类任务”

Skill 应包含：

- 任务触发场景；
- 完成任务的步骤；
- 可使用的 Tool；
- 何时读取 reference；
- 何时运行 script；
- 如何处理 empty、clarify、exact、alternative；
- 输出方式与边界案例。

Skill 不应包含：

- 实时商品价格和库存；
- 数据库连接信息；
- 用户 JWT；
- 商品目录的全量枚举；
- 无限制的自然语言关键词表；
- 任意可执行 shell 指令。

### 4.2 Tool：执行真实查询或受控动作

Tool 应保持结构化输入输出，并负责：

- 调用 Milvus、PG、Repository 或既有多模态服务；
- 返回真实商品、价格、SKU、库存和来源；
- 保证用户、会话和商品访问范围；
- 返回可解释的失败状态；
- 必要时保存临时 CandidateSet 引用。

### 4.3 Script：执行稳定、确定性的重复逻辑

适合放入 script：

- 将候选字段转换成统一 JSON 结构；
- 去重并保持原始召回顺序；
- 校验模型只能选择已有候选编号；
- 校验 compare/detail 只能使用绑定 ID；
- 计算预算差额、价格区间和库存合计；
- 在 LLM 已输出偏好相关度分数后做稳定排序；
- 生成对比矩阵的基础行列结构。

不适合放入 script：

- 判断所有开放语言条件是否满足；
- 通过关键词表判断“耳机”“咖啡机”“跑鞋”等所有品类；
- 自由连接 PostgreSQL 或 Milvus；
- 自由访问网络；
- 自由读取其他用户会话文件。

### 4.4 Reference：保存按需加载的详细契约

Reference 用于保存详细但不是每次都需要的资料，例如：

- 候选输入输出 Schema；
- exact / alternative / reject 示例；
- 商品事实字段说明；
- 多模态召回通道说明；
- 推荐话术边界；
- 对比维度与缺失字段处理；
- 基础偏好参与软排序的规则。

### 4.5 Tool Guard：保存不可协商的执行边界

现有 `ShoppingToolGuardMiddleware` 应继续保留：

- Compare/Detail 只能使用 Router 绑定 ID；
- 一轮最多一个主要 Shopping capability；
- 相同参数工具调用去重；
- 图片只能作用于当前允许的任务；
- 工具执行记录可观测；
- 不允许未授权写操作。

Skill 是模型可读的工作说明，不是安全机制。即使 `SKILL.md` 写了“不要编造 ID”，服务端仍必须验证 ID。

## 5. 推荐 Skill 目录

### 5.1 按 Agent 建立 Skill 命名空间

`skills/` 不应直接平铺所有领域的 Skill。当前虽然只改造 ShoppingAgent，但未来 KnowledgeAgent、ChitchatAgent 或其他领域 Agent 也可能接入 Deep Agents，因此应先按 Agent 划分 Skill 根目录，再在对应 Agent 目录下放具体 Skill。

推荐总体结构：

```text
ai-service/
├── skills/
│   ├── shopping-agent/       # ShoppingAgent 专属 Skill source
│   ├── knowledge-agent/      # KnowledgeAgent 未来的专属 Skill source
│   ├── chitchat-agent/       # ChitchatAgent 未来的专属 Skill source
│   └── shared/               # 经过确认、真正跨 Agent 复用的 Skill
└── app/
```

`shopping-agent/`、`knowledge-agent/` 和 `chitchat-agent/` 是 Skill source/命名空间，本身不放 `SKILL.md`。它们下面的 `discover-products/`、`search-store-knowledge/` 等目录才是符合 Agent Skills 规范的具体 Skill。

各 Agent 默认只加载自己的 Skill source：

```python
shopping_agent_skills = ["/skills/shopping-agent/"]
knowledge_agent_skills = ["/skills/knowledge-agent/"]
chitchat_agent_skills = ["/skills/chitchat-agent/"]
```

这样可以避免 ShoppingAgent 看到 KnowledgeAgent 的知识检索 Skill，也避免不同领域 description 相似时发生错误激活。

### 5.2 ShoppingAgent Skill 目录

ShoppingAgent 的具体目录建议为：

```text
ai-service/
├── skills/
│   ├── shopping-agent/
│   │   ├── discover-products/
│   │   │   ├── SKILL.md
│   │   │   ├── scripts/
│   │   │   │   ├── normalize-candidates.py
│   │   │   │   ├── validate-selection.py
│   │   │   │   └── sort-by-preference.py
│   │   │   └── references/
│   │   │       ├── candidate-contract.md
│   │   │       ├── candidate-judging.md
│   │   │       ├── multimodal-input.md
│   │   │       └── recommendation-output.md
│   │   ├── compare-products/
│   │   │   ├── SKILL.md
│   │   │   ├── scripts/
│   │   │   │   ├── build-comparison-matrix.py
│   │   │   │   └── normalize-units.py
│   │   │   └── references/
│   │   │       ├── comparison-contract.md
│   │   │       └── missing-facts.md
│   │   ├── inspect-product/
│   │   │   ├── SKILL.md
│   │   │   ├── scripts/
│   │   │   │   └── summarize-sku-facts.py
│   │   │   └── references/
│   │   │       ├── product-facts.md
│   │   │       └── detail-boundaries.md
│   │   └── use-shopping-profile/
│   │       ├── SKILL.md
│   │       └── references/
│   │           ├── profile-fields.md
│   │           └── preference-isolation.md
│   ├── knowledge-agent/
│   │   └── ...
│   ├── chitchat-agent/
│   │   └── ...
│   └── shared/
│       └── ...
└── app/
```

### 5.3 Shared Skill 的使用规则

只有以下条件同时满足时，才把 Skill 放进 `shared/`：

- 至少两个 Agent 确实使用同一套完整工作方法；
- Tool 和数据权限边界在两个 Agent 中一致；
- Skill 的 description 不会让无关 Agent 误激活；
- 共享不会导致 Agent 获得不属于自身职责的能力。

需要共享时，由对应 Agent 显式加载，而不是让所有 Agent 默认看到全部 shared Skills：

```python
shopping_agent_skills = [
    "/skills/shared/",
    "/skills/shopping-agent/",
]
```

Deep Agents 的多个 Skill source 按顺序加载，后面的同名 Skill 可能覆盖前面的同名 Skill。应尽量避免 shared 与领域目录出现同名 Skill；确需覆盖时，领域专属 source 放在后面，并增加覆盖测试。

### 5.4 不推荐的拆分方式

不建议采用以下目录：

```text
skills/
├── recommend-products-tool/
├── compare-products-tool/
├── query-price-tool/
├── query-stock-tool/
└── image-search-tool/
```

原因是这会把原子函数误当成 Skill，导致 Skill 数量膨胀、description 重叠、模型读错 Skill。Skill 应对应一套完整、可复用的任务方法。

## 6. 各 Skill 的详细设计

### 6.1 `discover-products`

#### 触发范围

- 推荐、查找、筛选新商品；
- 带预算、品牌、场景、肤质、偏好或避雷条件；
- 纯文本、纯图片和图文找相似商品；
- 找不到精确商品时需要同类诚实替代。

#### 不触发范围

- 已绑定多个商品的比较；
- 已绑定单个商品的事实追问；
- 普通知识解释；
- 加购、下单和支付。

#### 建议 frontmatter

```yaml
---
name: discover-products
description: >-
  Discover and recommend real products from the current store for text, image,
  or multimodal shopping requests. Use when the user wants to find, choose, or
  filter new products by product type, budget, brand, scenario, preferences,
  skin type, exclusions, or a reference image, including honest same-type
  alternatives when exact matches are unavailable.
---
```

#### SKILL.md 核心流程

```text
1. 使用 Router 交付的当前完整问题，不读取完整历史。
2. 根据输入模式调用唯一的候选召回 Tool；不要自行选择向量库或 Collection。
3. 若候选为空，直接返回真实 empty，不创造替代商品。
4. 若候选非空，根据用户完整问题与候选真实字段进行一次语义判断：
   - exact：商品类型和明确条件满足；
   - alternative：商品类型一致，但部分附加条件不满足；
   - reject：商品类型不一致或明显无关。
5. 当前请求命中与长期基础偏好分开判断：
   - 偏好不得改变 exact / alternative / reject；
   - 只有偏好与当前品类有关时才给偏好相关度分数。
6. 使用候选编号提交最终选择；不得生成任意商品 ID。
7. 有 exact 时只展示 exact；没有 exact 但有同类候选时展示 alternative 并说明差距；
   候选中没有目标品类时才返回 empty。
8. 基于终结 Tool 返回的卡片和事实生成自然回答，不重复检索。
```

#### 可用 Tool

第一阶段可以继续使用现有 `recommend_products`，完成 Skill 化后再逐步拆为：

| 目标 Tool | 职责 |
| --- | --- |
| `search_product_candidates` | 统一执行文本、纯图或图文召回，返回有限 CandidateSet |
| `get_candidate_facts` | 必要时补齐候选真实字段，不做开放语义判断 |
| `finalize_product_recommendation` | 校验候选编号和事实，生成 ranked_products 与 product_cards |
| `get_user_shopping_context` | 仅在用户明确要求个人数据时读取基础画像 |

#### 可执行 scripts

| Script | 输入 | 输出 | 是否每轮必跑 |
| --- | --- | --- | --- |
| `normalize-candidates.py` | CandidateSet JSON | 有界、统一字段候选 JSON | 候选字段不统一时运行 |
| `validate-selection.py` | 候选与模型选择 | 合法选择或明确错误 | 最终提交前运行或由 Tool 内部复用 |
| `sort-by-preference.py` | 已命中的商品和偏好分数 | 稳定排序结果 | 偏好与品类相关且候选大于 1 时运行 |

这些 script 不负责访问数据库，也不负责判断自然语言品类。

### 6.2 `compare-products`

#### 触发范围

- 比较两个或更多 Router 已绑定商品；
- 在已有商品中选一个；
- 按价格、规格、使用场景、优缺点或性价比比较。

#### 建议 frontmatter

```yaml
---
name: compare-products
description: >-
  Compare two or more products already bound by the Router, explain factual
  differences and trade-offs, and recommend among those products for the
  user's stated scenario. Use only when multiple concrete products are already
  identified; do not use it to discover new products.
---
```

#### SKILL.md 核心流程

```text
1. 只使用 Router 已绑定的有序商品 ID。
2. 商品少于两个时自然澄清，不从历史文本或任意卡片猜测。
3. 调用事实 Tool 一次加载同一活动商品源的数据。
4. 优先比较用户明确关心的维度；未指定时选择当前商品共同可验证的关键维度。
5. 缺失字段标为未知，不把营销描述写成可验证参数。
6. 必要时运行单位规范化和对比矩阵脚本。
7. 解释差异和取舍；推荐结论只能在已绑定商品中选择。
8. 不重新调用推荐工具扩大商品集合。
```

#### 可用 Tool 和 Script

| 类型 | 名称 | 职责 |
| --- | --- | --- |
| Tool | `load_bound_product_facts` | 按绑定 ID 读取商品、SKU 和可比较字段 |
| Tool | `extract_product_evidence` | 对非结构化描述做受控特征抽取，可复用现有 LLM 特征抽取 |
| Script | `normalize-units.py` | 统一重量、容量、时长和价格单位 |
| Script | `build-comparison-matrix.py` | 根据事实生成稳定对比矩阵，不做开放语义推荐 |

现有 `_FOCUS_MAP` 和 `_pick_best_by_focus` 不应继续无限扩充关键词。Skill 负责告诉 Agent 如何理解比较目标，代码只负责可验证的数据计算。

### 6.3 `inspect-product`

#### 触发范围

- 已绑定单个商品的价格、库存、SKU、规格、成分和适用性追问；
- 用户要求解释该商品的一个具体事实。

#### 建议 frontmatter

```yaml
---
name: inspect-product
description: >-
  Answer factual follow-up questions about one concrete product already bound
  by the Router, including current price, stock, SKU options, specifications,
  ingredients, and suitability. Use only for a uniquely identified product;
  otherwise ask which product the user means.
---
```

#### SKILL.md 核心流程

```text
1. 只消费唯一的 Router 绑定商品 ID。
2. 如果没有唯一商品，直接澄清，不自行消解“它”“第一款”。
3. 调用商品事实 Tool 获取实时商品和 SKU 数据。
4. 根据用户问题选择需要回答的事实，而不是依赖固定关键词穷举所有问法。
5. 实时价格、库存和 SKU 只引用 Tool 结果。
6. 适用性可以基于真实字段进行解释，但必须区分事实和推断。
7. 缺少字段时明确说无法确认，不改调推荐或比较工具。
```

#### 可用 Tool 和 Script

| 类型 | 名称 | 职责 |
| --- | --- | --- |
| Tool | `get_bound_product_detail` | 获取唯一绑定商品的实时事实 |
| Tool | `extract_product_evidence` | 必要时从商品描述中抽取成分、材质、适用场景等证据 |
| Script | `summarize-sku-facts.py` | 计算 SKU 数量、价格区间、总库存和默认规格 |

### 6.4 `use-shopping-profile`

这是辅助 Skill，不应与推荐、对比或详情争夺主任务。

#### 触发范围

- “按我的肤质推荐”；
- “根据我喜欢的推荐”；
- “参考我收藏、浏览或买过的商品”；
- 用户明确要求使用个人画像。

#### 核心边界

```text
1. 只有用户明确要求时读取个人数据 Tool。
2. 基础标签是软信号，不是商品事实，也不是硬过滤条件。
3. 先判断偏好是否与当前商品领域相关。
4. 肤质可影响护肤、美妆等相关任务，不得影响耳机、电脑或跑鞋。
5. 当前明确需求优先于基础偏好。
6. 长期行为偏好、自动偏好事实和自动 Proposal 继续关闭。
```

`use-shopping-profile` 可以与 `discover-products` 同轮加载，但不单独完成推荐任务。

## 7. Tool 重构策略

### 7.1 第一阶段：先 Skill 化，不立即拆毁已验收 Capability

第一阶段保留现有四个高层 Tool：

```text
recommend_products
compare_products
answer_product_detail
get_user_shopping_context
```

但做以下变化：

- `SHOPPING_AGENT_PROMPT` 缩短为核心角色和全局边界；
- 操作手册迁入对应 `SKILL.md`；
- Tool docstring 只保留用途、输入、输出和事实边界，不再复制五步手册；
- DeepAgent 根据 Skill metadata 选择并读取 Skill；
- 继续复用现有 Capability、Judge、Retriever、Tool Guard 和商品卡协议。

这一阶段能最快验证：Skill 是否正确激活、Prompt token 是否下降、功能是否回归。

### 7.2 第二阶段：把“大高层 Tool”拆成可组合的窄 Tool

当第一阶段稳定后，再逐步拆分：

| 当前大 Tool | 目标组合 |
| --- | --- |
| `recommend_products` | `search_product_candidates` + Agent 语义判断 + `finalize_product_recommendation` |
| `compare_products` | `load_bound_product_facts` + 可选特征抽取 + 对比 Script |
| `answer_product_detail` | `load_bound_product_facts(purpose=detail)` + 可选 SKU Script |
| `get_user_shopping_context` | 保留为窄 Tool，按授权读取基础画像 |

拆分的目的不是让 Agent 自由乱调更多工具，而是让 Skill 能组合稳定步骤，同时把每个 Tool 的输入输出变得清楚、可验证。

### 7.3 Candidate Judge 的迁移选择

当前 `recommend_products` 内部会额外调用一次 `relevance_judge.py`。迁移时有两种方案：

#### 方案 A：第一阶段继续复用现有 Judge

优点：

- 风险最低；
- exact / alternative / reject 和偏好软排序行为保持不变；
- 便于先单独评估 Skill 激活。

缺点：

- DeepAgent 读取 Skill 会增加一次模型循环；
- 推荐链仍有额外 Judge LLM，延迟可能增加。

#### 方案 B：稳定后由 ShoppingDeepAgent 自身完成候选语义判断

流程为：

```text
Agent 读取 discover-products Skill
  → search_product_candidates
  → 同一个 Agent 根据 Skill 生成候选编号、verdict、差距和偏好分数
  → finalize_product_recommendation
  → 服务端验证并生成卡片
```

优点：减少独立 Judge 模型实例的重复理解；Skill 的判断方法可独立迭代。

缺点：需要新增结构化终结 Tool，并处理流式回答与结构化决策的边界。

建议先采用方案 A 完成安全迁移，建立真实延迟基线后，再单独实施方案 B。不要在第一次接入 Deep Agents 时同时改 Skill、工具粒度和 Judge，避免无法判断回归来源。

## 8. Script 执行方案

### 8.1 “能执行 scripts”不等于开放任意 shell

Deep Agents 通过 Backend 的 `execute` 能力运行 Skill 脚本，但 `ai-service` 是对外 HTTP 服务，不能让模型直接在宿主机上自由执行命令。

生产环境必须满足：

- 只能执行仓库内已发布、已审核的 Shopping Skill scripts；
- 禁止执行用户上传脚本；
- 禁止读取 `.env`、密钥、其他用户工作目录；
- 限制 CPU、内存、执行时长和输出大小；
- 默认无网络；
- 脚本不能直接持有 PG、Milvus 或外部 API 凭据；
- 所有真实数据仍通过受控 Tool 获取。

### 8.2 推荐的两级实现

#### V1：受控脚本执行 Tool

新增一个窄的内部 Tool，例如：

```text
run_shopping_skill_script(
  skill_name,
  script_name,
  input_ref,
  output_ref
)
```

服务端使用白名单映射，只允许：

```text
discover-products/normalize-candidates.py
discover-products/validate-selection.py
discover-products/sort-by-preference.py
compare-products/normalize-units.py
compare-products/build-comparison-matrix.py
inspect-product/summarize-sku-facts.py
```

优点：实现简单、延迟可控、适合先上线；不会给模型通用 shell。

#### V2：Sandbox Backend 直接执行

当需要动态增加 Skill scripts 或使用 Deep Agents 标准 `execute` 时，迁移到隔离 Sandbox：

```text
/skills/shopping-agent/**  只读
/workspace/<run_id>/**  当前请求可读写
/secrets/**             完全不可见
网络                     默认关闭
命令                     只允许 Python + 指定脚本路径
```

Sandbox 应使用池化或长生命周期实例，避免每个请求冷启动一个容器导致导购延迟明显上升。

### 8.3 Script 接口约定

所有脚本建议遵守：

```text
输入：UTF-8 JSON 文件
输出：UTF-8 JSON 文件
标准输出：只写简短观测信息
标准错误：写明确错误原因
退出码：0 成功，非 0 失败
超时：默认 1 秒，复杂批处理不超过 3 秒
幂等：相同输入得到相同输出
```

脚本失败不能让 Agent 自由猜结果。应返回明确的 script error，由 Skill 指示 Agent 使用原始事实继续或给出保守回答。

## 9. Backend 设计

### 9.1 本地开发

本地只验证 Skill 发现和读取时，可使用：

```python
FilesystemBackend(root_dir=AI_SERVICE_ROOT, virtual_mode=True)
```

但 `virtual_mode=True` 只限制虚拟路径，不是进程隔离。它不适合直接作为生产 HTTP 服务的任意执行环境。

### 9.2 生产建议

建议使用 Composite 或自定义 Backend 分区：

```text
/skills/shopping-agent/  → ShoppingAgent 只读 Skill Store
/skills/shared/          → 仅显式授权给 ShoppingAgent 的共享 Skill
/workspace/              → 当前 run 的临时 State/Sandbox Backend
/memories/               → 本次不开放给 ShoppingAgent
/conversation/           → 本次不开放给 ShoppingAgent
```

ShoppingAgent 的跨轮上下文仍由上层 Router 处理。不要因为 Deep Agents 提供 Memory，就让 ShoppingAgent 重新读取完整聊天历史，否则会恢复之前已经收敛掉的重复上下文解析问题。

### 9.3 权限原则

- `read /skills/shopping-agent/**`：允许；
- `read /skills/shared/**`：仅对显式配置的共享 Skill 允许；
- `write /skills/**`：拒绝；
- `read/write /workspace/<run_id>/**`：允许当前请求；
- `read/write /**/.env*`：拒绝；
- `read /conversation/**`：拒绝；
- `execute /skills/shopping-agent/**/scripts/*.py`：仅白名单或 Sandbox；
- 其他执行：拒绝。

## 10. ShoppingDeepAgent Adapter 设计

### 10.1 保持外部契约不变

现有调用方继续使用：

```python
await shopping_agent.run(
    question=question,
    messages=messages,
    business_memory=business_memory,
    conversation_id=conversation_id,
    user_id=user_id,
    jwt_token=jwt_token,
    selected_product_ids=selected_product_ids,
    image_url=image_url,
    input_mode=input_mode,
    token_sink=token_sink,
)
```

返回继续兼容：

```text
answer
product_cards
task_type=shopping
sources
tool_calls
suggested_questions
capability
dispatch_source
model_call_count
error / error_code / message
```

Router、Planner、DAG 和 `assistant/nodes.py` 不需要知道内部从 `create_agent` 切换到了 `create_deep_agent`。

### 10.2 建议新增 Adapter 文件

```text
ai-service/app/domain/shopping/deep_agent.py
```

职责：

- 创建并缓存 DeepAgent 图；
- 注入 model、skills、tools、backend 和 middleware；
- 把当前请求转成 DeepAgent state；
- 过滤 `read_file`、script、Tool 等内部事件；
- 只把模型可见文本通过 `token_sink` 发给前端；
- 从 ToolResult 提取 product_cards；
- 生成与当前 ShoppingAgent 一致的返回 dict；
- 记录 Skill 读取和脚本执行观测。

`agent.py` 可以保留为稳定门面，根据开关选择旧 Agent 或 DeepAgent Adapter。

### 10.3 组装示意

以下代码只表达结构，正式编码时需以锁定的 Deep Agents 版本 API 为准：

```python
from deepagents import create_deep_agent

deep_agent = create_deep_agent(
    model=self._llm,
    system_prompt=SHOPPING_AGENT_CORE_PROMPT,
    tools=shopping_tools,
    skills=["/skills/shopping-agent/"],
    backend=shopping_backend,
    middleware=[
        shopping_tool_guard,
        model_call_limit,
        tool_call_limit,
    ],
    checkpointer=shopping_checkpointer,
    name="shopping-deep-agent",
)
```

需要通过当前锁定版本支持的 Harness/Profile 或 Middleware 工具 allowlist，排除第一阶段不需要的能力：

- `task`；
- `write_todos`；
- `write_file` / `edit_file`；
- 通用 `execute`，除非已接 Sandbox；
- 其他与 Shopping 请求无关的文件工具。

保留 `read_file`，因为 Skill Level 2 加载依赖它。

## 11. 常驻 Prompt 的目标

迁移后 `SHOPPING_AGENT_PROMPT` 应缩短为类似：

```text
你是微爱商城 ShoppingAgent，只处理 Router 已交付的当前商品任务。

- 根据任务读取最匹配的 Shopping Skill，并按 Skill 使用真实商品工具。
- 商品、价格、库存、SKU 和在售状态只能来自工具结果。
- 不读取完整会话历史，不重新消解指代，不重新判断顶层领域。
- Compare/Detail 只能使用 Router 已绑定商品。
- 不向用户暴露 Skill、Tool、脚本、Agent 或内部字段。
- 完成一个主要商品任务后直接自然回答，不重复执行无收益查询。
```

以下内容应从常驻 Prompt 删除并迁入 Skills：

- 推荐操作手册 A；
- 比较操作手册 B；
- 详情操作手册 C；
- 每种任务的大量 few-shot；
- ToolResult 每个字段的详细消费说明；
- 多模态内部召回步骤；
- 候选 Judge 的 exact / alternative 详细示例。

## 12. 上下文、Memory 与偏好边界

### 12.1 ShoppingAgent 仍然不读取完整历史

Deep Agents 的 Memory 能力不应在这里直接加载聊天记录。ShoppingAgent 输入继续限制为：

- Router 已整理的完整当前问题；
- Router 已绑定商品 ID；
- 当前图片和 input_mode；
- 必要的依赖任务 Artifact；
- 基础偏好软信号；
- 用户和会话身份，仅用于 Tool 权限。

### 12.2 Skill 不是用户长期记忆

Skill 是商城导购的工作方法，不是某个用户的画像。基础偏好仍来自现有用户数据或 `business_memory`，并由 Tool/Context 注入。

### 12.3 偏好仍遵循当前已确认原则

```text
当前问题是否命中商品
  与
基础偏好是否更相关
```

是两个独立判断：

- 先确定 exact / alternative / reject；
- 再给已命中候选做偏好相关度评分；
- 代码只对已命中候选稳定排序；
- 偏好分低不能把正确商品直接删除；
- 无关领域偏好不得参与排序。

## 13. 流式输出与事件观测

### 13.1 用户 SSE 保持不变

Deep Agents 会产生多类内部事件：

- 模型消息；
- `read_file`；
- Tool 调用；
- Script 执行；
- Middleware 状态。

这些不能原样暴露到用户界面。Adapter 只转发最终自然回答的文本 token，继续保持现有：

```text
token...
product_cards
final
done
```

复杂任务仍由现有 DAG 按任务顺序流式输出，不让 DeepAgent 自己创建子任务流。

### 13.2 agent_meta 新增安全观测字段

可以新增可选内部字段：

```json
{
  "shopping_runtime": "deep_agent",
  "skill_reads": ["discover-products"],
  "skill_scripts": ["sort-by-preference.py"],
  "tool_call_count": 2,
  "model_call_count": 3,
  "backend_type": "shopping_sandbox",
  "fallback_stage": null
}
```

不得保存：

- 完整 system prompt；
- 完整 SKILL.md 正文；
- JWT；
- 其他用户数据；
- Sandbox 内部绝对路径；
- 模型隐式推理过程。

## 14. 依赖与 requirements.txt 计划

截至 2026-08-02，PyPI 当前 `deepagents` 最新版本为 `0.7.1`，要求 Python `>=3.11,<4.0`，并要求较新的 LangChain 1.x。

当前 `ai-service/requirements.txt` 中：

```text
langchain>=0.1.11
langchain-core>=0.1.30
langgraph>=0.2.0
pydantic>=1.10.0
langsmith>=0.9.0
```

这些下限不能表达 Deep Agents 0.7.1 的真实兼容范围。实施时不能只追加一行无上限的 `deepagents`，建议统一调整为：

```text
# Deep Agents 0.7.1 requires Python >=3.11.
deepagents==0.7.1
langchain>=1.3.14,<2.0.0
langchain-core>=1.5.0,<2.0.0
langgraph>=1.2.5,<1.3.0
langsmith>=0.10.9
pydantic>=2.7.4,<3.0.0
```

说明：

- `deepagents==0.7.1` 建议精确锁定，避免快速迭代导致 API 漂移；
- `langgraph>=1.2.5,<1.3.0` 来自当前 LangChain 1.3.14 的兼容范围；
- 当前代码已使用 `model_dump()` 等 Pydantic v2 API，应显式收敛到 Pydantic 2；
- Sandbox 具体依赖等 Backend 选型确定后再追加，不提前安装无用 Provider；
- 用户负责执行安装，本方案实施时只修改 `requirements.txt` 和必要说明，不自动安装。

实施前必须先确认实际运行 Python 版本。当前终端的 `python.exe` 是 Windows App Alias，无法从本次会话确认真实虚拟环境版本；若生产环境低于 Python 3.11，需要先升级运行时。

## 15. 配置开关与回滚

新增：

```text
SHOPPING_DEEP_AGENT_ENABLED=true
SHOPPING_SKILLS_ROOT=/skills/shopping-agent
SHOPPING_SKILL_SCRIPT_MODE=disabled|controlled|sandbox
SHOPPING_SKILL_SCRIPT_TIMEOUT_SECONDS=2
```

开关策略：

| 配置 | 行为 |
| --- | --- |
| `false` | 使用当前 ShoppingAgent，作为发布期人工回滚路径 |
| `true` | 使用 ShoppingDeepAgent + Skills |
| `script_mode=disabled` | 只验证 Skill 读取，仍使用现有 Capability |
| `script_mode=controlled` | 使用受控白名单脚本 Tool |
| `script_mode=sandbox` | 使用隔离 Backend 的标准 execute |

新架构运行失败时不应在同一请求中悄悄切回旧 Agent 再执行一次商品查询，否则可能重复召回、重复模型调用并造成不可预测延迟。回滚开关用于发布和人工切换；单次请求失败应返回明确错误或受限事实降级。

## 16. 分阶段开发计划

### Phase S0：依赖与最小可运行验证

目标：确认 Deep Agents 版本和当前模型、Middleware、异步流兼容。

工作项：

- 更新 `requirements.txt` 兼容范围；
- 新增最小 `create_deep_agent` 集成测试；
- 验证现有 `get_llm()` 返回模型支持 Tool Calling；
- 验证 `ainvoke`、`astream`、checkpointer 和 request state；
- 验证现有 `ShoppingToolGuardMiddleware` 是否可直接复用；
- 记录 DeepAgent 默认工具清单，排除 `task`、Todo 和写文件能力；
- 不接真实商品链路。

完成标准：一个测试 Skill 能被发现、读取，测试 Tool 能被调用，模型 token 能被 Adapter 捕获。

#### Phase S0 实现记录（2026-08-02）

已完成：

- `requirements.txt` 锁定 `deepagents==0.7.1`，并收敛 LangChain、LangGraph、LangSmith 和 Pydantic 的兼容范围；
- 新增 `deep_agent_runtime.py`，提供 Deep Agents 精确版本检查；
- 新增 ShoppingAgent 专用工具面 Middleware，只向模型暴露 `read_file` 和显式 Shopping 业务工具；
- 新增只读 Skill 权限：允许读取 `/skills/shopping-agent/**`，拒绝其他读取和所有写入；
- 验证 Deep Agents 0.7.1 在 `FilesystemBackend` 下原始工具面包含 `ls`、`read_file`、`write_file`、`edit_file`、`delete`、`glob`、`grep` 和 `task`；普通文件 Backend 不提供 `execute`；
- 修复 `RequireInitialShoppingToolMiddleware` 与 Skill 读取的兼容问题：`read_file` 的 ToolMessage 不再被误认为已经取得商品事实；
- 验证 Skill metadata 能注入 system context，Agent 能读取测试 `SKILL.md`；
- 验证测试业务 Tool 能读取 `conversation_id` 和 Router 绑定商品 ID；
- 验证 `ainvoke`、`astream`、`InMemorySaver` 和模型消息流；
- 验证现有 `ShoppingToolGuardMiddleware` 在 Skill 读取后仍能对相同业务 Tool 参数去重；
- 验证当前 `get_llm()` 返回 `ChatOpenAI`，并可正常执行 `bind_tools()`。

离线结果：

```text
29 passed
python -m compileall -q app tests：通过
Deep Agents：0.7.1
Python：3.12.13
```

环境说明：当前虚拟环境存在一个与本项目 requirements 无关的既有告警：未被项目代码引用的 `langchain-experimental==0.4.2` 要求 `langchain-community>=0.4.2`，环境中实际为 `0.3.31`。项目代码未引用 `langchain-experimental`，当前 Deep Agents、Shopping 定向测试和 Tool Calling 均正常；本阶段未擅自升级或卸载用户虚拟环境中的无关包。

### Phase S1：建立 Skill 目录与 DeepAgent Adapter

目标：完成运行时骨架，不改变业务结果。

工作项：

- 新增 `ai-service/skills/shopping-agent/`，并预留其他 Agent 与 `shared/` 命名空间；
- 使用标准 Skill 初始化和校验脚本创建四个 Skill；
- 新增 `deep_agent.py` Adapter；
- 新增 Backend factory；
- 新增 `SHOPPING_DEEP_AGENT_ENABLED`；
- 保持 `ShoppingAgent.run()` 输入输出不变；
- 保持现有四个高层 Tool 和 Capability；
- 增加 Skill read 观测。

完成标准：开启开关后，推荐、对比、详情分别读取正确 Skill，并仍能返回现有结构。

#### Phase S1 实现记录（2026-08-02）

已完成：

- 建立 `ai-service/skills/` Agent 命名空间，ShoppingAgent 下创建
  `discover-products`、`compare-products`、`inspect-product`、`use-shopping-profile`
  四个标准 Skill，并预留 `knowledge-agent`、`chitchat-agent`、`shared`；
- 使用 Skill Creator 标准初始化器确认目录模板，四个正式 `SKILL.md` 均通过
  `quick_validate.py` 校验；
- 新增 `ShoppingDeepAgentAdapter`，使用 `create_deep_agent`、现有四个高层商品 Tool、
  `ShoppingAgentState`、独立 checkpointer 和现有 Tool Guard；
- 新增只读 `FilesystemBackend` 工厂，将虚拟路径 `/skills/shopping-agent/` 映射到
  `ai-service/skills/shopping-agent/`，并拒绝配置为其他 Agent 或应用目录；
- 新增双轨开关 `SHOPPING_DEEP_AGENT_ENABLED=true` 和
  `SHOPPING_SKILLS_ROOT=/skills/shopping-agent/`，默认使用 DeepAgent Skill 运行时；
  设置为 `false` 时人工回滚到现有 LangChain Agent；
- 保持 `ShoppingAgent.run()` 参数、商品卡、Capability、`dispatch_source=agent_tool_loop`
  和 token SSE 路径不变；DeepAgent 正常链路不回调旧 Agent；
- DeepAgent 仅向模型暴露 `read_file` 与四个高层业务 Tool，继续隐藏写文件、Shell、
  SubAgent、Todo 和通用文件检索能力；
- `read_file` 不再进入业务 Tool Guard 记录和对外 `tool_calls`，新增
  `shopping_runtime`、`skill_reads` 安全观测字段，只记录运行时名称与 Skill 名称；
- DeepAgent 的 Tool/Model 调用仍分别受 4 次和 6 次硬上限约束；图步数预算调整为 40，
  用于容纳 Skill 与文件中间件节点，不放宽业务工具循环边界；
- 推荐、对比、详情分别验证读取对应 Skill；明确个性化推荐验证可先读取
  `use-shopping-profile`，再读取 `discover-products`，并仍只执行允许的业务工具。

离线结果：

```text
Skill quick_validate：4/4 通过
Phase S0/S1、Phase 2、High-level Tools、Tool Guard、SSE：41 passed
Recommend、Candidate Judge、输入模式、多模态、Assistant Graph：44 passed
合并定向回归：85 passed
python -m compileall -q app tests：通过
git diff --check：通过
```

本阶段没有启动 PostgreSQL、Redis、Milvus 或真实 AI Service，也没有执行真实模型
Skill 激活冒烟；运行配置已默认开启，可通过 `SHOPPING_DEEP_AGENT_ENABLED=false`
人工回滚到现有 LangChain Agent。

### Phase S2：删除常驻长操作手册

目标：真正降低 Prompt 膨胀和重复维护。

实现状态：已完成。

工作项：

- 将操作手册 A/B/C 迁入 Skills；
- 将候选判断示例迁入 `candidate-judging.md`；
- 缩短 `SHOPPING_AGENT_PROMPT`；
- 缩短 Tool docstring；
- 保留参数和返回 Schema；
- 对比迁移前后 Prompt token。

完成标准：不读取 Skill 时，Shopping 常驻 Prompt 不再包含所有能力的完整流程；相关任务会按需读取对应 Skill。

实际实现：

- 推荐、比较、详情和画像的完整工作方法已迁入各自 `SKILL.md`；
- 候选 `exact / alternative / empty`、诚实替代和基础偏好软排序示例已迁入
  `discover-products/references/candidate-judging.md`；
- `SHOPPING_AGENT_PROMPT` 从迁移前 4238 字符缩短到 617 字符，减少约 85.4%；
- DeepAgent 专属 Skill 使用契约为 243 字符，默认运行时合计 862 字符，仍比迁移前减少约 79.7%；
- 四个高层 Tool docstring 仅保留用途边界、参数和返回结构，不再复制固定执行闭环和 Few-shot；
- 新增 `RequireMatchingShoppingSkillMiddleware`：模型仍自主选择 Skill 和业务工具，代码只校验
  工具与已读取 Skill 的能力契约，不解析用户自然语言；
- 未读取或读取错误 Skill 时，业务 Tool 不会真实执行，模型可读取正确 Skill 后在同一轮恢复；
- `read_file` 和被 Skill 契约拦截的调用不进入对外 Shopping 业务 `tool_calls`。

离线验证：

```text
Phase S2 首轮定向测试：28 passed
Shopping / Judge / 多模态 / SSE / 主图合并回归：93 passed
四个 Skill quick_validate：全部通过
```

本阶段未自动重启或停止 AI Service。真实模型验收前需要由用户手动重启 AI Service，
再确认 `shopping_runtime=deep_agent` 且 `skill_reads` 能按任务显示对应 Skill。

### Phase S3：接入受控 scripts

目标：让 Skill 能使用确定性脚本，但不开放宿主机 shell。

实现状态：已完成。

工作项：

- 实现候选标准化、选择校验、偏好稳定排序脚本；
- 实现对比矩阵和 SKU 汇总脚本；
- 新增白名单 script runner；
- 限制路径、超时、输入输出大小；
- 单测所有 script；
- 增加 script trace。

完成标准：Agent 按 Skill 只在需要时运行对应脚本；脚本失败不会产生虚假商品事实。

实际实现：

- `discover-products` 新增候选字段标准化、候选编号原子校验和基础偏好稳定排序脚本；
- `compare-products` 新增单位标准化和显式维度比较矩阵脚本；
- `inspect-product` 新增真实 SKU 价格、库存和规格汇总脚本；
- 新增 `run_shopping_skill_script` 窄 Tool，只接受 `skill_name`、白名单 `script_name`
  和有限 JSON `payload`，不接受路径、命令、输入输出文件或任意 Python 代码；
- Runner 使用固定 `sys.executable -I -S <reviewed-script>` 参数并通过 `subprocess.run`
  执行，不经过 Shell；异步 Agent 通过线程等待，兼容 Windows SelectorEventLoop；
- Runner 在执行前使用 AST 限制 imports 和动态执行/文件调用，子进程只获得最小环境变量，
  不继承 API Key、数据库密码和业务配置；
- 输入上限 64 KiB、输出上限 128 KiB，默认超时 2 秒；未知脚本、越界路径、超时、
  非 JSON 输出和未审核 import 均返回稳定错误码；
- Script Tool 只有 `SHOPPING_SKILL_SCRIPT_MODE=controlled` 时才进入 DeepAgent 工具面，
  `disabled` 模式不暴露该工具，通用 `execute` 和 Shell 继续隐藏；
- Skill Guard 要求 script 声明的 `skill_name` 已被成功读取，读错 Skill 不能授权执行；
- 新增 `script_calls` 安全观测，只记录 Skill、script、状态、耗时和错误码，
  不记录完整输入、输出或用户数据；
- 当前四个高层业务 Tool 已返回最终结构时，Skill 明确禁止重复运行 scripts，因此正常推荐、
  比较和详情不会无条件增加一次脚本调用；scripts 主要为异常结构和 Phase S4/S5 窄 Tool 做准备。

离线验证：

```text
Phase S3 定向测试：33 passed
Shopping / Judge / 多模态 / SSE / 主图 / API 合并回归：120 passed
四个 Skill quick_validate：全部通过
```

本阶段未自动重启或停止 AI Service。真实模型验收前需要用户手动重启 AI Service，
确认 `.env` 中 `SHOPPING_SKILL_SCRIPT_MODE=controlled`，并在确实触发 script 的任务中
观察 `script_calls`。

### Phase S4：拆窄推荐 Tool

目标：让 `discover-products` 真正编排候选召回和结果终结。

工作项：

- 从 `RecommendCapability` 提取 `search_product_candidates`；
- 提取 `finalize_product_recommendation`；
- 保持文本、纯图、图文统一 CandidateSet；
- 第一轮继续复用独立 Candidate Judge；
- 验证 exact / alternative / empty 和偏好软排序；
- 评估是否将 Judge 合并到 ShoppingDeepAgent。

完成标准：Skill 决定流程，Tool 提供事实，代码只校验候选和构造卡片。

#### Phase S4 实现记录

- DeepAgent 主链将一体化 `recommend_products` 替换为
  `search_product_candidates → finalize_product_recommendation`；
- `RecommendCapability` 拆出 `search_candidates()` 与 `finalize_candidates()`，
  原 `run()` 保留为关闭 DeepAgent 时的人工回滚组合入口；
- 文本、纯图和图文仍统一输出 `CandidateSet`，没有增加新的检索通道或语义规则；
- 第一轮继续复用现有单次 Candidate Judge，没有新增 LLM 调用；
- 候选集通过请求级随机 `candidate_set_id` 传递，终结 Tool 读取服务端保存的
  原始候选，模型不能改写商品 ID、价格或候选事实；
- 候选召回返回 `clarify/empty` 时直接结束，返回 `candidates` 时中间件强制继续
  调用终结 Tool，未完成终结不能直接生成推荐回答；
- `discover-products` Skill 已更新为两步编排，正常链路不重复运行候选脚本；
- 原 `recommend_products` 仅保留在 `SHOPPING_DEEP_AGENT_ENABLED=false` 的人工回滚链。

### Phase S5：拆窄 Compare / Detail Tool

目标：移除不断扩充的固定关注点关键词。

工作项：

- 提取统一 `load_bound_product_facts`；
- 让 Skill/Agent 理解用户关心的对比或详情维度；
- 将单位、区间和矩阵计算下沉 scripts；
- 保留 Router 绑定 ID Guard；
- 删除无用 `_FOCUS_MAP` 分支，前提是回归通过。

完成标准：新增一种对比维度或详情问法优先改 Skill/reference，不需要继续扩充关键词表。

#### Phase S5 实现记录

- DeepAgent 主链不再暴露一体化 `compare_products` 和
  `answer_product_detail`，两者仅保留在
  `SHOPPING_DEEP_AGENT_ENABLED=false` 的人工回滚链；
- 新增统一 `load_bound_product_facts`，仅接收
  `purpose=compare|detail` 和 Router 已绑定商品 ID 的可选有序子集，
  不接收 query、focus 或自然语言关键词；
- 新增 `BoundProductFactsCapability` 和稳定契约，一次返回真实商品主档、
  价格、SKU、库存、规格及商品卡；不存在、下架、数量不足或绑定不清时返回
  `empty/clarify`；
- Compare Skill 由 Agent 根据当前完整问题理解开放比较维度，再按需运行
  `normalize-units` 或 `build-comparison-matrix`；代码不再通过 `_FOCUS_MAP`
  识别价格、评分、销量、肤质等固定词，也不替 Agent 选择赢家；矩阵 script
  支持对任意真实字段路径做 `range/min/max/sum/count` 聚合，因此 SKU 价格区间、
  总库存等新维度不需要继续扩充关键词映射代码；
- Inspect Skill 由 Agent 根据当前完整问题理解详情关注点；只有 SKU 价格区间、
  总库存或规格汇总需要确定性计算时才运行 `summarize-sku-facts`，普通基础价格
  和商品描述不增加 script 调用；旧回滚 Detail Tool 也改为返回完整事实，删除
  固定 `_FOCUS_KEYWORDS` 和按关键词分派的额外特征 LLM；
- Skill 和 Tool Guard 继续双重限制：Compare 至少两个绑定商品，Detail 只能一个，
  Agent 不能从历史文本、标题片段或自然语言创建、补充或替换商品 ID；
- 统一事实 Tool 的能力观测由 `purpose` 映射为 `compare/detail`，最终商品卡、
  `capability`、`dispatch_source=agent_tool_loop` 和 SSE 返回契约保持兼容；
- 本阶段没有新增 LLM：比较维度和详情关注点由现有 ShoppingAgent 模型理解，
  商品事实由 Tool 提供，单位、区间与矩阵由受控 scripts 确定性计算。

离线验证：

```text
Phase S1-S5、High-level Tools、Tool Guard、旧 Capability：69 passed
Shopping、Skills scripts、Judge、多模态、SSE、主图与 API 合并回归：141 passed
python -m compileall -q app tests：通过
四个 Shopping Skill quick_validate：全部通过
git diff --check：通过
```

本阶段没有自动启动、停止或重启 AI Service。真实验收前由用户手动重启服务，
再一起冒烟 Phase S4 推荐两步编排与 Phase S5 比较/详情事实加载。

### Phase S6：Sandbox、性能与旧逻辑清理

目标：生产化并删除重复实现。

工作项：

- 选择并接入 Sandbox 或受控自定义 Backend；
- Skill 目录发布为只读；
- 建立 Sandbox 池和资源限制；
- 基于 LangSmith 对比 Skill 激活、模型调用、延迟和成本；
- 新架构稳定一个版本后删除旧长 Prompt 和重复 docstring；
- 评估是否删除旧 Shopping rule dispatcher，仅保留明确故障策略；
- 默认开启 DeepAgent 开关。

## 17. 测试与验收计划

### 17.1 Skill 结构测试

- 每个目录包含合法 `SKILL.md`；
- `name` 与目录一致；
- `description` 能区分 discover / compare / inspect / profile；
- `SKILL.md` 不超过建议长度；
- reference 路径存在且只嵌套一层；
- scripts 通过静态检查和独立运行测试；
- Skill 目录不包含无关 README、变更记录等冗余文件。

### 17.2 Skill 激活矩阵

| 用户任务 | 应读取 | 不应读取 |
| --- | --- | --- |
| “推荐通勤耳机” | `discover-products` | compare、inspect、profile |
| “根据我的肤质推荐防晒” | `discover-products`、`use-shopping-profile` | compare、inspect |
| “比较第一款和第三款”且 Router 已绑定 ID | `compare-products` | discover、inspect |
| “第一款多少钱”且唯一绑定 | `inspect-product` | discover、compare |
| “这两款哪个更适合通勤” | `compare-products` | discover |
| 纯图片找相似商品 | `discover-products` | compare、inspect |

### 17.3 功能回归

继续覆盖当前已验收场景：

```text
推荐几款耳机
推荐 500 元以内的耳机
无精确预算商品时返回同类 alternative
推荐耳机不能出现电脑
夏天出油多，推荐控油清爽护肤品
纯图片找相似跑鞋
图文找相似跑鞋且预算 500 元以内
第一款和第三款对比
第一款和第三款越界时自然澄清
查询已绑定商品价格、库存和 SKU
肤质偏好不污染耳机推荐
相同参数推荐最多执行一次
```

### 17.4 Script 测试

- 候选字段缺失；
- 重复候选；
- 非法候选编号；
- 模型创造商品 ID；
- exact 与 alternative 混合；
- 偏好分相同的稳定排序；
- 偏好与当前品类无关；
- 预算差额；
- SKU 空列表；
- Script 超时、非法 JSON 和输出过大。

### 17.5 安全测试

- 尝试读取 `.env`；
- 尝试写入 Skill；
- 尝试执行非白名单脚本；
- 尝试用 `../` 越界路径；
- 尝试 Compare/Detail 传入未绑定 ID；
- 尝试让图片污染 Knowledge 子任务；
- 尝试让 Agent 输出任意未召回商品；
- 尝试从其他 conversation 读取工作文件。

### 17.6 性能验收

Deep Agents Skill 首次读取通常会增加一次 Agent 循环，因此必须记录真实数据，不能只看 HTTP 200。

重点指标：

| 指标 | 目标 |
| --- | --- |
| 常驻 Prompt token | 明显低于迁移前长 Prompt |
| Skill 命中率 | 目标任务正确读取率不低于 95% |
| 错误 Skill 加载率 | 不高于 2% |
| 普通推荐模型调用 | 建立基线，避免无边界增长 |
| 相同 Tool 重复调用 | 0 |
| Script 执行 | 正常脚本 P95 不高于 100 ms；Sandbox 冷启动单独统计 |
| 简单请求端到端 | 以当前真实环境基线为准，目标保持用户可接受的 5–6 秒级体验 |
| 商品事实错误 | 0 |
| 跨品类无关卡片 | 0 |

若 Skill 读取导致延迟不可接受，优先优化 Skill 内容、模型调用次数、Backend I/O 和 Sandbox 池，不要恢复长常驻 Prompt，也不要叠加新的规则 Router。

### 17.7 现有定向测试

实施时至少运行：

```powershell
cd ai-service
python -m pytest -q `
  tests/test_shopping_agent_phase2.py `
  tests/test_shopping_high_level_tools.py `
  tests/test_shopping_tool_guard.py `
  tests/test_recommend_capability.py `
  tests/test_relevance_judge.py `
  tests/test_shopping_recommend_input_modes.py `
  tests/test_shopping_sse_streaming.py `
  tests/test_multimodal_retrieval_v2.py

python -m compileall -q app tests
```

并新增：

```text
tests/test_shopping_deep_agent.py
tests/test_shopping_skill_discovery.py
tests/test_shopping_skill_activation.py
tests/test_shopping_skill_scripts.py
tests/test_shopping_skill_permissions.py
tests/test_shopping_deep_agent_streaming.py
```

## 18. 代码文件变更清单

### 第一批新增

```text
ai-service/skills/shopping-agent/**
ai-service/app/domain/shopping/deep_agent.py
ai-service/app/domain/shopping/skill_backend.py
ai-service/app/domain/shopping/skill_observability.py
ai-service/tests/test_shopping_deep_agent.py
ai-service/tests/test_shopping_skill_activation.py
```

### 第一批修改

```text
ai-service/requirements.txt
ai-service/.env.example
ai-service/app/infrastructure/config.py
ai-service/app/domain/shopping/agent.py
ai-service/app/domain/shopping/high_level_tools.py
ai-service/app/prompts/prompts.py
```

### 后续按阶段修改

```text
ai-service/app/domain/shopping/capabilities/recommend.py
ai-service/app/domain/shopping/capabilities/compare.py
ai-service/app/domain/shopping/capabilities/detail.py
ai-service/app/domain/shopping/relevance_judge.py
ai-service/app/domain/shopping/tool_guard.py
```

第一阶段不改：

```text
services/chat-service 的外部 API
前端 SSE 事件名称
product_cards 对外结构
Router 的领域和复杂度输出
Planner / DAG 的任务模型
KnowledgeAgent / ChitchatAgent
```

## 19. 主要风险与处理

| 风险 | 表现 | 处理 |
| --- | --- | --- |
| Skill description 重叠 | 推荐任务误读 compare Skill | 明确“新商品发现”和“已绑定商品比较”边界，建立激活矩阵 |
| Skill 读取增加延迟 | 比当前多一次模型循环 | 先做真实基线；缩短 Skill；缓存只读文件；后续合并独立 Judge |
| Agent 读了 Skill 仍不执行步骤 | 跳过真实 Tool 直接回答 | 保留首次商品 Tool 结果要求和事实 Guard |
| Script 变成任意代码执行 | 读取密钥或执行系统命令 | 白名单 runner 或隔离 Sandbox，默认无网络 |
| Tool 拆太细导致游走 | 多次无收益调用 | Skill 限定流程，Tool Guard 限制主能力和重复调用 |
| 双重 Planner | ShoppingAgent 又使用 task/write_todos | 第一阶段排除 Deep Agents Subagent/Todo 能力 |
| Skill 与现有 Capability 双份逻辑 | 修改一处另一处过期 | 先迁操作手册，再逐步拆 Capability，阶段结束删除重复内容 |
| 生产版本漂移 | Deep Agents API 更新导致启动失败 | 精确锁定 `deepagents==0.7.1`，增加最小集成测试 |
| 偏好再次污染品类 | 油皮影响耳机 | Skill 明确分离命中与偏好，Judge 输出适用度，代码只稳定排序 |

## 20. 最终验收标准

只有同时满足以下条件，才能认为 ShoppingAgent 已完成 Skill 化：

- [x] ShoppingAgent 使用 `create_deep_agent`，不是只建立了 Skill 目录但仍由旧长 Prompt 驱动；
- [x] 推荐、对比、详情任务能按需读取正确 `SKILL.md`；
- [x] 常驻 Shopping Prompt 不再包含所有能力的完整操作手册；
- [x] Tool docstring 不再复制 Skill 的完整流程；
- [ ] 实时商品事实仍全部来自受控 Tool / Repository；
- [x] Skills 可以按说明读取 references，并通过受控方式执行 scripts；
- [ ] Compare/Detail 仍只能使用 Router 绑定 ID；
- [ ] 相同参数推荐仍不会重复执行；
- [ ] 文本、纯图和图文仍走统一 ShoppingAgent；
- [ ] exact / alternative / empty 和偏好软排序不回归；
- [ ] SSE、product_cards 和现有调用契约兼容；
- [ ] 不引入第二套 Router、Planner 或跨轮上下文解析；
- [ ] Skill 激活、Tool、Script、模型调用和延迟均可观测；
- [ ] 生产环境没有开放宿主机任意文件和任意 shell；
- [ ] 真实 H5 核心场景通过，且延迟没有不可接受的增长。

## 21. 推荐实施顺序

建议严格按以下顺序推进：

```text
S0 依赖和最小 DeepAgent 验证
  → S1 Adapter + Skill 目录 + 双轨开关
  → S2 删除长 Prompt 和重复 docstring
  → 人工验收 Skill 激活、SSE 和核心商品功能
  → S3 受控 scripts
  → S4 推荐 Tool 拆分
  → S5 Compare / Detail 拆分
  → S6 Sandbox、性能优化和旧逻辑删除
```

不建议一次性同时完成 Deep Agents 接入、所有 Tool 拆分、Judge 合并和 Sandbox。那样出现“推荐耳机却出电脑”“预算替代消失”或延迟上升时，将无法判断问题来自 Skill、Agent、Retriever、Judge 还是 Backend。

## 22. 官方资料

- Deep Agents Overview：<https://docs.langchain.com/oss/python/deepagents/overview>
- Deep Agents Skills：<https://docs.langchain.com/oss/python/deepagents/skills>
- Deep Agents Backends：<https://docs.langchain.com/oss/python/deepagents/backends>
- Deep Agents Customization：<https://docs.langchain.com/oss/python/deepagents/customization>
- Deep Agents Python API：<https://reference.langchain.com/python/deepagents>
- Agent Skills specification：<https://agentskills.io/specification>
- PyPI deepagents 0.7.1：<https://pypi.org/project/deepagents/0.7.1/>
