# LangSmith 多 Agent 可观测性接入说明

## 目标

让一次 `/api/assistant/run` 或 `/api/assistant/stream` 请求在 LangSmith 中形成可读的运行树，而不改变现有 FastAPI、SSE、LangGraph Checkpoint 或 DeepAgent Skills 主链。

```text
assistant.request
├─ assistant.router
├─ assistant.planner                 # 仅复杂任务
├─ shopping-agent
│  └─ shopping-agent.tool-loop
│     ├─ read Skill
│     └─ 商品工具 / Script
├─ knowledge-agent
│  └─ knowledge-agent.tool-loop
│     ├─ read Skill
│     └─ search_knowledge
└─ chitchat-agent
```

复杂任务中，Planner 生成的每个子任务以 `assistant.task.<id>` 作为父节点，继续带有 `domain:shopping`、`domain:knowledge` 或 `domain:chitchat` 标签。

## 运行配置

根请求统一生成以下信息：

- `run_name=assistant.request`；
- tags：`welove-shop-ai`、`multi-agent`、入口、同步或 SSE、文本或图片；
- metadata：请求随机标识、会话和用户的单向短哈希、是否流式、是否携带图片；
- `configurable.thread_id`：真实 `conversation_id`，仅用于 LangGraph Checkpoint 的正确会话隔离。

子 Agent 从根配置派生，保留 LangSmith callbacks、tags 与 metadata。Shopping/Knowledge 内部 Agent 可改用独立 `thread_id`，但不会脱离父 Trace。

metadata 不包含用户问题、聊天历史、手机号、JWT、API Key、原始用户 ID 或用户画像。请求和模型正文是否上传由环境变量控制。

## 配置

`.env.example` 默认安全屏蔽输入输出。当前本地 `.env` 为调试用途，显式设置为不屏蔽；生产环境应改为 `true`，或在确认数据合规后再开启完整正文追踪。

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=仅放在本地.env
LANGSMITH_PROJECT=welove-shop-ai-dev
LANGSMITH_ENVIRONMENT=development
LANGSMITH_HIDE_INPUTS=false
LANGSMITH_HIDE_OUTPUTS=false
```

项目使用 LangChain/LangGraph 1.x 的 `LANGSMITH_*` 变量，不再并行写入旧版 `LANGCHAIN_*` 变量。

## 验收

1. 重启 ai-service，调用一次简单商品推荐和一次“推荐耳机，同时解释开放式与入耳式区别”。
2. 在 `welove-shop-ai-dev` 项目中按 API 请求的 `X-Trace-Id` 搜索对应运行。
3. 简单请求应看到 `assistant.request → assistant.router → shopping-agent`；复杂请求还应出现 `assistant.planner` 和多个 `assistant.task.*`。
4. 检查每个子 Agent 下是否看到自己的模型调用、Skill 读取与真实工具调用；如果缺失，记录 Trace URL 和 `X-Trace-Id` 以便排查配置传播。

## Studio（仅本地调试）

安装 `langgraph-cli[inmem]` 后，在 `ai-service` 目录运行：

```powershell
langgraph dev --no-reload
```

然后用 LangSmith Studio 打开：

```text
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

Studio 服务器独立于 uvicorn，仅用于看图拓扑和调试。业务端到端验收仍使用 FastAPI 接口，避免 Studio 的手工 State 输入绕过 API 的请求状态构建。

本地 in-memory 持久化会在 `.langgraph_api/` 持续写入 checkpoint/operation
文件。Windows 下文件监听器可能把这些内部文件误判为源码变动并反复打印
`watchfiles.main: changes detected`；因此本项目使用 `--no-reload`，代码变更
后手动重启 Studio 服务即可。
