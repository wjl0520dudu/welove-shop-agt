# 智能导购主链收敛与体验恢复实施计划

> 状态：待实施。本文是后续逐阶段开发与验收的唯一执行计划。
>
> 基线提交：`87846c2 feat(ai): 收敛路由上下文与子Agent职责`
>
> 范围：以当前工作区和现有服务为基础收敛主链；不推倒重写，不覆盖既有设计文档。

> 术语校正：当前基线**没有**独立的 `ContextUnderstanding` 节点或另一套 `IntentRouter` 实现。当前已有的是纯代码的 `resolve_context()`、结构化 LLM 的 `_route()` / `IntentDecision`，以及位于 Router 前的 `_analyze_request()` / Orchestrator。本计划中所说的“Router LLM”是对当前 `_route()` 的收敛改造，绝不合并或依赖已废弃分支中的 `Context Understanding`、`TurnUnderstanding` 等代码。

## 1. 背景、结论与边界

近期真实 API 评测的前 100 条样本通过率为 67%，其中 Shopping 68.89%、Knowledge 59.38%、Chitchat 73.91%；文本请求 P50 为 8.93 秒、P95 为 20 秒。更重要的是，人工体验发现部分简单请求会等待 40～60 秒，且出现了“问推荐却澄清”“宽泛护肤需求没有商品”“防晒推荐出精华或防晒帽”“复合问题漏答”等直接可见回归。

当前恢复后的代码主链如下；这是本计划唯一认可的实际起点：

```text
START
  → resolve_context（纯代码：保留完整当前历史，并补充最近商品卡快照）
  → analyze_request（旧 Orchestrator：规则短路或 Planner LLM）
  ├─ simple  → route_intent（当前结构化 LLM：IntentDecision）
  │             → Shopping / Knowledge / Chitchat / Unknown
  └─ complex → execute_dag → synthesize_final → format_response
```

其中，`resolve_context()` 已经是正确的纯数据准备层，不需要替换。问题是 `_analyze_request()` 在 Router 之前便可能将原始问题送进旧 Orchestrator；普通 Shopping 又常被 Dispatcher 直接分流，实际没有让 Shopping Tool Agent 决定任务。因此系统同时存在多个、可能彼此冲突的“理解者”，不仅变慢，也会让规则漏命中时直接损失能力。

本计划采用以下已确认原则：

1. **LLM 主理解，代码保安全与事实。** 自然语言的指代消解、话题延续或切换、领域识别、复杂度判断、商品条件理解、候选匹配与解释，均由受结构化输出约束的 LLM 完成。代码不得用关键词或正则重新解释用户语义。
2. **规则只用于领域工具执行时不可协商的事实与安全边界。** 例如真实商品 ID、在售状态、价格/SKU/库存事实、权限和写操作安全。
3. **Router 是唯一上层语义入口。** 它基于完整当前会话上下文完成理解和领域路由；它不决定 Shopping 内部应当“推荐/比较/详情”。
4. **子 Agent 只执行自己的领域任务。** Shopping、Knowledge、Chitchat 不再自行读取全历史、Redis 或业务记忆来做第二次指代消解和顶层路由。
5. **复杂任务才使用 Planner/DAG。** Planner 不重新进入 Router；DAG 子任务也不重新进入顶层 Router。
6. **不做 Agent 加购/HITL。** 商品卡已有加购入口；下单、支付仍只引导至正式页面。用户的澄清问题属于正常对话控制，不视为交易型 HITL。
7. **长期行为偏好继续关闭。** 仅保留基础标签作为可选的软信号；只有 LLM 认定与本轮商品领域相关时才可参与排序，肤质不得影响耳机推荐。

## 2. 目标架构

### 2.1 新主链

