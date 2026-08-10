# LangSmith 启动后简要验收

## 1. 启动与确认

使用实际安装依赖的 Python 虚拟环境启动 `ai-service`。启动日志应包含：

```text
LangSmith tracing enabled, project=...
```

健康检查：

```powershell
curl.exe http://127.0.0.1:8000/health/live
```

## 2. 简单导购 Trace

请求：

```text
POST http://127.0.0.1:8000/api/assistant/run
```

```json
{
  "question": "推荐一款适合通勤、500元以内的耳机",
  "conversation_id": "langsmith-smoke-shopping-001",
  "user_id": "10001"
}
```

在 `.env` 的 `LANGSMITH_PROJECT` 对应项目中，应看到：

```text
assistant.request
└─ assistant.router
   └─ shopping-agent
      └─ shopping-agent.tool-loop
```

## 3. 知识问答 Trace

```json
{
  "question": "烟酰胺白天能用吗？",
  "conversation_id": "langsmith-smoke-knowledge-001",
  "user_id": "10001"
}
```

应看到 `knowledge-agent`、`knowledge-agent.tool-loop`、Skill 读取与 `search_knowledge`。

## 4. 复杂任务 Trace

```json
{
  "question": "推荐适合通勤的耳机，同时解释开放式耳机和入耳式耳机的区别",
  "conversation_id": "langsmith-smoke-complex-001",
  "user_id": "10001"
}
```

应看到：

```text
assistant.request
├─ assistant.router
├─ assistant.planner
├─ assistant.task.t1 → shopping-agent
└─ assistant.task.t2 → knowledge-agent
```

## 5. 异常反馈

- 没有 Trace：检查 `LANGSMITH_TRACING=true`、API Key 与启动日志。
- 只有根节点或子 Agent 脱离根节点：记录响应头 `X-Trace-Id` 后反馈。
- 本地调试需要完整 Prompt/工具输入时，保持 `.env` 中 `LANGSMITH_HIDE_INPUTS=false`、`LANGSMITH_HIDE_OUTPUTS=false`；生产环境应改为 `true`。

`langgraph dev` 仅用于 Studio 看图调试，不替代正常 FastAPI 接口验收。
