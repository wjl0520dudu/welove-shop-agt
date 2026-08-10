# Phase 5：Planner、DAG 与流式返回收敛开发计划

> 状态：已开发，待真实 API / H5 验收  
> 前置版本：`feat(ai): 完成 Phase 3 候选评估与诚实替代策略`、`feat(ai): 增加闲聊智能体与未知请求自然兜底`  
> 上位计划：[agent-stability-convergence-implementation-plan.md](agent-stability-convergence-implementation-plan.md)

## 1. 目标与边界

本阶段只改造**复杂请求**的执行和返回方式：让 Router 已经识别出的 `complex` 请求由 Planner 生成 DAG，DAG 中各领域任务按依赖执行，并在每一个任务完成时立即向前端发送结果。

目标链路：

```text
resolve_context
  → Router LLM（一次：上下文理解、指代消解、simple/complex 判断）
  → complex ?
      ├─ 否：保持现有 Shopping / Knowledge / Chitchat / Unknown 简单链路
      └─ 是：Planner LLM（一次）
            → DAG Executor
                ├─ ShoppingAgent
                ├─ KnowledgeAgent
                └─ ChitchatAgent
            → 当前顺序子任务逐 token SSE
            → 子任务完成后发出 subtask_result 元数据
            → final（兼容性汇总） → done
```

本阶段明确不做：

- 不改变 `resolve_context`、Router 的上下文理解职责或简单请求主链；
- 不增加 Synthesis LLM，也不增加新的语义判断或关键词规则；
- 不重构既有 `TaskExecutionResult` / `sub_results` 为全新的 `AgentArtifact` 类型；
- 不改 Shopping 候选召回、Candidate Judge、偏好软排序或 Knowledge 风险策略；
- 不引入 Agent 加购/HITL 闭环。

## 2. 当前实现与问题

当前复杂链路为：

```text
route_intent
  → plan_complex
  → execute_dag
  → synthesize_final
  → format_response
```

当前已有且继续复用的能力：

- Router 已能将复杂请求标记为 `complex`；
- `plan_complex` 已使用结构化 LLM 生成子任务 ID、问题、领域、依赖与图片使用标记；
- `build_task_levels()` 已校验任务数量、深度、重复 ID、非法依赖与环，并生成并发拓扑层；
- `scope_task_images()` 已限制图片只能传给允许使用图片的购物子任务；
- 同层任务已具备并发、依赖等待、超时和失败隔离；
- 子任务通过 Planner 指定的领域直接调用 Shopping、Knowledge 或 Chitchat 节点，不重新进入顶层 Router；
- 前置任务的商品卡、来源与回答已可注入依赖任务。

需要收敛的问题：

1. `execute_dag` 完成全部任务后才返回 state，之后仍要经过 `synthesize_final`，用户必须等待最慢的任务。
2. `_build_orchestrator_answer()` 用固定模板把所有回答重新拼接，形成机械话术，也阻塞已完成结果的展示。
3. `_execute_subtask()` 仍把完整 `parent_state.messages` 传给每个领域子任务；Shopping 与 Knowledge 会再次看到会话历史，职责边界不清。
4. `execute_dag` 会再次读取 business memory；Preparation 已完成同轮上下文收集，复杂链路不应重复访问 Store/Redis。
5. 现有 `astream()` 只在 `execute_dag` 节点整体结束后发送子任务状态事件，并不发送面向用户的已完成内容。
6. chat-service 对复杂任务收到 `final` 后会覆盖此前累积的回答；H5 也主要依赖 `token` 与 `final`，不能直接消费逐任务结果。

## 3. 设计决策

### 3.1 删除最终等待与硬编码总回答

删除以下复杂链路专用实现：

- `synthesize_final` 图节点；
- `_synthesize_final()`；
- `_build_orchestrator_answer()`；
- “我会分成几个部分依次回答”等固定前缀。

不新增替代性的最终总结 LLM。

`final` 仍保留，以兼容现有 `/run`、SSE 消费者与持久化协议，但它只汇总已有子任务的结构化数据：

- `answer` 为按计划顺序拼接的**原始子任务回答**，不增加额外总结话术；
- `product_cards`、`sources`、`tool_calls` 去重汇总；
- `error`、`error_code`、`message` 表示整轮是否部分失败；
- `task_type=complex`、`sub_results`、`task_levels` 等观测字段保持兼容。

已经收到 `subtask_result` 的前端与 chat-service 不得再次把 `final.answer` 渲染成第二份正文；不支持新事件的旧调用方仍可从 `final.answer` 得到完整结果。

### 3.2 复杂子任务上下文隔离