```text
用户问题 + 图片
    │
    ▼
Conversation Preparation / resolve_context（纯代码、完整收集当前可用上下文）
    │  当前问题 / 图片状态 / 完整历史 / 后续可选滚动摘要 /
    │  最近商品卡与知识实体 / agent_meta / 基础偏好标签
    ▼
Intent Router LLM（唯一上层语义节点）
    │  指代消解、槽位继承、意图延续/切换/嵌套、
    │  canonical question、领域、simple/complex、置信度
    │
    ├── unknown ───────────────────────────────► General Fallback：请清楚描述需求
    ├── simple/shopping ───────────────────────► Shopping Tool Agent
    ├── simple/knowledge ──────────────────────► Knowledge Tool Agent
    ├── simple/chitchat ───────────────────────► Chitchat Agent
    └── complex ─► Planner LLM → DAG Executor → 指定领域 Agent
                                               └► 每个子任务完成即 SSE 输出
    │
    ▼
Response / SSE done
    │
    └──────────────────────────────────────────► 异步会话摘要与观测更新
```

Router 输出的 `canonical_question`、领域、模式和上下文引用直接写入主图 state，简单任务由对应领域节点直接消费；复杂任务由 Planner 消费。节点间仅做 state 字段传递，不额外进行意图、动作或实体的二次加工。

### 2.2 Router 的输入与输出契约

Router 是一次受 Structured Output 约束的 LLM 调用，不是普通聊天 Agent。输入使用 `resolve_context` 提供的完整当前会话历史、已脱敏结构化快照与本轮输入；Router 不能自行访问数据库、Redis 或工具。

```python
class RouteDecision(BaseModel):
    decision: Literal["execute", "unknown"]
    mode: Literal["simple", "complex"] | None
    target_domain: Literal["shopping", "knowledge", "chitchat"] | None
    canonical_question: str
    resolved_entity_refs: list[ResolvedEntityRef]
    inherited_context: dict[str, Any]
    confidence: float
    reason: str  # 仅用于观测，不向用户暴露
```

简单问题的 Router 输出示例：

```json
{
  "decision": "execute",
  "mode": "simple",
  "target_domain": "shopping",
  "canonical_question": "推荐适合通勤、预算 500 元以内的耳机",
  "resolved_entity_refs": [],
  "confidence": 0.92
}
```

复杂问题的 Router 输出示例。Router 只确认它是复杂目标，并交出已经消解的完整问题；**不在这一步生成 DAG，也不输出 Shopping 的 recommend/compare/detail 操作**：

```json
{
  "decision": "execute",
  "mode": "complex",
  "target_domain": null,
  "canonical_question": "推荐适合通勤的耳机，并解释开放式耳机与入耳式耳机的区别",
  "resolved_entity_refs": [],
  "confidence": 0.90
}
```

`unknown` 时，`decision=unknown`、`mode` 与 `target_domain` 均为空，由 General Fallback 提示用户描述清楚需求。

约束：

- `canonical_question` 必须消除跨轮指代。例如“第一款和第三款呢”应转成“请说明上一轮推荐集合中商品 A 和商品 C 的信息”，并绑定真实 `product_id`；不要求 Router 决定这是对比还是详情。
- 无法唯一绑定的“它/这几款/前两款”、完全不知道用户要做什么、或关键需求过于模糊时，返回 `unknown`；本轮由 General Fallback 自然提示“请描述清楚你想找的商品或想了解的问题”，不新增独立追问状态机。
- 无论问题是否复杂，指代消解只发生在这里。进入 Planner、Shopping、Knowledge 的任务问题都不得保留未绑定的跨轮代词。
- `unknown` 用于订单、物流、退货、优惠券等当前没有 CustomerServiceAgent 或真实工具的业务，也用于不属于商城助手能力范围的问题。它由 General Fallback 以自然语言说明可协助范围或引导正确页面；不能伪装成 Chitchat，也不能机械回复“无法识别”。
- 低置信度且缺少完成任务的关键事实时，返回 `unknown`；品牌、预算等可选偏好不应导致 `unknown`。

### 2.3 复杂任务与 SSE

