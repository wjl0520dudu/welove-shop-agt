# Chat Service 同会话并发消息治理方案

> 状态：实施中  
> 范围：`services/chat-service` 为主，`web/welove-shop` 增加兼容请求字段；不改 AI Service Agent 主链。

## 1. 背景与问题

当前文本与图文 SSE 请求均在 `ChatServiceImpl` 中以 `CompletableFuture.runAsync()` 独立执行。两个不同内容若同时进入同一 `conversationId`，会分别落库、读取会话历史并调用 AI Service。

现有 `chat:dedup:{conversationId}:{contentHash}` 只能拦截短时间的相同内容，无法处理不同内容并发、跨网络重试或多实例场景。`finalized` 仅保证单个 SSE 的回调不重复写库，不能保护整个会话。

由此可能产生：

- 两条用户消息、助手回答和商品卡以非预期顺序落库；
- 前一请求的历史读取到后一条用户消息，或两条请求得到不同的历史快照；
- 同一 AI Service / LangGraph thread 同时执行，运行时状态与 Checkpointer 出现竞争；
- 网络重试产生重复 AI 调用或重复助手回答；
- 异步摘要对交错终态重复触发，增加不必要的摘要调用。

## 2. 目标与非目标

### 目标

1. 同一会话任一时刻最多一条 AI 流在执行。
2. 同一用户提交的网络重试不再创建第二条 user/assistant 消息或第二次 AI 调用。
3. 文本、纯图和图文走同一并发保护语义。
4. 正常完成、服务异常、用户停止和 SSE 超时均释放会话锁。
5. 不同会话继续并行；未来多 chat-service 实例也有效。

### 非目标

- 不在服务端构建长期消息队列或自动改写第二条问题。
- 不修改 ShoppingAgent、KnowledgeAgent、Router、LangGraph 业务逻辑。
- 不压缩或删除前端可见历史消息。

## 3. 策略选择：忙时拒绝，不做自动排队

当同一会话已有生成中请求时，新的不同请求返回可识别的 SSE 错误：

```text
code = CHAT_CONVERSATION_BUSY
message = 当前会话正在回复，请等待完成后继续发送
```

原因：第二个问题是否应基于第一个回答追问，属于用户语义，服务端自动排队会改变这一语义并占用 SSE 连接、放大超时。H5 已有 `streaming` 状态，本次只补充后端兜底和明确提示。

同一 `clientRequestId` 的重复提交则识别为幂等重放，不会再次调用 AI。

## 4. 数据与接口设计

### 4.1 请求标识

`StreamChatRequest` 和 `StopMessageRequest` 新增可选 `clientRequestId`。

- H5 真实发送时生成 UUID；同一次网络重试复用。
- “重新生成”创建新的 UUID，维持现有 `retry=true` 不重复写用户消息的行为。
- 老客户端未传时后端生成 UUID，仅失去跨请求幂等识别，不影响调用。

### 4.2 数据库

Flyway `V9` 为 `chat_svc.message` 增加 `turn_id`。

- 同一请求的 user message 和 assistant message 共用 `turn_id`。
- 为 `(conversation_id, turn_id, role)` 建立部分唯一索引，约束每个 turn 最多一条 user 和一条 assistant 消息。
- 助手消息在 AI 调用前以 `status=streaming` 插入为占位；`final` 更新为 `done`，中断更新为 `truncated`/`error`。

该占位消息使幂等重放可辨识“进行中、已完成、已中断”，并避免原先截断路径额外插入未关联助手消息。

## 5. Redis 分布式会话锁

新增 `ConversationTurnGuard`：

```text
key   = chat:conversation:turn-lock:{conversationId}
value = ownerToken（包含 clientRequestId）
```

- 获取：`SET key value NX PX`；租约略大于 SSE 服务端超时。
- 释放：Lua 比较 value 后删除，避免旧请求删除后续请求的锁。
- 锁持有区间：用户消息落库、会话上下文快照构造、AI SSE 调用、助手消息终态落库。
- 所有 terminal 回调在 `finally` 中释放；释放失败只记录日志，不覆盖终态。

不引入 Redisson，复用项目已有 `StringRedisTemplate`，降低依赖与部署复杂度。

## 6. 执行流程

```text
H5 提交 clientRequestId
  → Chat Service 异步任务尝试获取 conversation 锁
    ├─ 锁被其他 turn 占用 → SSE error(CHAT_CONVERSATION_BUSY) → 完成
    ├─ 同 turn 已有记录 → SSE error(CHAT_REQUEST_IN_PROGRESS / COMPLETED) → 不重复调用 AI
    └─ 获取成功
        → 写 user message（retry=false）
        → 写 assistant(status=streaming) 占位
        → 构造 history + summary
        → 调 AI Service SSE
        → final: 更新 assistant 为 done
        → abort/error/timeout: 更新 assistant 为 truncated/error
        → 失效上下文缓存、调度一次摘要、释放锁
```

## 7. H5 兼容

- `buildPayload()` 带 `clientRequestId`。
- 同一次鉴权重试重用该 ID；重新生成使用新 ID。
- stop 快照携带同一 ID，后端可更新对应 streaming 占位消息。
- 收到 `CHAT_CONVERSATION_BUSY` 时展示明确提示，不把它误显示为通用 AI 失败。

## 8. 验收与回归

1. 同会话不同问题并发：第一条正常完成；第二条返回 `CHAT_CONVERSATION_BUSY`；仅一条 AI 请求进入下游。
2. 同会话同 `clientRequestId` 并发：只保留一组 user/assistant 消息与一次 AI 调用。
3. 不同会话并发：两条请求均可流式正常运行。
4. 断流、超时、上游异常：助手占位转为终态且锁释放；下一轮可继续发送。
5. 文本、纯图、图文、复杂 DAG、重新生成：产品卡、`done.messageId`、截断持久化和摘要水位保持正确。
6. Java 测试、Flyway 校验、H5 build、`git diff --check`。

