# Phase 2 ShoppingAgent：AI Service 人工验收指南

## 1. 目的与范围

本文只验收 `ai-service` 的 Phase 2 ShoppingAgent 改造，不要求启动或验证 `chat-service`、Redis、Gateway、前端、加购、下单或支付。多轮指代验收建议保持 AI Service 自己的 PostgreSQL Store 可用；若不可用，服务会退化为进程内记忆，单次服务进程内的连续调用仍可测试，但重启后记忆会丢失。

本阶段要确认的是：

```text
Router 已完成上下文绑定
        ↓
ShoppingAgent（LLM Tool Agent）自行选择一个高层商品工具
        ↓
recommend_products / compare_products / answer_product_detail
        ↓
真实商品数据与自然语言回答
```

本阶段不验收以下尚未实施的 Phase 3 能力：候选 Judge LLM、`exact/alternative/reject` 标签、预算不满足时的替代推荐策略。因此，“500 元以内耳机”无符合结果时，当前版本仍可能返回空结果或普通的无结果说明；这不能单独判定为 Phase 2 失败。

### 1.1 验收时必须分开记录的两个结论

| 观察维度 | 属于哪个阶段 | 判定依据 |
| --- | --- | --- |
| Agent 编排 | Phase 2 | 是否进入 ShoppingAgent、由 LLM 选择一个高层工具、工具是否重复或混用 |
| 商品实体绑定 | Phase 2 | “第一、三款”是否绑定为对应两件商品，比较/详情是否只使用绑定 ID |
| 候选语义质量 | Phase 3 | 候选是否真的属于耳机/跑鞋等目标品类，是否应被 accept/reject |
| 预算替代表达 | Phase 3 | 无精确商品时，能否把同类超预算商品诚实显示为参考 |

例如“推荐耳机却出现 MacBook”：这是需要修复的真实产品问题，但它通常是召回后排序/候选筛选问题，不表示 ShoppingAgent 选错了工具。验收记录必须写成：

```text
Phase 2 编排：通过（recommend_products 仅调用一次，dispatch_source=agent_tool_loop）
Phase 3 候选质量：失败 / 待实现（尚无 Candidate Judge LLM，跨品类卡片未被 reject）
```

不要因该现象误改 Agent 工具选择；同时也不能忽略它，应记录 `trace_id`、完整 `product_cards`，移交 Phase 3。

## 2. 最小环境

启动以下依赖即可完成核心验收：

- `ai-service`：`http://127.0.0.1:8000`
- Milvus 本地栈
- DashScope：对话模型、文本向量、重排模型；图片用例还需要图片向量和 VL Rerank
- 当前活动商品 Collection 中存在 `status=1` 的商品数据
- 多轮商品指代：建议启用 ai-service 配置的 PostgreSQL（LangGraph Checkpointer / Store）

当前生产式三路集合配置应确认如下（集合名按本地实际配置填写）：

```env
SHOPPING_MULTIMODAL_USE_THREE_PATH_COLLECTION=true
MILVUS_PRODUCT_THREE_PATH_COLLECTION=product_multimodal_prod_v1
```

若本地刻意使用旧集合，开关设为 `false`，并确认 `MILVUS_PRODUCT_COLLECTION` 有商品数据。推荐、比较、详情必须读取同一个活动 Collection；不要依赖“推荐有数据、详情读取旧 Collection 后找不到”的错误行为。

启动后先执行：

```powershell
curl.exe http://127.0.0.1:8000/health/live
curl.exe http://127.0.0.1:8000/health
```

`/health/live` 应成功；`/health` 用于检查 LLM、Milvus 等依赖。直接验收 AI Service 时，即便 Java 侧健康检查显示未启动，也不影响下面的商品检索用例；但 Milvus、DashScope 或活动 Collection 不可用时，应先修复环境，不能把它误报成 Agent 行为失败。

## 3. 调用接口与观察字段

推荐使用非流式接口便于直接查看完整 JSON：

```text
POST http://127.0.0.1:8000/api/assistant/run
```