复杂任务不会第二次进入 Router。Router 将其标记为 `complex` 后，Planner 接收已经消解的完整问题并输出受约束的 DAG；DAG 校验通过后，子任务直接交给指定领域 Agent。

这里的 Planner 是 Router 后新增/重构出的条件节点 `plan_complex`，它取代当前 `_analyze_request()` 的“复杂度判断 + 规划”混合职责。新的职责边界是：Router 判断是否复杂；Planner 仅在复杂时拆分任务、标注每个子任务的执行领域、依赖和图片使用范围；Planner 不再读取完整历史、做指代消解或重新进行顶层路由。

每个子任务完成即发送独立 SSE 内容事件；前端可逐段展示，不等待一个额外的 `synthesize_final` LLM。代码只负责以任务顺序标识、失败状态和 `done` 事件维护协议。若某一子任务失败，已经完成的子任务不得丢失，失败段给出简短、面向用户的说明。

## 3. 已确认问题与对应修复方向

| 编号 | 当前问题 | 已定位位置/表现 | 收敛方向 |
|---|---|---|---|
| P-01 | Router 前已有旧语义决策 | `assistant/graph.py::_analyze_request()` 可能把简单问题提前送入旧 Orchestrator | 改造现有 `_route()` 成为唯一上层语义入口，并移除 `_analyze_request()` 的分流权 |
| P-02 | 普通 Shopping 不是 Tool Agent 主导 | `shopping/agent.py` 先调用 `dispatch_shopping_capability()` | Tool Agent 自己选 recommend/compare/detail；规则 Dispatcher 退出正常主链 |
| P-03 | 核心商品品类会在放宽召回时丢失 | `shopping/retrieval.py` 的 plan/relaxed recall/final filter 语义不一致 | 宽召回后由 LLM Judge 判断相关性；代码只保证在售和真实事实，`alternative` 绝不跨核心品类凑数 |
| P-04 | 评测可能把错误商品误判为通过 | `evals/agent_contract.py` 将生成 reason 混入类目匹配 | 只使用商品真实 category/sub_category/title 等事实做断言 |
| P-05 | 评测无法追踪真实 Prompt | `evals/run_agent_eval.py` 的 Prompt 路径已过期 | 更新 Prompt 指纹路径、固定 UTF-8 报告输出 |
| P-06 | 低风险知识与商城服务类边界不清 | “开放式和入耳式区别”可能被拒答；订单类被误派 | Knowledge 支持低风险通用知识；服务类走自然 Fallback |
| P-07 | 延迟过高且难定位 | 多次 LLM、重复记忆读取、无收益 rerank 和 DAG 等待被混在一起 | 先埋点，再删重；简单推荐不走 Planner 或最终综合模型 |

## 4. 分阶段开发与验收

每一阶段均遵循“实现 → 离线测试 → 用户启动依赖后的 API 冒烟 → 人工/H5 验收 → 用户确认后提交”的顺序。后一阶段不得在前一阶段的核心验收失败时继续叠加实现。

### Phase 0：评测基线、可观测性与服务边界校准

**目的**：先保证后续数据真实可解释，防止“错误商品被 reason 掩盖”或运行器本身导致假失败。

**修改项**：

- 修复 `evals/agent_contract.py::_card_category_text()`：断言只读商品的真实字段；不得把模型生成的 `reason`、回答正文或推荐文案作为类目证据。
- 更新 `evals/run_agent_eval.py::PROMPT_FILES` 至现有 `app/prompts/`、Router、Shopping、Knowledge 与 Chitchat Prompt 文件；报告必须输出真实 Prompt 指纹。
- 统一 runner 的 UTF-8 输出与异常收集，避免 Windows 中文管道编码使已生成完整报告却以失败状态结束。
- 将订单、物流、退货、优惠券等归入 `mall_service_unavailable` 评测契约：预期自然引导而非 Shopping/Knowledge/Chitchat 伪成功。
- 为请求追加阶段耗时观测：Preparation、Router、Planner、各领域 Agent、检索、rerank、Candidate Judge、SSE 首包和总耗时；只记录 request id、阶段、耗时、错误码和模型调用数，不记录完整 Prompt 或敏感原文。
- 固定 200 条分层评测集：Shopping、Knowledge、Chitchat、复杂 DAG、多轮指代、纯图片、图文、商城服务边界。复用现有多模态测试样本，不将单一品类作为全部结论。