Router 是复杂任务唯一的跨轮语义理解节点。Planner 接收的输入是 Router 输出的无指代完整问题与受信任快照；Planner 不读完整历史、不再次消解指代、不做顶层路由。

ShoppingAgent 和 KnowledgeAgent 的 DAG 子任务只接收：

- Planner 生成的、无跨轮指代的 `task.question`；
- Router 已绑定的商品 ID、知识实体及相关结构化事实；
- 该任务显式依赖的上游 `sub_results`（商品卡、来源、已验证事实和回答）；
- `use_image=true` 时的当前图片；
- 领域相关的基础偏好软信号。

它们不得接收：

- 完整 `parent_state.messages`；
- 未绑定的历史商品卡、任意旧文本或另一个子任务的结果；
- Redis、Store 或业务记忆的自主读取权限；
- “第一款”“它”“刚才的”等需要再次消解的原始表达。

ChitchatAgent 是例外：它可以继续接收 Preparation 提供的会话历史、滚动摘要和用户基础画像，并由已接入的 middleware 做长上下文摘要/裁剪。即便它出现在复杂任务中，也不负责重做 Router 的领域判定或规划。

实现上，`_execute_dag()` 不再调用 `get_business_memory()`；改为消费 `resolve_context` 已写入 state 的 `business_memory`。`_execute_subtask()` 为 Shopping/Knowledge 构建任务级 messages，而不是复制父级完整 messages。

### 3.3 维持现有结果契约

本阶段不单独新增或大规模重命名 `AgentArtifact`。继续以现有 `sub_results` 与 `TaskExecutionResult` 作为内部结果载体，只补齐流式传输需要的字段。

每一个已完成任务至少提供：

```text
id / question / status / route
answer / product_cards / sources
depends_on / use_image / duration_ms
error / error_code / message
```

依赖任务仍使用现有精简的 `dependency_payload()`。代码只负责事实、依赖和作用域校验，不重新解释用户自然语言。

### 3.4 子任务逐 Token SSE 返回

复杂任务复用现有 `token` SSE，并携带可选 `task_id / sequence`；`subtask_result` 只表示该任务完成并携带商品卡、来源和状态，不再重复整段正文。

推荐 payload：

```json
{
  "task_id": "t1",
  "sequence": 1,
  "question": "推荐适合通勤的耳机",
  "status": "success",
  "answer": "……",
  "product_cards": [],
  "sources": [],
  "error_code": null,
  "message": null
}
```

约束：

- `sequence` 按 Planner 计划中的稳定顺序标注；用户可见的发送顺序也严格遵循该顺序；
- 无依赖任务仍并发启动；后序任务先完成时暂存在内存中，等前序任务发布后立即连续发出，避免回答顺序跳跃；
- 依赖任务仅在其依赖成功后启动；
- 当前顺序任务生成一个 token 就立即发送一个 `token` SSE；后序并发任务的 token 暂存，轮到该任务时按原始 chunk 顺序释放；
- 超时、失败或被依赖阻塞的任务也发送 `subtask_result`，但不泄漏内部异常栈；
- `orchestrator_plan` / `orchestrator_subtask` 可继续保留为诊断事件与 `agent_meta` 数据，不作为用户正文；
- 用户界面不展示 Planner、DAG、Agent、Tool 或内部任务 ID。

实现上使用任务级 token sink 和 `asyncio.as_completed()`：领域 Agent 的模型 chunk 通过 LangGraph stream writer 发送 custom token；DAG executor 按 Planner 顺序放行 token，并在任务结束时发送 `subtask_result`。

## 4. 分步开发计划

### Step 1：收敛复杂图终点

- 从 `StateGraph` 移除 `synthesize_final` 节点与边；
- `execute_dag → format_response`；
- 在 `execute_dag` 结束时仅生成兼容性汇总 state，不调用 LLM、不生成模板化总回答；
- 删除无引用的 `_synthesize_final()`、`_build_orchestrator_answer()` 与旧子任务标题拼接逻辑；
- 保持 `/run` 返回的 `AIResponse` 字段和 `task_type=complex` 兼容。

### Step 2：隔离 DAG 子任务输入

- 移除 `_execute_subtask()` 对完整 `parent_state.messages` 的复制；
- 为 Shopping/Knowledge 构建最小任务 messages：依赖 Artifact 的系统消息 + 当前 `task.question`；
- 仅将本任务的实体绑定、图片作用域、依赖 payload、相关基础偏好写入 `task_state`；
- 对 Chitchat 保留 Preparation 提供的历史/摘要/画像输入；
- 移除 `execute_dag()` 内部的第二次 business memory 读取，复用 state 快照；
- 确保 `_run_business_task()` 仍直接按 Planner 分配的领域执行，不调用 `_route()`。

### Step 3：逐任务流式结果