`/api/assistant/run` 已支持可选 `image_url`。兼容入口 `/api/assistant/multimodal/run` 与它语义相同；纯图片可以让 `question` 为空，但必须提供 `image_url`。

流式验收使用：

```text
POST http://127.0.0.1:8000/api/assistant/stream
```

应依次看到 `start`、`route`、可选的 `tool_call/tool_result`、`final`、`done`。`final` 必须早于 `done`；出现 `error` 后也应有 `done`。

基础请求模板：

```json
{
  "question": "推荐一款适合通勤的耳机",
  "conversation_id": "phase2-manual-001",
  "user_id": "1",
  "conversation_history": [],
  "image_url": null
}
```

建议为每一组多轮用例使用独立的 `conversation_id`，例如 `phase2-ref-001`、`phase2-image-001`。`user_id` 对本阶段非必填，但保留可使请求形态更贴近正式链路。

PowerShell 示例：

```powershell
$body = @{
  question = '推荐一款适合通勤的耳机'
  conversation_id = 'phase2-manual-001'
  user_id = '1'
  conversation_history = @()
} | ConvertTo-Json -Depth 12

$response = Invoke-RestMethod `
  -Method Post `
  -Uri 'http://127.0.0.1:8000/api/assistant/run' `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body

$response | ConvertTo-Json -Depth 20
```

每个用例至少记录以下字段：

| 分类 | 关注字段 | 正常表现 |
| --- | --- | --- |
| 最终结果 | `error`、`error_code`、`answer`、`product_cards` | `error=false`；回答与问题相关；推荐成功时有真实商品卡 |
| 路由 | `route`、`task_type`、`orchestrator_mode` | 单领域商品问题为 `shopping`；复合问题为 `complex` 且有子任务结果 |
| Agent 主路径 | `dispatch_source`、`shopping_capability` 或 `capability` | 正常 Shopping 为 `agent_tool_loop`；能力由 Agent 的工具选择得出 |
| 工具链 | `tool_calls[]` | 有高层工具名、状态、耗时；正常推荐/比较/详情不混用多个主能力 |
| 可追踪性 | `trace_id` | 失败时可用它在 ai-service 日志定位 |

`AIResponse` 允许兼容扩展字段，因此 `dispatch_source`、`shopping_capability`、`capability` 可能以顶层扩展字段或工具记录中的字段出现。验收时以实际返回为准，不要求客户端固定解析其中某一个字段名。

## 4. 跨轮验收方式

正常验收**不需要**手工维护 `conversation_history`。使用相同的 `conversation_id` 连续请求即可：

1. 第一轮推荐成功后，`recommend_products` 会把完整、有序的商品卡写入会话级 LangGraph Store；
2. 第二轮使用同一个 `conversation_id` 提问“第一款和第三款呢”；
3. Context Preparation 会读取该会话的最近商品卡，Router 再完成商品 ID 绑定；
4. ShoppingAgent 只接收 Router 已绑定的 ID，不读取历史自行猜测。

例如：

```powershell
# 第一轮和第二轮只要 conversation_id 相同即可；conversation_history 可省略或保持空数组。
$conversationId = 'phase2-ref-001'

# 第一轮：推荐 5 款适合通勤的耳机
# 第二轮：第一款和第三款呢？
```

`conversation_history` 是 chat-service 在正式链路中从其消息库回传的**完整规范消息历史**，用于更丰富的上下文、图片产物和会话回顾；它不是 AI Service 直连多轮测试的前置条件。

仅在以下可选兼容性用例中，才需要手工传历史：验证“chat-service 回传的最新 assistant 商品卡优先于旧 Store 记忆”。这时应把完整来源集合放入 `conversation_history`，不要先切片，以保证“第一、三款”的序号稳定。

示例（可选，不是核心验收步骤）：

```powershell
$history = @(
  @{
    id = 'phase2-ref-001-a1'
    role = 'assistant'
    content = $first.answer
    product_cards = @($first.product_cards)
  }
)