**离线验收**：评测 Contract 单测覆盖真实字段断言；报告 Prompt 指纹非空；UTF-8 运行器退出码与报告状态一致；阶段日志可还原一次请求的耗时分布。

**API/H5 验收**：无行为改动，本阶段只确认 200 条评测报告可重复生成并保存基线。

### Phase 1：Router 成为唯一上下文理解与路由入口

**目的**：解决简单问题误进 DAG、多个节点重复消解指代、语义在规则之间被截断的问题。

**修改项**：

- 保留并扩展当前 `resolve_context()`：它完整传递当前可用的会话历史、当前输入、图片存在状态、最近商品卡/知识实体、`agent_meta` 和基础偏好标签；它只补充结构化快照，不裁剪、不改写、不解释自然语言。
- 在当前 `_route()` / `IntentDecision` 上完成语义收敛：Router Agent LLM 一次完成指代消解、槽位继承、话题延续/切换、领域和 simple/complex 判断。`unknown` 直接交给 General Fallback，不建设 `clarify` 分支、待补槽状态或追问状态机。删除正常主链上的关键词复杂度判断、`classify_high_confidence_rule` 的语义决策权，以及 Router 前 `_analyze_request()` 的分流权；不引入也不合并废弃分支的 `ContextUnderstanding` 代码。
- Router Prompt 增加面向职责的 few-shot：离散商品序号（“第一款和第三款”）、整组引用、指代不唯一、话题切换、嵌套请求、简单商品/知识/聊天、复合请求、商城服务类和未知请求。Prompt 明确其不是聊天助手，输出只能满足 Schema。
- Router 输出直接写入主图 state，供下游节点消费。商品价格、在售、SKU 等事实在 Shopping 工具实际查询时确认。
- Router 不输出 `recommend`、`compare`、`detail` 等 Shopping operation；只输出领域与 simple/complex。
- Router 首期保持无工具、单次结构化 LLM 调用，避免为了“Agent”名称额外制造 Tool Loop。它接收完整 `state.messages` 与 `resolve_context()` 准备的结构化快照；首期不在 `resolve_context` 中增加任何按条数或 token 的历史截断。
- 现有 `app/infrastructure/llm/middleware.py::build_summarization_middleware()` 已可复用：当前阈值为 tokens 超过 4000 或消息超过 20 条，保留最近 6 条原文。它目前挂在 Shopping/Knowledge 的 `create_agent` 上。后续接入 Router 前，必须单独设计和验收“摘要 + 原始历史 + 商品/知识实体快照”的完整性；摘要不能静默替代或丢弃权威会话记录，也不得在每个请求同步重算。

**离线验收**：

- “第一款和第三款呢”“第一、三、五款”“前两款”“它们”“上一款”可正确绑定并保留用户指定顺序；歧义时进入 `unknown` 并提示用户描述清楚商品名或序号。
- “先推荐耳机，下一轮聊电影”不会携带耳机实体；“从刚才前两款中选一个，再判断是否适合通勤”在 Router 输出中已绑定两件商品与完整问题。
- Router 不可访问完整历史、Redis、业务工具；下游输入不再含未解析指代。
- Router 调用或现有 Structured Output 解析本身失败时，沿用当前 `unknown` 兜底。

**人工验收**：推荐五款 → “对比这五款” → “第一款和第三款呢”；随后切换为普通聊天，再切回商品问题，确认没有旧实体污染。

### Phase 2：简单路径与 Shopping Tool Agent 收敛