- 在每个子任务成功、失败、超时或阻塞时构造现有 `sub_result`；
- 领域 Agent 最终回答生成时逐 token 写入任务级 sink；
- `AssistantGraph.astream()` 将任务 token 转为对外 `token`，任务结束再发送 `subtask_result`；
- 不把计划 JSON、工具选择过程或其他内部模型文本写入用户正文；
- 确保 `final` 只在所有任务结束后发送一次，`done` 始终最后发送一次。

### Step 4：chat-service 与 H5 兼容

- chat-service 透传 `subtask_result`；
- chat-service 通过 `token` 累积正文，通过 `subtask_result` 收集商品卡、来源和任务状态；
- 已收到逐任务结果时，`final` 只补充元数据与兼容性字段，不能清空或覆盖累计正文；
- H5 收到一个 `token` 就立即追加到同一条助手消息；收到 `subtask_result` 时渲染对应商品卡和完成状态；
- H5 忽略 `final.answer` 的重复正文，但继续使用 `final` 作为完成态、回放和兜底数据来源；
- 既有简单任务的 `token → final → done` 行为不改变。

### Step 5：清理与观测

- 清理 Phase 5 范围内已无引用的硬编码拼接、旧注释和无效状态字段；
- 继续保留 Planner、子任务、失败阶段、耗时和模型调用次数的安全观测；
- 不记录完整 Prompt、完整历史或敏感原文；
- 不在本阶段清理其他旧 Router/Dispatcher 代码，避免扩大范围。

## 5. 测试与验收计划

### 5.1 AI Service 离线测试

- Router 为复杂请求时，只调用一次 Planner；简单请求不调用 Planner；
- Planner 子任务不会重新调用顶层 Router；
- Shopping/Knowledge 子任务 state 中不含完整会话 messages；Chitchat 保持历史/摘要/画像输入；
- 无依赖任务并发；即使后序任务更快完成，`subtask_result` 仍按 Planner 顺序出现；
- 有依赖任务在前置成功后才执行，并接收正确的依赖 Artifact；
- 非法 ID、非法依赖、循环、超限与图片越权计划触发一次结构化修订，仍失败时安全返回；
- 一项超时/失败时，其他成功 Artifact 仍被发送；
- `final`、`done` 各一次，且无重复正文 token；
- `product_cards`、`sources`、`sub_results` 的去重与现有 API 契约保持兼容。

### 5.2 chat-service 与 H5 测试

- `subtask_result` 可被透传、累计并落库；
- `final` 不覆盖已经流出的复杂任务正文；
- 刷新历史会话后，复杂任务的完整回答、商品卡与来源可正确回放；
- 简单任务 SSE 行为无变化；
- H5 不展示内部事件名、任务 ID、Planner、DAG 或 Agent 术语。

### 5.3 真实验收场景

```text
1. 推荐适合通勤的耳机，同时解释开放式和入耳式耳机的区别
   - Shopping 与 Knowledge 均完成；先完成者先显示。

2. 从刚才前两款中选一个，再判断是否适合通勤
   - 后续判断仅依赖前置商品结果；不重新路由，不猜测历史商品。

3. 推荐一款护肤品，同时说明烟酰胺和视黄醇能否一起使用
   - 一项失败时，另一项结果仍可见；最后明确部分完成。

4. 图文推荐跑鞋，同时说明跑鞋缓震与支撑的区别
   - 图片只进入允许使用图片的 Shopping 子任务，知识子任务不接收图片。
```

### 5.4 验证命令

```powershell
cd ai-service
& 'D:\dev\env\conda_envs\wlagt\python.exe' -m pytest -q tests/test_assistant_graph.py tests/test_assistant_stream_filtering.py tests/test_api_contract.py
& 'D:\dev\env\conda_envs\wlagt\python.exe' -m compileall -q app tests

cd ..
mvn -pl services/chat-service -am test
cd web/welove-shop
npm run build:h5
cd ..\..
git diff --check
```

真实冒烟由用户启动 PostgreSQL、Redis、Nacos、gateway、chat-service 与 ai-service；Shopping/Knowledge 实例按测试问题额外需要 Milvus、模型服务及相应数据源。

## 6. 完成标准

- 复杂任务的用户可见首段不等待所有子任务完成；
- 复杂任务不存在 Synthesis LLM 或硬编码总回答阻塞；
- Shopping/Knowledge DAG 子任务不读取完整会话历史或业务 Store；
- Chitchat 保持必要的会话历史、摘要和画像能力；
- 子任务不重新进入全局 Router；
- 部分失败不丢失已经成功的结果；
- `final → done`、商品卡、来源、聊天记录回放与简单任务 SSE 兼容。
