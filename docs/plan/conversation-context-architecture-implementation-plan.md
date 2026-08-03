# 多轮会话上下文改造：实现与回归计划

## 目标

让 Shopping、图文检索和复杂 DAG 在同一会话中能够稳定理解“这两款”“刚才图片里的商品”等追问，同时不向 H5 用户暴露内部编排过程。

## 本次实现

1. `chat-service` 在每次请求 AI 前读取最近会话窗口，并将消息文本、图片 URL、商品卡片、任务类型和 `agent_meta` 一起传入 `conversation_history`。
2. `ai-service` 在 Router 前执行 `ContextResolver`：
   - 最近一条带商品卡片的 assistant 消息是商品指代的权威来源；
   - “这两款/那两款”只有来源消息恰好包含两张卡片时才直接解析；
   - 来源含三张及以上卡片时返回澄清，禁止静默选择前两张；
   - 将解析出的卡片写入本轮 state-local `business_memory`，供 ShoppingAgent 的 Compare/Detail Capability 使用。
3. 图文检索返回商品卡片后，也会写入会话商品记忆，和文本推荐行为对齐。
4. DAG 的 plan/subtask 仍保留为 SSE 诊断事件与持久化元数据，但不再作为 `token` 写入聊天回答；H5 不再渲染 DAG 进度面板。

## 不变的边界

- ContextResolver 不负责意图路由、检索或商品推荐；它只解析会话引用并限定上下文。
- `last_product_cards` 仍保留为兼容缓存，但用户追问优先使用消息表中的卡片工件。
- DAG 最终合成答案、商品卡片、来源仍照常持久化并在刷新后回放；仅隐藏内部任务过程。

## 测试 Agent 回归清单

### 图文与文本商品集合隔离

1. 文本推荐两款 A/B。
2. 上传图片，图文检索推荐两款 C/D。
3. 追问“这两款对比一下”。

预期：比较 C/D，不得回退到 A/B；工具轨迹应为 `compare_products`，结果卡片为 C/D。

### 指代不唯一时澄清

1. 推荐三款商品。
2. 追问“这两款哪个好”。

预期：澄清需要哪两款，不得默认比较前两款，也不得重新检索。

### 普通多轮历史

1. 推荐两款商品。
2. 追问“第二个多少钱/适合什么肤质”。

预期：上下文路由到 Shopping，命中上一条卡片中的对应商品。

### DAG 输出隔离与刷新

1. 发送会触发复杂 DAG 的“推荐 X，然后问 A 和 B 能否一起使用”请求。
2. 观察流式过程和最终回答。
3. 刷新会话页面。

预期：用户只看到最终聚合回答、商品卡片和来源；不显示“多任务处理完成”、子任务标题、路由理由或依赖层级；最终回答及卡片刷新后仍存在。

## 已完成静态校验

- Python 相关模块 `py_compile`；
- `git diff --check`；
- `mvn -pl services/chat-service -am compile -DskipTests`。

## 统一滚动摘要实现（2026-08）

当前上下文主链已收敛为：

```text
chat_svc.message（完整、权威原文）
  → conversation_context.summary（已压缩的较早前缀）
  + 最近 N 条可见原文
  → resolve_context 组装唯一 messages
  → Router / ChitchatAgent 共用
```

- `chat-service` 在助手消息落库后异步执行摘要更新；当前 SSE 回复不等待该 LLM 调用。
- `conversation_context` 仍保持每会话一行；V7 仅增加 `summary_covered_message_id`，记录摘要已覆盖到的消息，避免重复压缩，不新建第二套记忆表。
- 摘要仅接收用户/助手的可见文本、图片标记与展示商品卡关键字段；不输入 Tool、DAG、Judge、Prompt 或运行时状态。
- `resolve_context` 将“持久化摘要 + 最近原文”作为同一份 LangChain messages 注入 Router 与 Chitchat；Shopping / Knowledge 继续只获取 Router 已消解的当前任务和绑定实体。
- ChitchatAgent 不再独立使用 `SummarizationMiddleware`，避免与持久化摘要产生两份不同的会话事实。
- 阈值统一配置：`ROUTER_ROLLING_SUMMARY_ENABLED`、`ROUTER_SUMMARY_TURN_THRESHOLD`、`ROUTER_SUMMARY_CHAR_THRESHOLD`、`ROUTER_CONTEXT_RECENT_MESSAGE_WINDOW`、`ROUTER_SUMMARY_MAX_CHARS`。AI Service 的 `.env` 与 `.env.example` 已同步；chat-service 使用同名环境变量或其默认值。

默认策略为：保留最近 10 条可见原文；当可压缩的新前缀达到 4 个完整轮次（8 条消息）或 4000 字符时，异步更新摘要。未达到窗口边界时不摘要，因为全部对话仍以原文形式可见。