**目的**：让 Shopping 真正由 LLM Agent 决定本轮能力，并消除规则 Dispatcher 抢占、重复工具调用和图片绕行造成的行为割裂。

**修改项**：

- 普通 Shopping 主链改为真正的 `create_agent(LLM + 高层工具)`。Agent 根据 Router 已消解的问题、绑定商品、图片作用域和可用工具决定调用推荐、对比或详情；只允许最终选择一个主要 Shopping capability。
- 移除 `dispatch_shopping_capability()` 在正常路径的抢占；保留其仅作为模型结构化输出持续失败时的受限降级，不得成为关键词主链。
- 强化 `high_level_tools.py` 的工具描述和 few-shot：清晰说明每种工具的输入、适用场景、可用实体、不可用事实和“不得重复调用相同推荐参数”。这属于 Agent 提示能力，不以正则扩充语义。
- 纯文本、纯图片、图文统一进入 ShoppingAgent。输入模式只决定候选生成方式：文本为 BM25 + Dense，图片为图片向量，图文为三路融合/VL rerank；三个路径都在 `CandidateSet` 汇合后进入同一候选判断链。
- Compare/Detail 仅接受 Router 绑定的商品 ID；无法绑定时 Agent 只能澄清，不能从任意历史文本猜测。
- 一轮相同参数推荐最多执行一次；工具结果回到 Agent 时包含结构化候选与事实，不允许 Agent 二次无收益检索。
- Shopping Prompt 删除“自行消解指代/读取会话历史/改写问题”等职责，保留商品发现、比较、详情、条件权衡和自然表达职责。

**离线验收**：Agent Tool 调用测试验证推荐、比较、详情各由 Tool Agent 发起；同参数只调用一次；图片没有文字时会调用相似商品推荐；compare/detail 不会使用未绑定商品。

**人工验收**：文本推荐、纯图片找相似、图文找相似、五款比较、指定第 1 和第 3 款分别完成；前端不会出现“未收到商品问题”。

### Phase 3：推荐候选链与诚实替代策略

**目的**：恢复“有候选但无完全匹配时仍能给有用建议”的体验，同时杜绝用无关商品凑数。

**目标链路**：

```text
Shopping Tool Agent
  → 宽召回真实在售候选（不因普通预算/场景过早清空）
  → LLM Candidate Judge
  → 代码事实校验
  → Shopping Finalizer LLM
  → exact / alternative / empty 商品卡
```

**修改项**：

- 检索层只做系统硬过滤：真实 Collection、状态、权限、可查询字段。目录真实字段可用于规范化，但不得以“耳机/油皮/通勤”等自然语言别名表替代语义理解。
- Candidate Judge 输入用户完整问题、Tool Agent 已抽取的开放需求、真实候选商品字段和可选基础偏好标签，输出候选编号、`exact | alternative | reject`、满足条件、约束差距、理由和置信度。
- Candidate Judge 只能选择当前 `CandidateSet` 的编号。代码校验候选真实存在、`status == 1`、价格/SKU/库存等事实；模型无法伪造商品、价格或差额。
- “核心对象”由 LLM 在本轮理解中定义并通过候选相关性判断维持，而不是逐类扩充硬编码别名。无满足预算的耳机时，只能给商城在售耳机的 `alternative`，并说明实际价格与预算差额；不得推荐防晒帽、精华等无关商品。
- 用户说“500 元以内”但商城没有完全符合项：有同类候选时返回 `alternative`；用户说“必须 500 元以内”时，参考卡仍可展示但必须显著标记不符合预算，不得称为符合推荐。只有同类候选池确实为空才返回 `empty`。
- 保留 `ProductCard.match_status` 与 `constraint_gaps` 的向后兼容字段。前端按 `exact` 与 `alternative` 分组，参考卡标为“店内参考”，首条展示真实差距。
- 现有确定性 CandidateCoverage 仅作为 Candidate Judge 连续失败后的事实级保守兜底，不能作为正常语义过滤。
- 基础偏好标签仅以软信号提供给 Judge；由模型决定是否有关。长期行为偏好、自动偏好事实与自动偏好 Proposal 保持关闭。