$body = @{
  question = '比较刚才第一款和第三款'
  conversation_id = 'phase2-ref-001'
  user_id = '1'
  conversation_history = $history
} | ConvertTo-Json -Depth 20
```

注意：不要先把 `product_cards` 切成前两项再传。必须传入完整、原顺序的来源集合，这样“第一款和第三款”的序号才有稳定基准。

## 5. 核心人工用例

### A. 文本推荐：LLM Tool Agent 主链

请求：`推荐一款适合通勤的耳机`

通过标准：

- `task_type`/`route` 为 `shopping`；
- `error=false`；
- `tool_calls` 中出现 `recommend_products`，并有真实执行状态与耗时；
- `dispatch_source=agent_tool_loop`；
- 有召回数据时返回至少一张商品卡，商品理由与“通勤耳机”相关；
- 不出现 `GraphRecursionError`、无限等待或无意义的重复工具调用。

若卡片为 0，先核查当前活动 Collection、在售字段和 Milvus 检索日志；这说明“没有候选”，不能仅凭 HTTP 200 判定 Agent 已通过。

### B. 跨轮比较：离散多选绑定

第一轮：`推荐 5 款适合通勤的耳机`。第二轮保持相同 `conversation_id`，无需传 `conversation_history`。

第二轮：`第一款和第三款呢？`

预期：Router 将第 1、3 张卡绑定给下游；ShoppingAgent 应根据问题选择比较或详情类处理，并且只处理这两张商品。不能只命中第一款，也不能重新触发推荐把原集合替换掉。

建议再测：

- `比较第一、三、五款`
- `比较这 5 款`
- `前两款呢？`（在上一轮已经执行比较后，应该继承比较语境）

通过标准：

- `tool_calls` 的主工具是 `compare_products`；
- 不应同时出现新的 `recommend_products`；
- 比较对象与卡片位置完全一致，顺序保持第 1、3（或第 1、3、5）款；
- 如果第一轮实际没有足够卡片，则自然澄清，不能编造商品。

### C. 跨轮详情：只使用已绑定商品

沿用第一轮的相同 `conversation_id`，询问：`第一款多少钱？它适合什么场景？`

通过标准：

- 主工具为 `answer_product_detail`；
- 价格、SKU、在售等事实来自活动商品 Collection/商品事实查询；
- 不触发推荐或比较；
- 推荐卡存在而详情说“商品不存在”时，记录 `trace_id`，按第 7 节的 Collection 一致性问题处理。

反例：在没有任何历史商品卡的全新会话发送 `它多少钱？`。

- 预期是自然澄清“你指的是哪款商品”；
- 不得任选历史文本、Store 旧卡片或随机商品回答。

### D. 纯图片检索

使用 ai-service 运行环境可以访问的一张已有商品测试图。可传完整 URL；相对路径只有在 `IMAGE_BASE_URL` 配置正确且能拼成可访问 URL 时才可使用。

```json
{
  "question": "",
  "image_url": "https://<可从-ai-service-访问的域名>/weloveshop/products/xxx.jpg",
  "conversation_id": "phase2-image-001",
  "user_id": "1",
  "conversation_history": []
}
```

通过标准：

- 纯图片不返回 `AI_SHOPPING_EMPTY_INPUT`；
- 请求仍进入 ShoppingAgent，工具为 `recommend_products`，而不是旧的图像专用回答旁路；
- 有匹配数据时返回商品卡；无匹配时给出清晰的换图/补充需求建议；
- 图片无效或 ai-service 无法访问时返回 HTTP 400 和图片地址相关错误，而不是笼统 500。

图片入口会先做 HEAD 可达性检查，超时约 3 秒；CDN 返回 405（不支持 HEAD）允许继续由后续图像处理兜底。

#### D-1. 回归：上轮详情后只上传新图片

前置：同一会话先发送“这款多少钱？”或任一详情追问；下一轮只发送一张新图片，`question` 保持空字符串。

预期：**新上传图片代表新的图片检索意图，优先级高于上一轮详情语境**，必须路由至 `shopping` 并调用一次 `recommend_products`。

当前实测“第二轮空文本 + 图片没有检索”是 **Phase 2 的真实回归 Bug**：Router 对当前图片的优先级不足，错误继承了上一轮详情语境。它不是 Phase 3 候选质量问题。修复方向是把“当前轮有图片且无文本”作为明确的图片检索输入语义，在 Router 的 LLM 指令和测试中明确：不继承上一轮 recommend/compare/detail 操作，路由至 Shopping；不需要靠关键词猜测。

### E. 图文检索

请求：`找和图中类似的跑鞋，预算 500 元以内`，同时传入上述可访问图片 URL。

Phase 2 通过标准：

- ShoppingAgent 选择 `recommend_products`；
- 一次请求内走图文候选生成与融合路径，最终仍由同一个 ShoppingAgent 生成回答；
- 不出现“没有收到商品问题”；
- Agent 不绕开 `recommend_products` 改走旧图片旁路，也不因图片输入重复调用工具。

“预算 500 元以内”没有结果、但能找到 500 元以上相似跑鞋，是当前缺少 `exact / alternative` 诚实替代策略：属于 **Phase 3**。当前严格预算过滤后返回空是已知限制；Phase 3 才会保留同品类候选，标记为“店内参考”，并说明它超出预算，不能伪称符合。

### F. 宽泛文本品类与偏好隔离

请求一：`夏天出油多，有什么控油又清爽的护肤品？`

- 预期进入 `shopping`，并调用推荐工具；
- 宽泛品类不应因“控油/清爽/夏天”这类自然条件被早期硬过滤成“找不到”；
- 有数据时返回护肤类商品，不相关时说明实际数据限制。

请求二：在 AI Service 直连测试中，通过请求体显式注入 `skin_type` 和 `preference_tags`。这不是让终端用户手填的聊天文本；正式链路中由 chat-service / 用户画像带入。示例：

```json
{
  "question": "推荐一款适合通勤的耳机",
  "conversation_id": "phase2-pref-isolation-001",
  "user_id": "1",
  "skin_type": "油皮",
  "preference_tags": ["清爽", "控油"],
  "conversation_history": []
}
```

建议先用完全相同的问题发送一条不带这两个字段的基线请求，再发送上述请求，比较回答文本、工具选择和商品卡：

- 预期耳机结果和理由中不出现“油皮、控油、肤质”等护肤语境；
- 本阶段关闭长期行为偏好和自动偏好 Proposal，基础标签不能污染无关品类。

### G. 复杂问题：Shopping 与 Knowledge 都完成

请求：`推荐适合通勤的耳机，同时解释开放式和入耳式耳机的区别。`

通过标准：

- `route`/`task_type` 表示复杂任务，`orchestrator_mode=complex`；
- `sub_results` 同时包含 Shopping 与 Knowledge 的有效输出；
- 最终回答同时给出商品建议和两类耳机差异；
- 一个子任务失败时，另一个成功结果仍应保留，并明确失败部分；
- 不允许复杂子任务重新回到全局 Router 造成循环或重复规划。

### H. 请求级工具保护与观测

该保护是**单个 HTTP 请求内部**的保护，不是跨两次聊天请求的缓存。模型是否会在一次对话内主动重复调用工具并不稳定，所以人工验收与自动化验收应分开：

1. 人工验收：对任意推荐请求使用 `/api/assistant/stream`，在 `final.tool_calls` 或日志中检查：正常只有一次 `recommend_products`；它完成后不能紧接 `compare_products` 或 `answer_product_detail`。这能验证“没有发生多能力游走”。
2. 自动化证明：运行 `tests/test_shopping_tool_guard.py`。其中会**人为模拟**同一 Agent run 内两次完全相同的 `recommend_products` 调用，断言底层 handler 只实际执行一次，第二条记录是 `status=deduplicated`、`deduplicated=true`；也模拟推荐后切换比较、以及越权商品 ID 被拦截。
3. 若线上某次模型真的重复调相同参数，响应的 `tool_calls` 中第二条应为 `deduplicated=true`、`duration_ms=0`，不会再次访问 Milvus / Rerank。这个情形不是普通人工输入可以稳定复现的前置条件。

常规观察字段：

- 每个工具记录应包含 `tool_name`、`status`、`duration_ms`；
- 正常工具来源为 `dispatch_source=agent_tool_loop`；
- 若同参数工具被模型重复请求，第二次记录应标记 `deduplicated=true`，并复用本轮结果，不应再次访问 Milvus/Rerank；
- 一轮已成功推荐后，Agent 不应再混用 `compare_products` 或 `answer_product_detail`；
- 仅当 Agent Tool Loop 异常时才允许看到 `dispatch_source=restricted_rule_fallback`。

`restricted_rule_fallback` 不是正常通过结果。发现后要保留请求体、完整响应、`trace_id` 和对应 ai-service 日志。

### I. 流式契约

对任一文本推荐用例改用 `/api/assistant/stream`，使用能够显示 SSE 的客户端。

通过标准：

- 存在 `start` 和最终 `done`；
- 有工具执行时可看到相应的工具事件；
- `final` 中商品卡、回答和非流式调用结果语义一致；
- 不可出现 `done` 缺失、`final` 在 `done` 之后、无限 token 或重复输出完整回答。

## 6. 验收记录模板

每个用例可按下表记录，至少覆盖 A、B、C、D、E、G、I：

| 用例 | 输入与前置历史 | HTTP/错误 | 路由与工具 | 业务结果 | trace_id | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| A 文本推荐 | `推荐通勤耳机` |  |  |  |  |  |
| B 离散多选 | 第一轮完整 5 卡 + `第一款和第三款呢` |  |  |  |  |  |
| C 详情 | 第一轮完整卡 + `第一款多少钱` |  |  |  |  |  |
| D 纯图片 | 图片 URL，无文本 |  |  |  |  |  |
| E 图文 | 跑鞋文本 + 图片 |  |  |  |  |  |
| G 复杂 | 推荐耳机 + 知识解释 |  |  |  |  |  |
| I SSE | 文本推荐流式 |  |  |  |  |  |

## 7. 常见失败定位

| 现象 | 首先判断 | 处理方向 |
| --- | --- | --- |
| `product_cards=[]`，HTTP 200 | 可能是无候选，不代表 Agent 成功 | 查活动 Collection、`status`、Milvus 检索和重排日志 |
| `dispatch_source=restricted_rule_fallback` | LLM Tool Agent 正常链路异常 | 用 `trace_id` 查 Agent 异常、模型响应与 Tool Guard 日志 |
| `GraphRecursionError` | 不是正常现象 | 保留完整日志；当前正常“模型选工具 → 工具返回 → 模型回答”不应触发该错误 |
| 图片 HTTP 400 | 图片地址不可达或未能绝对化 | 查 `IMAGE_BASE_URL`、URL 可访问性、CDN HEAD 策略和图片格式 |
| 推荐有卡，比较/详情说不存在 | 活动 Collection 选择不一致或商品状态变动 | 查三路开关、两个 Collection 名和该 `product_id` 的 `status` |
| 第一、三款只处理第一款 | Router 商品绑定或传入历史结构错误 | 确认传入完整有序 `product_cards`，记录 `trace_id` 和 Router 输出 |
| 一个请求持续很久 | 可能是模型、检索、重排或重复工具调用 | 对照 `tool_calls.duration_ms`、模型调用次数、`deduplicated` 与 ai-service 时间日志；不要用提高超时掩盖 |

## 8. 通过门槛

本阶段 AI Service 人工验收通过，至少同时满足：

- 文本、纯图和图文都经过 ShoppingAgent，而非文本/图片两套最终回答旁路；
- 正常 Shopping 请求的工具来源为 `agent_tool_loop`；
- 推荐、比较、详情由 Agent 决定高层工具，且一轮不混用多个主能力；
- 跨轮“第一款和第三款”能保留两个绑定商品并正确处理；无上下文指代会澄清而不编造；
- 推荐与后续详情读取同一活动商品 Collection；
- 复杂的“商品推荐 + 商品知识”能保留两个子任务结果；
- SSE 保持 `final → done` 契约；
- 没有 `GraphRecursionError`、不可解释的 500、无限循环或正常请求落入 `restricted_rule_fallback`。

完成本文件后，才进入 `chat-service` 会话持久化、前端商品卡、真实上传图片和端到端人工体验验收。它们不在本次 AI Service 独立验收范围内。
