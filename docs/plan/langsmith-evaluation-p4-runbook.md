# P4：四组 Agent Variant 对比实验操作手册

## 目的

在同一套 142 条 Golden Dataset、同一模型、同一产品/知识库依赖和相同串行并发度下，量化以下三项改造的实际收益：

- ShoppingAgent 的 DeepAgent Skills 运行时；
- KnowledgeAgent 的 DeepAgent Skills 运行时；
- Router 的持久化滚动摘要。

P4 不会修改线上主链，也不会为了比较而把已删除的历史实现接回当前代码。它只切换当前代码中已保留、已验收的三个运行时开关，并以报告中记录的实际配置为准。

## 四组实验

| Variant | Shopping Skills | Knowledge Skills | Router 滚动摘要 |
|---|---:|---:|---:|
| `legacy` | `false` | `false` | `false` |
| `skills` | `true` | `true` | `false` |
| `summary` | `false` | `false` | `true` |
| `current` | `true` | `true` | `true` |

`legacy` 与 `skills` 可使用 142 条通用 Golden Dataset 对比 Agent 主链。滚动摘要不应使用该全量集：它不包含 `conversation_summary`，开关不会实际参与上下文构造。`summary` 与 `current` 的摘要维度改用 [滚动摘要专项性能实验](rolling-summary-performance-runbook.md)。

## 前置条件

1. 确认 `LANGSMITH_TRACING=true`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT` 均已配置；无需修改这些值。
2. 确认 Golden Dataset 已同步为 `welove-shop-agent-golden-v1`，且数量为 142。
3. 启动 PostgreSQL、Redis、Milvus 和 ai-service 所需的现有依赖；本阶段由 ai-service HTTP 接口执行，不经过 H5。
4. 在开始前记录当前 Git Commit。四组必须从同一个 Commit 运行。

## 每组执行步骤

在 `ai-service/.env` 仅修改本组对应的三个值，然后重启 ai-service。`.env` 是本地配置，不能提交。

```dotenv
# legacy
SHOPPING_DEEP_AGENT_ENABLED=false
KNOWLEDGE_DEEP_AGENT_ENABLED=false
ROUTER_ROLLING_SUMMARY_ENABLED=false
```

将值替换为上表中下一组的配置并重启服务。每次确认启动日志无配置加载错误后，在 `ai-service` 目录执行一次完整实验：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_langsmith_experiment `
  --variant legacy `
  --experiment-prefix p4-legacy-v1 `
  --evaluation-run-id p4-legacy-v1-001 `
  --timeout-seconds 60 `
  --max-concurrency 1 `
  --include-stream
```

按同一命令分别替换为：

| Variant | `--variant` | `--experiment-prefix` | `--evaluation-run-id` |
|---|---|---|---|
| `legacy` | `legacy` | `p4-legacy-v1` | `p4-legacy-v1-001` |
| `skills` | `skills` | `p4-skills-v1` | `p4-skills-v1-001` |
| `summary` | `summary` | `p4-summary-v1` | `p4-summary-v1-001` |
| `current` | `current` | `p4-current-v1` | `p4-current-v1-001` |

每组完成后保留 `evals/reports/p4-*-v1.json`。脚本会同时校验两层证据：评测进程记录的配置元数据，以及每个 HTTP 响应中服务端实际返回的 `shopping_runtime` / `knowledge_runtime`。汇总工具会拒绝名称、客户端 `.env` 或服务端实际 runtime 不一致的报告，避免只改 `.env` 却没有重启 ai-service 时产生错误对比。

## 汇总并生成对比报告

四组全部完成后运行：

```powershell
D:\dev\env\conda_envs\wlagt\python.exe -m evals.run_p4_matrix `
  --report legacy=evals/reports/p4-legacy-v1.json `
  --report skills=evals/reports/p4-skills-v1.json `
  --report summary=evals/reports/p4-summary-v1.json `
  --report current=evals/reports/p4-current-v1.json
```

输出文件：

- `evals/reports/p4-matrix.json`：可供后续脚本、图表和复盘使用的结构化结果；
- `evals/reports/p4-matrix.md`：人工评审用横向表格。

## 如何解读结果

- 质量：优先看 `Contract Pass Rate`、`Task Success Rate`，再按 `scenario_breakdown` 和失败原因核查是否只在某一类场景改善。
- 体验：看 P50/P95 延迟与 P95 TTFT。相对 Legacy 的负值表示更快。
- 成本：看真实 LangSmith LLM Leaf Trace 汇总的 Token 总量和每请求 Token。Token 样本数不足 142 时，不把该项用于结论。
- 失败归因：先看 `failure_reason_counts`，再在 LangSmith 用 `evaluation_run_id`、`evaluation_case_id`、`evaluation_variant` 过滤具体 Trace。

不要仅凭整体平均数得出“Skills 一定更好”的结论。只有在同一批数据和依赖下，质量不回退且延迟/Token 或关键场景指标有正向变化，才确认该改造有效。

## 已知边界

- 142 条串行且包含流式请求，完整四组运行耗时较长，也会产生真实模型费用；先使用 P3 的 `--limit 5` 做连通性冒烟，再启动正式四组。
- 滚动摘要只有在多轮 Case 经过足够轮次或字符阈值时才会体现；报告应单独审阅带 `setup` 的上下文、多轮和历史回顾场景。
- P4 是运行时组合实验，不等同于跨 Git 历史版本对比；若要对比已不存在的代码实现，应另建只读 worktree 和独立数据/环境。