**离线验收**：

- 防晒、精华、耳机、跑鞋、食品、家电等不同类目都覆盖 `exact/alternative/empty`。
- “夏天出油多，控油又清爽的护肤品”在有护肤候选时不因软场景词被硬过滤为空；耳机推荐不出现肤质理由。
- “500 元以内耳机”无精确候选时，仅出现耳机 `alternative`；候选池没有耳机时才报告无同类商品。
- 所有商品卡的价格、状态、类目均由真实字段断言，评测不得从生成文案推断通过。

**人工验收**：同一问题分别以普通预算、严格“必须”预算测试；检查商品卡分组、差距提示、详情与加购按钮保持可用且不误导。

### Phase 4：Knowledge、Chitchat、Fallback 边界收敛

**目的**：使知识问题可回答、风险问题可控、日常聊天自然延续，而不是互相抢路由。

**修改项**：

- KnowledgeAgent 保持 LLM Tool Agent。它只接受 Router 完整问题及已绑定实体，按需调用内部知识检索、证据读取和必要网络检索。
- 知识回答统一为 `grounded_internal`、`grounded_web`、`general_knowledge`、`unavailable`。开放式与入耳式耳机区别等稳定低风险常识可直接使用 `general_knowledge`，但不得伪造论文、来源或精确数字。
- 商品实时价格、库存、SKU、具体型号参数必须由商品事实工具提供；医疗、孕妇、药物、治疗效果、具体浓度和副作用必须有内部/可信网络证据。代码风险规则只能提高风险等级，不能将高风险问题降级为常识。
- Chitchat 继续接收 Preparation 提供的最近消息、滚动摘要、当前问题和用户基础画像，使正常聊天可连贯；其 Prompt 不再提及指代消解、问题改写或任务路由，且禁止生成商品实时事实、虚构历史或写操作。
- 回顾问题由 Router 明确区分：`last_turn`（上一轮）、`recent_questions`（近期主要问题）、`conversation_review`（滚动摘要 + 最近消息）。Chitchat 不自行读取数据库或 Redis。
- General Fallback 处理 `unknown` / 暂无对应商城服务能力的请求，以自然语言说明可用入口；不制造不存在的订单、物流或退款状态。

**离线验收**：低风险常识能回答；高风险无证据安全拒答；商品事实不走通用知识；“我之前问过哪些问题”基于摘要得到回顾而非仅复述上一轮；订单类请求不会被当作知识或商品检索。

**人工验收**：“推荐耳机，同时解释开放式和入耳式区别”中两部分都能输出；连续聊天与回顾历史自然、无虚构；医学/孕期类问题不越权。

### Phase 5：Planner、DAG 与流式返回收敛

**目的**：只为真正独立的复合目标增加编排成本，避免复杂任务二次路由及最终综合模型造成整体阻塞。

**修改项**：

- Planner 仅在 Router 输出 `mode=complex` 时调用。输入是已消解的完整问题与绑定实体，输出 `ExecutionPlan`（任务 ID、领域、问题、实体引用、依赖、图片使用标记）；不重新读取历史，不重做领域识别。
- DAG Validator 只检查 Agent 白名单、实体引用、图片作用域、重复 ID、依赖合法性、环和任务数上限。Planner 输出非法时允许一次结构化修订；仍失败则自然建议用户拆分问题，不退回关键词拆解。
- DAG 子任务直接派发给指定领域 Agent，禁止回到全局 Router。各领域输出统一 `AgentArtifact`：状态、领域、问题、已验证事实、商品卡、来源、正文草稿和错误。
- 删除 `_build_orchestrator_answer` 等硬编码终稿拼接及 `Synthesis Final LLM` 等待。每个 Artifact 完成即产生带任务编号的 SSE 内容；仅在 `done` 事件汇报整体完成/部分失败状态。
- 现有并发、依赖、超时和失败隔离能力继续复用；有依赖的任务等待上游 Artifact，无依赖任务并发执行。

