# 滚动摘要专项性能实验

本实验不复用 142 条通用 Golden Dataset：该数据集不携带 `conversation_summary`，无法测出摘要开关的效果。

专项集固定为 20 条长会话场景，覆盖早期预算/偏好继承、商品推荐/对比、知识追问、对话回顾、闲聊确认和话题切换。

每个场景包含：

- 一段正文达到 `ROUTER_SUMMARY_CHAR_THRESHOLD` 的较早历史；
- 最近 10 条保留原文；
- 触发摘要后连续 3 条追问。

摘要组对同一会话只生成一次初始摘要，并在 3 条后续问题中复用它；如最近窗口继续滑动，尚未达到下一次阈值的消息以“未压缩桥接消息”保留，不允许丢失上下文。完整历史组每一条追问都携带完整原文。两组使用相同的固定可见历史回复，避免某一组的生成答案污染另一组的后续输入。

## 对照组：完整历史

在 `.env` 设置并重启 ai-service：

```dotenv
ROUTER_ROLLING_SUMMARY_ENABLED=false
```

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode full-history `
  --evaluation-run-id summary-long-full-v3 `
  --continuation-turns 3 `
  --minimum-prefix-chars 8000
```

## 实验组：滚动摘要

在 `.env` 设置并重启 ai-service：

```dotenv
ROUTER_ROLLING_SUMMARY_ENABLED=true
```

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_summary_context_perf `
  --mode rolling-summary `
  --evaluation-run-id summary-long-rolling-v3 `
  --continuation-turns 3 `
  --minimum-prefix-chars 8000
```

输出位于 `evals/reports/summary-perf-*.json`。每次运行的 LangSmith Trace 可使用 `evaluation_run_id` 过滤。

两组完成后自动汇总：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.compare_summary_context_perf `
  --full evals/reports/summary-long-full-v3.json `
  --rolling evals/reports/summary-long-rolling-v3.json `
  --output evals/reports/summary-long-comparison-v3.json
```

## 解读

- `route_pass_rate`：全部连续追问的路由正确率；`conversation_pass_rate`：三条追问均正确的会话比例。
- `context_chars.sent_total`：所有后续轮进入 Router/Chitchat 的可见上下文总字符数。
- `latency_ms`：只统计用户当前轮 `/run` 延迟；摘要生成作为 chat-service 异步工作，不计入用户等待。
- 汇总中的 `final_turn_saving` 是 60 条后续请求的累计节省；`summary_generation_total` 是摘要 LLM 的一次性累计成本；`end_to_end_saving` 才是两者相减后的真实净节省。`break_even_future_turns` 以同类后续轮的实测节省估算回本所需次数。

本专项集总共 20 个会话 × 3 条连续追问：完整历史组为 60 次用户请求；摘要组为 20 次初始摘要生成 + 60 次用户请求（若桥接消息再次达到阈值才会额外汇总）。它不包含昂贵的 SSE 重放。使用 `--minimum-prefix-chars 8000` 时，每个会话的 `initial_eligible_prefix_content_chars` 都保证不少于 8000，与 chat-service 的实际调度阈值使用同一“消息正文字符数”口径。
