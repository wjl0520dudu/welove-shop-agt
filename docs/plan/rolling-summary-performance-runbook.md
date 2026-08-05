# 统一滚动摘要：Token 与性能对比实验

本实验验证的不是单轮问答，而是同一会话在积累较长历史后，滚动摘要是否能降低后续 Router / Chitchat 的上下文 Token，同时不降低多轮路由正确性。

评测直接调用 ai-service，使用 20 个受控长会话场景。每个场景由离线 fixture 构造出至少 20 条可见消息和不少于 8000 字符的旧历史；实验组先生成一次摘要，保留最近 4 条原文，再连续发送 3 个追问。这样不写入生产会话，也不会让一组模型输出污染另一组输入。

## 统一参数

两组都使用相同的语义参数：

```dotenv
CONVERSATION_SUMMARY_TRIGGER_MESSAGES=20
CONVERSATION_SUMMARY_KEEP_MESSAGES=4
CONVERSATION_SUMMARY_MAX_CHARS=1600
```

本评测直接调用 ai-service：`--mode` 构造完整历史或“摘要 + 最近消息”的请求形态，
`CONVERSATION_SUMMARY_ENABLED` 则确保 ai-service 实际接受或忽略摘要。每组必须按下文切换该值并重启 ai-service；Runner 会检查本地配置是否与 `--mode` 一致，避免误跑。

## 1. 基线：完整历史

先设置基线组配置并重启 ai-service：

```dotenv
CONVERSATION_SUMMARY_ENABLED=false
CONVERSATION_SUMMARY_TRIGGER_MESSAGES=20
CONVERSATION_SUMMARY_KEEP_MESSAGES=4
CONVERSATION_SUMMARY_MAX_CHARS=1600
```

再以两个场景做低成本连通性检查：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode full-history `
  --evaluation-run-id summary-smoke-full-v4 `
  --continuation-turns 1 `
  --case-limit 2

```

然后切换实验组配置并重启 ai-service：

```dotenv
CONVERSATION_SUMMARY_ENABLED=true
CONVERSATION_SUMMARY_TRIGGER_MESSAGES=20
CONVERSATION_SUMMARY_KEEP_MESSAGES=4
CONVERSATION_SUMMARY_MAX_CHARS=1600
```

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode rolling-summary `
  --evaluation-run-id summary-smoke-rolling-v4 `
  --continuation-turns 1 `
  --case-limit 2
```

确认两个报告都有 `final_token_usage.sample_count`，且滚动组有
`summary_token_usage.sample_count` 后，切回对应配置并执行正式实验：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode full-history `
  --evaluation-run-id summary-long-full-v4 `
  --continuation-turns 3 `
  --trigger-message-count 20 `
  --keep-messages 4 `
  --minimum-old-prefix-chars 8000
```

## 2. 实验组：滚动摘要

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode rolling-summary `
  --evaluation-run-id summary-long-rolling-v4 `
  --continuation-turns 3 `
  --trigger-message-count 20 `
  --keep-messages 4 `
  --minimum-old-prefix-chars 8000
```

## 3. 汇总报告

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.compare_summary_context_perf `
  --full evals/reports/summary-long-full-v4.json `
  --rolling evals/reports/summary-long-rolling-v4.json `
  --output evals/reports/summary-long-comparison-v4.json
```

关注报告中的：

- `route_pass_rate`、`conversation_pass_rate`：摘要有没有损伤上下文理解；
- `context_chars`：传给模型的上下文体积是否下降；
- `final_token_saving`：60 次后续追问的累计 Token 节省；
- `summary_generation_total`：20 次摘要生成的额外成本；
- `end_to_end_saving`、`break_even_future_turns`：扣除摘要成本后的净收益和回本所需后续轮数；
- `latency_ms.p50/p95`：用户后续追问的延迟变化。摘要生成是 chat-service 异步工作，不计入用户单轮等待时间。

本实验约 140 次 LLM 调用（60 基线追问 + 20 摘要 + 60 实验组追问），有成本。建议先以 `--continuation-turns 1` 做连通性检查，确认 LangSmith token 已采集后再运行正式 3 轮实验。