**离线验收**：复杂任务仅一次 Router、一次 Planner；子任务不重新路由；非法 DAG/循环/超限被安全拒绝；一项失败时其他项仍发送；SSE 顺序、`done` 语义与商品卡协议兼容。

**人工验收**：

- “推荐耳机，同时解释开放式和入耳式区别”能先看到已完成部分，不等待所有任务做统一润色。
- “从刚才前两款中选一个，再判断是否适合通勤”可按依赖完成；只要一个子任务失败，已成功内容仍可见。

### Phase 6：简单路径性能、降级与稳定性

**目的**：把简单导购恢复到正常交互等待范围，而不是将“更智能”建立在多次串行模型调用上。

**修改项**：

- 基于 Phase 0 分段埋点，逐项删除 Router 后的重复 LLM 理解、重复 memory 读取、重复推荐工具调用和无收益 rerank；不得靠提高超时掩盖慢调用。
- 简单 Shopping 目标调用链为：Preparation（代码）→ Router LLM（1 次）→ Shopping Tool Agent（按需 1 次工具循环）→ Candidate Judge（仅有候选且需要语义取舍时）→ Finalizer（仅事实工具结果无法自然表达时）。没有候选、澄清和纯事实详情不得额外调用无收益 Finalizer。
- 复合任务使用并发 DAG，SSE 首个完成任务立即输出。外部网络检索、重排和模型调用分别设置有限超时、一次可观测重试和明确失败阶段；不触发自动切回旧关键词主链。
- 保持 `ASSISTANT_UNIFIED_UNDERSTANDING_ENABLED` 为单一人工回滚开关：关闭时仅用于紧急回到已知旧链；新链本身失败时不静默切回，避免难以诊断的双行为。

**性能验收**（在相同本地模型/数据/网络条件下统计）：

| 场景 | 目标 |
|---|---:|
| 简单文本商品推荐 P50 | ≤ 6 秒 |
| 简单文本商品推荐 P95 | ≤ 10 秒 |
| 简单请求模型理解次数 | 顶层 Router 固定 1 次；不得有 Router 前二次理解 |
| SSE 首个有效内容 | 简单任务 ≤ 6 秒；复杂任务按首个已完成子任务输出 |
| 工具重复调用 | 同参数推荐 0 次重复 |

若外部模型或网络超时导致极端样本超过阈值，报告必须标记具体阶段，而不是将全部慢请求归因于“模型慢”。

### Phase 7：端到端回归、清理与发布准备

**目的**：以用户任务完成率而非 HTTP 200 决定是否上线，并在新主链稳定后清理竞争代码。

**修改项**：

- 按下文完整验收集先修复当前失败样本，再跑全量 200 条；报告按领域、输入模态、任务复杂度、延迟和失败阶段拆分。
- 在 H5 验收 exact/alternative 商品卡、逐段 SSE、图片上传、历史回顾和普通聊天。UI 不显示 Agent、DAG、Tool、Capability、Collection 等内部术语。
- 保持对外兼容：`final → done`、`product_cards`、Proposal、`conversation_summary`、`recommendation_coverage`、`answer_mode`、`match_status`、`constraint_gaps` 继续兼容旧调用与旧消息。
- `agent_meta` 仅持久化路由来源、模式、能力、摘要状态、失败阶段和模型调用次数等安全观测字段；不保存完整 Prompt 或敏感会话内容。
- 新架构稳定一个发布周期后，删除旧 Prompt、旧 Router/Planner、关键词复杂度判断、规则 Dispatcher 主链和无用状态字段。删除前必须以测试证明没有引用，不能在未验收前大范围清理。

## 5. 统一验收集

### 5.1 必测用户场景

```text
1.  图文推荐 5 款 → 第一款和第三款呢
2.  推荐 5 款 → 对比这 5 款 → 前两款呢
3.  从刚才前两款中选一个，再判断是否适合通勤
4.  推荐耳机，同时解释开放式和入耳式区别
5.  我上一轮问了什么 / 我之前问过哪些 / 总结这次对话
6.  纯图片找相似商品
7.  图文找相似商品并给出预算、用途条件
8.  夏天出油多，推荐控油清爽的护肤品
9.  推荐 500 元以内耳机
10. 必须 500 元以内；无符合项时展示诚实的同类店内参考
11. 防晒、精华、跑鞋、食品、家电等跨品类推荐
12. 先问护肤，再切换聊天，再问耳机；旧肤质与预算不得污染新任务
13. 订单/物流/退货/优惠券等商城服务请求的自然引导
14. 高风险健康问题无可信证据时的安全边界
15. 不存在商品 ID、跨会话引用、图片不属于当前会话等安全异常
```

### 5.2 通过标准

除接口可用外，每个案例还需同时检查：

- 用户目标是否完成；
- 是否路由到正确领域，复杂任务是否只调用一次 Planner；
- 指代是否被正确绑定；无法可靠绑定时，是否安全进入 `unknown` 并提示用户清楚描述需求；
- 商品卡是否真实、在售、同类相关，价格/差额是否准确；
- `exact/alternative/empty` 是否诚实；
- 复杂任务是否保留成功子结果并尽早流式输出；
- 是否存在无关基础偏好污染、虚构知识/历史、重复工具调用；
- 延迟是否达到 Phase 6 目标。

### 5.3 验证命令

离线阶段使用与改动范围相符的定向命令，至少包括：

```powershell
cd ai-service
D:\dev\env\conda_envs\wlagt\python.exe -m pytest <本阶段定向测试> -q
D:\dev\env\conda_envs\wlagt\python.exe -m compileall -q app tests evals
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_agent_eval --direct --output evals/reports/<版本>.json --markdown-output evals/reports/<版本>.md

cd ..
mvn -pl services/chat-service -am test
python scripts/check_flyway_migrations.py --base-ref origin/main
cd web/welove-shop
npm run build:h5
git diff --check
```

真实 API 冒烟由用户明确服务已启动后再执行。基础集合为 PostgreSQL、Redis、Nacos、Milvus、gateway、user-service、chat-service、ai-service；多模态需 DashScope，知识网络兜底需博查。不要在开发过程中自动启动、停止或修改用户的本地服务。

## 6. 不在本轮范围内

- 自动加购、自动下单、自动支付或交易型 HITL；
- 新建长期行为偏好、自动偏好事实、自动偏好 Proposal；
- 无界读取历史消息或绕过会话/用户权限；
- 以扩充关键词、正则、品类别名来替代 LLM 的语义理解；
- 在未完成各阶段验收前删除旧代码、重置工作区、修改已发布 Flyway 历史迁移；
- 将知识库索引/分块实验与本次主链收敛混为同一改动。知识库检索质量可独立优化，但不应阻塞 Router/Shopping 主链修复。

## 7. 实施顺序与提交边界

```text
Phase 0 评测可信度/埋点
  → Phase 1 单一 Router
  → Phase 2 Shopping Tool Agent
  → Phase 3 候选 Judge 与 alternative
  → Phase 4 Knowledge/Chitchat/Fallback
  → Phase 5 Planner/DAG/SSE
  → Phase 6 性能与降级
  → Phase 7 全量验收、清理、发布准备
```

建议每一 Phase 单独提交，提交前附上：改动范围、定向测试结果、API/H5 人工验收记录、已知未解决问题和回滚方式。若某阶段的目标指标或关键场景失败，先修复该阶段，不将下一阶段的功能叠加进来。这样可以保留当前可工作的基线，也能准确识别每次改动对体验与延迟的影响。
